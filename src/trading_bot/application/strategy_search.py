"""Ricerca automatica della strategia migliore con validazione severa.

Data il solo contesto (mercato, periodo, capitale, commissioni), questo modulo
sceglie la strategia più promettente fra tutte quelle disponibili, con la
validazione più rigorosa che il codebase permette, in tre strati:

1. **Holdout finale intoccato** — l'ultima fetta di dati (default 20%) viene
   messa da parte e non partecipa alla *selezione* del campione. Serve per
   misurare la resa su dati mai visti (difesa dal confronto multiplo: scegliere
   "la migliore fra 15" è di per sé una fonte di overfitting).

2. **Walk-forward sullo sviluppo** — sul restante 80% ogni strategia viene
   valutata in walk-forward (finestre IS che ottimizzano i parametri, finestre
   OOS che li testano). La classifica di *selezione* usa lo Sharpe OOS medio.

3. **Prova su dati nuovi** — ogni strategia viene poi riottimizzata sull'intero
   sviluppo e misurata sul holdout. Il campione (il primo per Sharpe OOS) porta
   con sé questa prova; se lì crolla, l'affidabilità è bassa.

``scan_mode`` (rapida/media/lunga/xl) regola quante combinazioni di parametri
provare: più è profondo, più è lento ma accurato.

Note sul realismo: dati di mercato reali (yfinance), commissioni in basis point,
shift di una barra contro il lookahead. Lo slippage non è modellato: le metriche
sono al netto delle sole commissioni.
"""
from __future__ import annotations

import dataclasses
import itertools
import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, wait
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS, AUTOSETTING_GRIDS_BY_MODE
from trading_bot.backtest import run_backtest
from trading_bot.strategies import (
    STRATEGY_SPECS,
    build_strategy_signal,
    validate_strategy_parameters,
)
from trading_bot.walkforward import MIN_TRADE_PER_SCELTA, WalkForwardResult, run_walk_forward

HOLDOUT_RATIO = 0.20        # fetta finale riservata alla prova su dati nuovi
TARGET_WINDOWS = 5          # numero indicativo di finestre walk-forward sullo sviluppo
OVERFIT_SOGLIA = 0.40       # calo Sharpe holdout > 40% vs sviluppo → affidabilità ridotta
MIN_TOTAL_BARS = 150        # sotto questa soglia la validazione severa non ha senso
MIN_DEV_BARS = 100          # barre minime nello sviluppo per il walk-forward
# Margine minimo sul comprare-e-tenere per considerare utile una strategia:
# sotto mezzo punto percentuale è rumore, non un vantaggio.
MARGINE_MINIMO_PCT = 0.5

# Semaforo di affidabilità in lingua semplice.
RELIABILITY_HIGH = "alta"
RELIABILITY_MEDIUM = "media"
RELIABILITY_LOW = "bassa"
RELIABILITY_NONE = "insufficiente"

# Avanzamento: (combinazioni provate, combinazioni totali stimate, messaggio).
ProgressCallback = Callable[[int, int, str], None]
# Ogni quante combinazioni aggiornare l'avanzamento condiviso (evita di
# prendere il lock migliaia di volte al secondo senza che si veda differenza).
PROGRESS_EVERY = 50
# Sotto questo numero di combinazioni la ricerca resta su un solo processo:
# avviare i processi costa circa un secondo e sotto questa mole non si
# recupera. Una ricerca completa sulle 15 strategie sta sempre sopra.
SOGLIA_PARALLELO = 2_000


@lru_cache(maxsize=None)
def count_valid_combinations(strategy_id: str, scan_mode: str) -> int:
    """Quante combinazioni di parametri valide ha una strategia a una profondità."""
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    grid = grids.get(strategy_id)
    if not grid:
        return 0
    names = list(grid.keys())
    values = [grid[name] for name in names]
    valide = 0
    for combo in itertools.product(*values):
        try:
            validate_strategy_parameters(strategy_id, dict(zip(names, combo)))
        except ValueError:
            continue
        valide += 1
    return valide


def count_windows(dev_len: int, is_days: int, oos_days: int) -> int:
    """Numero di finestre walk-forward che entrano nel set di sviluppo."""
    finestre = 0
    start = 0
    while start + is_days + oos_days <= dev_len:
        finestre += 1
        start += oos_days
    return finestre


def estimate_search_combinations(
    n_bars: int,
    *,
    scan_mode: str = "rapida",
    strategy_ids: list[str] | None = None,
    consenti_short: bool = False,
    holdout_ratio: float = HOLDOUT_RATIO,
    target_windows: int = TARGET_WINDOWS,
) -> int:
    """Quante combinazioni verranno provate in totale su un mercato.

    Serve a mostrare all'utente un contatore "X di Y opzioni controllate": ogni
    combinazione viene provata una volta per finestra walk-forward più una volta
    nell'ottimizzazione finale sull'intero sviluppo.
    """
    candidati = costruisci_candidati(strategy_ids, consenti_short)
    holdout_len = max(1, int(round(n_bars * holdout_ratio)))
    dev_len = n_bars - holdout_len
    if dev_len <= 0:
        return 0
    is_days, oos_days = _auto_windows(dev_len, target_windows)
    finestre = count_windows(dev_len, is_days, oos_days)
    passaggi = finestre + 1  # finestre walk-forward + ottimizzazione finale
    return sum(
        count_valid_combinations(c.strategy_id, scan_mode) * passaggi for c in candidati
    )


SUFFISSO_SHORT = " · anche al ribasso"


@dataclass(frozen=True)
class Candidato:
    """Una strategia in un verso: e' l'unita' che la ricerca mette in gara.

    Con il ribasso attivo la stessa strategia corre due volte, solo al rialzo e
    nei due versi, perche' sono due modi di operare diversi e non c'e' motivo di
    dare per scontato quale dei due regga meglio su un certo mercato.
    """

    strategy_id: str
    consenti_short: bool = False

    @property
    def label(self) -> str:
        etichetta = STRATEGY_SPECS[self.strategy_id].label
        return etichetta + SUFFISSO_SHORT if self.consenti_short else etichetta


def costruisci_candidati(
    strategy_ids: list[str] | None, consenti_short: bool
) -> list[Candidato]:
    """Elenco dei candidati: solo rialzo, piu' il ribasso dove ha senso."""
    ids = [sid for sid in (strategy_ids or list(AUTOSETTING_GRIDS.keys())) if sid in STRATEGY_SPECS]
    candidati = [Candidato(sid, False) for sid in ids]
    if consenti_short:
        candidati += [
            Candidato(sid, True) for sid in ids if STRATEGY_SPECS[sid].supports_short
        ]
    return candidati


@dataclass
class StrategyRanking:
    """Riga di classifica: come è andata una strategia in selezione e alla prova."""

    strategy_id: str
    label: str
    # Selezione (walk-forward sullo sviluppo)
    avg_oos_sharpe: float
    avg_is_sharpe: float
    avg_oos_return_pct: float
    wf_efficiency: float
    windows: int
    # Prova su dati nuovi (holdout)
    params: dict[str, int | float]
    holdout_return_pct: float
    holdout_sharpe: float
    holdout_max_drawdown_pct: float
    holdout_trades: int
    reliability: str            # alta | media | bassa | insufficiente
    # Quanto ha fatto meglio (o peggio) del comprare-e-tenere sullo stesso
    # periodo di prova: è il confronto onesto per un motore solo long.
    holdout_excess_return_pct: float = 0.0
    # Operazioni aperte nelle finestre di collaudo dello sviluppo: se sono zero
    # la strategia è rimasta ferma e il suo punteggio 0 non è un merito.
    dev_oos_trades: int = 0
    # Resa del comprare-e-tenere sullo stesso periodo di prova (uguale per tutte
    # le strategie dello stesso mercato, ma serve a chi valuta in un processo
    # separato per restituire un risultato completo).
    holdout_benchmark_return_pct: float | None = None
    # Verso in cui ha corso questa riga: la stessa strategia puo' comparire due
    # volte, solo al rialzo e nei due versi.
    consenti_short: bool = False
    error: str | None = None    # motivo se la strategia non è stata valutabile


@dataclass
class StrategySearchResult:
    symbol: str
    ranking: list[StrategyRanking]
    champion_id: str | None
    champion_label: str | None
    champion_params: dict[str, int | float]
    holdout: dict[str, object]
    development: dict[str, object]
    reliability: str
    verdict_note: str
    holdout_benchmark_return_pct: float
    data_span: dict[str, object]
    settings: dict[str, object]
    # Verso in cui ha corso il campione: la stessa strategia puo' comparire in
    # classifica due volte, solo al rialzo e nei due versi.
    champion_consenti_short: bool = False


def _auto_windows(dev_len: int, target_windows: int = TARGET_WINDOWS) -> tuple[int, int]:
    """Dimensiona le finestre IS/OOS per ottenere ~``target_windows`` finestre."""
    oos_days = max(20, dev_len // (target_windows + 3))
    is_days = max(60, oos_days * 4)
    return is_days, oos_days


def run_strategy_search(
    data: pd.DataFrame,
    *,
    symbol: str = "",
    interval: str = "1d",
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    holdout_ratio: float = HOLDOUT_RATIO,
    target_windows: int = TARGET_WINDOWS,
    optimize_by: str = "sharpe_ratio",
    scan_mode: str = "rapida",
    strategy_ids: list[str] | None = None,
    consenti_short: bool = False,
    progress_callback: ProgressCallback | None = None,
    max_workers: int | None = None,
) -> StrategySearchResult:
    """Cerca la strategia migliore per un singolo mercato con validazione severa.

    ``max_workers`` regola quante strategie vengono valutate in parallelo:
    ``None`` decide da sé in base ai core disponibili e alla mole di lavoro,
    ``1`` forza l'esecuzione sequenziale.
    """
    candidati = costruisci_candidati(strategy_ids, consenti_short)

    n = len(data)
    if n < MIN_TOTAL_BARS:
        raise ValueError(
            f"Servono almeno {MIN_TOTAL_BARS} barre per una validazione severa "
            f"(disponibili {n}). Allarga il periodo o usa un timeframe più fitto."
        )

    holdout_len = max(1, int(round(n * holdout_ratio)))
    dev_len = n - holdout_len
    if dev_len < MIN_DEV_BARS:
        raise ValueError(
            "Dati insufficienti per separare sviluppo e prova su dati nuovi: "
            f"servono più barre storiche (sviluppo {dev_len}, minimo {MIN_DEV_BARS})."
        )

    dev_data = data.iloc[:dev_len]
    holdout_index = data.index[dev_len:]
    is_days, oos_days = _auto_windows(dev_len, target_windows)

    ranking: list[StrategyRanking] = []
    benchmark_return_pct = 0.0

    # Contatore delle combinazioni: è l'avanzamento reale del lavoro, molto più
    # informativo del semplice "quante strategie ho finito".
    finestre = count_windows(dev_len, is_days, oos_days)
    passaggi = finestre + 1
    total = sum(
        count_valid_combinations(c.strategy_id, scan_mode) * passaggi for c in candidati
    )
    provate = 0
    etichetta = ""

    def _segnala(forza: bool = False) -> None:
        if progress_callback is not None and (forza or provate % PROGRESS_EVERY == 0):
            progress_callback(provate, total, etichetta)

    def _combinazione_provata() -> None:
        nonlocal provate
        provate += 1
        _segnala()

    lavoro = _LavoroStrategia(
        data=data, dev_len=dev_len, is_days=is_days, oos_days=oos_days,
        fee_bps=fee_bps, slippage_bps=slippage_bps, initial_capital=initial_capital,
        optimize_by=optimize_by, scan_mode=scan_mode,
    )

    if _usa_parallelo(total=total, n_strategie=len(candidati), max_workers=max_workers):
        etichetta = f"{len(candidati)} strategie in parallelo"
        _segnala(forza=True)
        ranking = _valuta_in_parallelo(
            lavoro=lavoro, candidati=candidati, max_workers=max_workers,
            progress_callback=progress_callback, total=total,
        )
    else:
        for candidato in candidati:
            # Segnala la strategia PRIMA di testarla: a profondità alte una singola
            # strategia può richiedere minuti, e senza questo l'utente resterebbe a
            # guardare "avvio della ricerca" senza sapere cosa sta succedendo.
            etichetta = candidato.label
            _segnala(forza=True)
            ranking.append(_valuta_strategia(lavoro, candidato, _combinazione_provata))

    for riga in ranking:
        if riga.error is None and riga.holdout_benchmark_return_pct is not None:
            benchmark_return_pct = riga.holdout_benchmark_return_pct

    etichetta = "analisi completata"
    provate = max(provate, total)
    _segnala(forza=True)

    # Classifica di selezione: prima chi ha davvero operato (una strategia ferma
    # ha punteggio 0 secco e scavalcherebbe tutte quelle in perdita senza aver
    # fatto niente), poi il punteggio sullo sviluppo; errori in fondo.
    ranking.sort(
        key=lambda r: (r.error is None, r.dev_oos_trades > 0, r.avg_oos_sharpe),
        reverse=True,
    )

    data_span = {
        "symbol": symbol,
        "interval": interval,
        "bars": int(n),
        "start": _fmt(data.index[0]),
        "end": _fmt(data.index[-1]),
        "dev_bars": int(dev_len),
        "holdout_bars": int(holdout_len),
        "holdout_start": _fmt(holdout_index[0]) if len(holdout_index) else "",
        "holdout_end": _fmt(holdout_index[-1]) if len(holdout_index) else "",
        "is_days": int(is_days),
        "oos_days": int(oos_days),
        "scan_mode": scan_mode,
    }
    settings = {
        "initial_capital": float(initial_capital),
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
    }

    champion = next((r for r in ranking if r.error is None and r.windows > 0), None)
    if champion is None:
        return StrategySearchResult(
            symbol=symbol, ranking=ranking, champion_id=None, champion_label=None,
            champion_params={}, champion_consenti_short=False, holdout={}, development={},
            reliability=RELIABILITY_NONE,
            verdict_note="Nessuna strategia ha completato la validazione su questo periodo. "
                         "Prova con più storia o un timeframe diverso.",
            holdout_benchmark_return_pct=round(benchmark_return_pct, 2),
            data_span=data_span, settings=settings,
        )

    development = {
        "avg_oos_sharpe": champion.avg_oos_sharpe,
        "avg_is_sharpe": champion.avg_is_sharpe,
        "avg_oos_return_pct": champion.avg_oos_return_pct,
        "wf_efficiency": champion.wf_efficiency,
        "windows": champion.windows,
    }
    holdout = {
        "sharpe_ratio": champion.holdout_sharpe,
        "total_return_pct": champion.holdout_return_pct,
        "max_drawdown_pct": champion.holdout_max_drawdown_pct,
        "trade_count": champion.holdout_trades,
    }
    return StrategySearchResult(
        symbol=symbol, ranking=ranking,
        champion_id=champion.strategy_id, champion_label=champion.label,
        champion_params=champion.params, champion_consenti_short=champion.consenti_short,
        holdout=holdout, development=development,
        reliability=champion.reliability,
        verdict_note=_verdict_note(champion, benchmark_return_pct),
        holdout_benchmark_return_pct=round(benchmark_return_pct, 2),
        data_span=data_span, settings=settings,
    )


@dataclass
class _LavoroStrategia:
    """Tutto ciò che serve per valutare una strategia su un mercato.

    Sta in un solo oggetto perché in modalità parallela viene spedito ai
    processi figli: se fosse una manciata di argomenti sparsi sarebbe facile
    dimenticarne uno e far divergere il risultato dal percorso sequenziale.
    """

    data: pd.DataFrame
    dev_len: int
    is_days: int
    oos_days: int
    fee_bps: float
    slippage_bps: float
    initial_capital: float
    optimize_by: str
    scan_mode: str


def _valuta_strategia(
    lavoro: _LavoroStrategia,
    candidato: Candidato,
    on_combination: Callable[[], None] | None = None,
) -> StrategyRanking:
    """Walk-forward sullo sviluppo + prova sul holdout per una sola strategia.

    Non solleva mai: una strategia non valutabile torna come riga in errore, in
    modo che non blocchi la ricerca sulle altre.
    """
    strategy_id = candidato.strategy_id
    data = lavoro.data
    dev_data = data.iloc[: lavoro.dev_len]
    holdout_index = data.index[lavoro.dev_len:]

    try:
        wf = run_walk_forward(
            data=dev_data,
            strategy_id=strategy_id,
            is_days=lavoro.is_days,
            oos_days=lavoro.oos_days,
            optimize_by=lavoro.optimize_by,
            fee_bps=lavoro.fee_bps,
            slippage_bps=lavoro.slippage_bps,
            initial_capital=lavoro.initial_capital,
            scan_mode=lavoro.scan_mode,
            consenti_short=candidato.consenti_short,
            on_combination=on_combination,
        )
        # Parametri di produzione + prova su dati nuovi (holdout).
        params = _optimize_on_development(
            data=dev_data, strategy_id=strategy_id, fee_bps=lavoro.fee_bps,
            slippage_bps=lavoro.slippage_bps,
            initial_capital=lavoro.initial_capital, optimize_by=lavoro.optimize_by,
            scan_mode=lavoro.scan_mode, consenti_short=candidato.consenti_short,
            on_combination=on_combination,
        )
        holdout_result = _evaluate_on_holdout(
            full_data=data, dev_len=lavoro.dev_len, holdout_index=holdout_index,
            strategy_id=strategy_id, params=params, fee_bps=lavoro.fee_bps,
            slippage_bps=lavoro.slippage_bps,
            initial_capital=lavoro.initial_capital, consenti_short=candidato.consenti_short,
        )
    except Exception as exc:  # una strategia non valutabile non blocca la ricerca
        return StrategyRanking(
            strategy_id=strategy_id, label=candidato.label,
            avg_oos_sharpe=float("-inf"), avg_is_sharpe=0.0, avg_oos_return_pct=0.0,
            wf_efficiency=0.0, windows=0, params={},
            holdout_return_pct=0.0, holdout_sharpe=0.0,
            holdout_max_drawdown_pct=0.0, holdout_trades=0,
            reliability=RELIABILITY_NONE, consenti_short=candidato.consenti_short,
            error=str(exc),
        )

    hs = holdout_result.summary
    reliability = _reliability(
        dev_oos_sharpe=wf.avg_oos_sharpe,
        holdout_return_pct=float(hs.get("total_return_pct", 0.0)),
        holdout_excess_return_pct=float(hs.get("excess_return_pct", 0.0)),
        holdout_sharpe=float(hs.get("sharpe_ratio", 0.0)),
        holdout_trades=int(hs.get("trade_count", 0)),
    )
    return StrategyRanking(
        strategy_id=strategy_id, label=candidato.label,
        avg_oos_sharpe=wf.avg_oos_sharpe, avg_is_sharpe=wf.avg_is_sharpe,
        avg_oos_return_pct=wf.avg_oos_return_pct,
        wf_efficiency=wf.wf_efficiency, windows=len(wf.windows),
        params=params,
        holdout_return_pct=round(float(hs.get("total_return_pct", 0.0)), 2),
        holdout_sharpe=round(float(hs.get("sharpe_ratio", 0.0)), 3),
        holdout_max_drawdown_pct=round(float(hs.get("max_drawdown_pct", 0.0)), 2),
        holdout_trades=int(hs.get("trade_count", 0)),
        reliability=reliability,
        holdout_excess_return_pct=round(float(hs.get("excess_return_pct", 0.0)), 2),
        dev_oos_trades=sum(int(w.oos_trades) for w in wf.windows),
        holdout_benchmark_return_pct=round(float(hs.get("benchmark_return_pct", 0.0)), 2),
        consenti_short=candidato.consenti_short,
    )


# ── Esecuzione parallela ─────────────────────────────────────────────────────
# Contatore condiviso fra i processi figli, valorizzato dall'initializer del
# pool: ogni figlio ci somma le combinazioni provate, il padre lo legge per
# aggiornare l'avanzamento mostrato.
_CONTATORE_CONDIVISO = None


def _usa_parallelo(*, total: int, n_strategie: int, max_workers: int | None) -> bool:
    """Il parallelismo conviene solo se c'è abbastanza lavoro da distribuire.

    Avviare i processi costa circa un secondo l'uno su Windows: su una ricerca
    piccola sarebbe tempo perso, oltre a rendere l'avanzamento meno leggibile.
    """
    if max_workers is not None and max_workers <= 1:
        return False
    if n_strategie < 2:
        return False
    if max_workers is not None:
        return True          # richiesto esplicitamente: si rispetta la scelta
    if (os.cpu_count() or 1) < 2:
        return False
    return total >= SOGLIA_PARALLELO


def _numero_processi(n_strategie: int, max_workers: int | None) -> int:
    if max_workers is not None:
        return max(1, min(max_workers, n_strategie))
    # Un core resta libero: la ricerca gira in sottofondo mentre si usa il PC.
    return max(1, min(n_strategie, (os.cpu_count() or 2) - 1))


def _init_worker(contatore) -> None:
    global _CONTATORE_CONDIVISO
    _CONTATORE_CONDIVISO = contatore


def _conta_nel_worker() -> None:
    """Somma al contatore condiviso a blocchi, per non prendere il lock
    migliaia di volte al secondo senza che l'utente veda differenza."""
    global _COMBINAZIONI_LOCALI
    _COMBINAZIONI_LOCALI += 1
    if _COMBINAZIONI_LOCALI >= PROGRESS_EVERY:
        _scarica_contatore()


def _scarica_contatore() -> None:
    global _COMBINAZIONI_LOCALI
    if _CONTATORE_CONDIVISO is not None and _COMBINAZIONI_LOCALI:
        with _CONTATORE_CONDIVISO.get_lock():
            _CONTATORE_CONDIVISO.value += _COMBINAZIONI_LOCALI
    _COMBINAZIONI_LOCALI = 0


_COMBINAZIONI_LOCALI = 0


def _valuta_strategia_in_worker(argomenti: tuple[_LavoroStrategia, Candidato]) -> StrategyRanking:
    lavoro, candidato = argomenti
    try:
        return _valuta_strategia(lavoro, candidato, _conta_nel_worker)
    finally:
        _scarica_contatore()


def _valuta_in_parallelo(
    *,
    lavoro: _LavoroStrategia,
    candidati: list[Candidato],
    max_workers: int | None,
    progress_callback: ProgressCallback | None,
    total: int,
) -> list[StrategyRanking]:
    """Valuta le strategie su più processi, mantenendo l'ordine dei candidati.

    Se il pool non parte (ambienti che vietano di creare processi) si ripiega
    sul percorso sequenziale invece di far fallire la ricerca.
    """
    contesto = multiprocessing.get_context("spawn")
    contatore = contesto.Value("q", 0)
    processi = _numero_processi(len(candidati), max_workers)
    etichetta = f"{len(candidati)} strategie in parallelo"

    try:
        with ProcessPoolExecutor(
            max_workers=processi, mp_context=contesto,
            initializer=_init_worker, initargs=(contatore,),
        ) as pool:
            # Prima le strategie con più combinazioni da provare: se la più
            # lunga partisse per ultima, gli altri core resterebbero fermi ad
            # aspettarla e il guadagno svanirebbe.
            per_costo = sorted(
                candidati,
                key=lambda c: count_valid_combinations(c.strategy_id, lavoro.scan_mode),
                reverse=True,
            )
            futures = {
                c: pool.submit(_valuta_strategia_in_worker, (lavoro, c)) for c in per_costo
            }
            rimanenti = set(futures.values())
            while rimanenti:
                _, rimanenti = wait(rimanenti, timeout=0.5)
                if progress_callback is not None:
                    with contatore.get_lock():
                        provate = int(contatore.value)
                    progress_callback(min(provate, total), total, etichetta)
            # L'ordine dei risultati segue i candidati, non quello di arrivo né
            # quello di lancio: così la classifica non cambia fra due lanci.
            return [futures[c].result() for c in candidati]
    except Exception:
        return [_valuta_strategia(lavoro, c) for c in candidati]


def _optimize_on_development(
    *, data: pd.DataFrame, strategy_id: str, fee_bps: float, slippage_bps: float = 0.0,
    initial_capital: float, optimize_by: str, scan_mode: str = "rapida",
    consenti_short: bool = False,
    on_combination: Callable[[], None] | None = None,
) -> dict[str, int | float]:
    """Trova i parametri migliori della strategia sull'intero set di sviluppo.

    Come nella walk-forward, a parità di punteggio vince chi ha davvero operato:
    una combinazione che non apre nessuna operazione totalizza 0 secco e
    verrebbe altrimenti preferita a ogni combinazione in perdita.
    """
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    grid = grids[strategy_id]
    names = list(grid.keys())
    values = [grid[name] for name in names]
    ascending = optimize_by == "max_drawdown_pct"

    best_params: dict[str, int | float] = dict(zip(names, (v[0] for v in values)))
    best_score = float("-inf")
    best_attiva = False

    for combo in itertools.product(*values):
        params = dict(zip(names, combo))
        # I vincoli si controllano prima: le combinazioni impossibili non
        # costano un backtest e quindi non entrano nel conteggio mostrato.
        try:
            validate_strategy_parameters(strategy_id, params)
        except ValueError:
            continue
        try:
            signal = build_strategy_signal(
                strategy_id=strategy_id, data=data, parameters=params,
                consenti_short=consenti_short,
            )
            result = run_backtest(
                data=data, signal=signal, initial_capital=initial_capital,
                fee_bps=fee_bps, slippage_bps=slippage_bps,
            )
        except Exception:
            continue
        finally:
            if on_combination is not None:
                on_combination()
        raw = float(result.summary.get(optimize_by, 0.0))
        score = -raw if ascending else raw
        attiva = int(result.summary.get("trade_count", 0)) >= MIN_TRADE_PER_SCELTA

        if attiva and not best_attiva:
            migliore = True
        elif attiva == best_attiva:
            migliore = score > best_score
        else:
            migliore = False

        if migliore:
            best_score = score
            best_params = params
            best_attiva = attiva
    return best_params


def _evaluate_on_holdout(
    *, full_data: pd.DataFrame, dev_len: int, holdout_index: pd.Index,
    strategy_id: str, params: dict[str, int | float], fee_bps: float, initial_capital: float,
    consenti_short: bool = False, slippage_bps: float = 0.0,
):
    """Valuta i parametri sul holdout, con buffer di warm-up per innescare gli indicatori."""
    spec = STRATEGY_SPECS[strategy_id]
    int_params = [p.name for p in spec.parameters if p.value_type == "int"]
    warmup = max((int(params[name]) for name in int_params if name in params), default=30)
    warmup = min(warmup * 3, dev_len)

    context = full_data.iloc[dev_len - warmup:]
    signal_ctx = build_strategy_signal(
        strategy_id=strategy_id, data=context, parameters=params, consenti_short=consenti_short,
    )
    signal_holdout = signal_ctx.reindex(holdout_index).fillna(0.0)
    holdout_data = full_data.loc[holdout_index]
    return run_backtest(
        data=holdout_data, signal=signal_holdout, initial_capital=initial_capital,
        fee_bps=fee_bps, slippage_bps=slippage_bps,
    )


def _reliability(
    *,
    dev_oos_sharpe: float,
    holdout_return_pct: float,
    holdout_excess_return_pct: float,
    holdout_sharpe: float,
    holdout_trades: int,
) -> str:
    """Traduce la tenuta su dati nuovi in un semaforo (alta/media/bassa/insufficiente).

    Il metro di paragone è il **comprare-e-tenere sullo stesso periodo**, non lo
    zero: il motore compra e basta, quindi in un periodo di prova in cui il
    mercato perde il 18% nessuna strategia potrebbe mai essere promossa se si
    pretendesse un guadagno in assoluto — e chi resta in liquidità, che quei 18
    punti li ha risparmiati, verrebbe bocciato.

    Resta però la distinzione fra "ha guadagnato" e "ha perso meno del mercato":
    la seconda non arriva mai ad affidabilità alta, perché il conto in euro
    scende comunque.
    """
    if holdout_trades == 0:
        return RELIABILITY_NONE
    if holdout_excess_return_pct < MARGINE_MINIMO_PCT:
        return RELIABILITY_LOW           # non ha battuto il comprare-e-tenere
    if holdout_return_pct <= 0 or holdout_sharpe <= 0:
        return RELIABILITY_MEDIUM        # meglio del mercato, ma comunque in perdita
    # Ha guadagnato e ha battuto il mercato: alta se ha retto il confronto con lo sviluppo.
    if dev_oos_sharpe > 0:
        calo = (dev_oos_sharpe - holdout_sharpe) / dev_oos_sharpe
        if calo <= OVERFIT_SOGLIA:
            return RELIABILITY_HIGH
        return RELIABILITY_MEDIUM
    return RELIABILITY_MEDIUM


def _verdict_note(champion: "StrategyRanking", benchmark_return_pct: float) -> str:
    """Frase di sintesi in lingua semplice sul campione."""
    r = champion.holdout_return_pct
    margine = champion.holdout_excess_return_pct
    confronto = f" (comprando e basta: {benchmark_return_pct:+.1f}%)"

    if champion.reliability == RELIABILITY_NONE:
        return "Sul periodo di prova non ha aperto operazioni: risultato non conclusivo."
    if champion.reliability == RELIABILITY_HIGH:
        return (f"Su dati nuovi mai visti ha reso il {r:+.1f}%{confronto}, "
                f"cioè {margine:+.1f} punti sul mercato, e ha retto bene: "
                "è la più solida fra quelle testate.")
    if champion.reliability == RELIABILITY_MEDIUM:
        if r <= 0:
            return (f"Su dati nuovi ha perso il {abs(r):.1f}%{confronto}: ha limitato i danni "
                    f"({margine:+.1f} punti sul mercato) ma il capitale è comunque sceso.")
        return (f"Su dati nuovi ha reso il {r:+.1f}%{confronto}, ma meno di quanto prometteva "
                "sul passato: promettente, da prendere con cautela.")
    # bassa
    return (f"La più promettente sul passato, su dati nuovi ha reso il {r:+.1f}%{confronto}: "
            "non ha battuto il semplice comprare e tenere, meglio non fidarsi.")


def _fmt(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


def to_serializable(result) -> dict:
    """Converte un risultato (dataclass) in dict JSON-safe.

    Serve sia per salvare su disco sia per renderizzare i template da un'unica
    fonte. I valori non finiti (es. -inf usato per ordinare le strategie in
    errore) diventano ``None``.
    """
    return _clean(dataclasses.asdict(result))


def _clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value
