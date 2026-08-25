"""Ricerca multi-mercato: la stessa validazione severa, ma su più simboli insieme.

La domanda a cui risponde: *esiste una strategia che regge su dati nuovi non su
un solo mercato per fortuna, ma su tanti mercati diversi?* È il test più severo
di robustezza — ed è quello che può durare a lungo (molti mercati × profondità
alta), quindi gira in background.

Per ogni simbolo esegue ``run_strategy_search`` (holdout + walk-forward), poi
aggrega per strategia: quante volte è risultata affidabile su dati nuovi, e con
quale resa media. Vince la strategia più costantemente solida fra i mercati.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS
from trading_bot.application.portafoglio import costruisci_portafoglio
from trading_bot.application.prova_del_caso import punti_in_euro
from trading_bot.application.strategy_search import (
    MARGINE_MINIMO_PCT,
    RELIABILITY_HIGH,
    Candidato,
    StrategyRanking,
    chiave_candidato,
    costruisci_candidati,
    estimate_search_combinations,
    run_strategy_search,
)
from trading_bot.data import download_price_data
from trading_bot.strategies import STRATEGY_SPECS

N_STRATEGIES = len(AUTOSETTING_GRIDS)
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class MarketOutcome:
    """Come è andata su un mercato la strategia mostrata (di norma il campione
    complessivo; il campione locale del mercato solo se non c'è un vincitore
    complessivo)."""

    symbol: str
    champion_label: str | None
    reliability: str
    holdout_return_pct: float
    benchmark_return_pct: float
    bars: int
    error: str | None = None
    # Esito della prova del caso su questo mercato e che tipo di vittoria è.
    prova_del_caso: dict | None = None
    tipo_vittoria: str = ""


@dataclass
class StrategyAcrossMarkets:
    strategy_id: str
    label: str
    markets_tested: int
    markets_reliable: int       # affidabilità "alta" su dati nuovi
    # Mercati in cui ha fatto meglio del comprare-e-tenere: per un motore solo
    # long è il confronto onesto (in un mercato che scende, "in positivo" non lo
    # sarebbe nessuno).
    markets_beat_market: int
    avg_holdout_return_pct: float
    avg_holdout_excess_pct: float
    avg_dev_sharpe: float
    # Verso in cui ha corso: la stessa strategia compare due volte quando il
    # ribasso è attivo, e le due righe non vanno mescolate.
    consenti_short: bool = False


@dataclass
class MultiMarketSearchResult:
    symbols: list[str]
    interval: str
    scan_mode: str
    markets: list[MarketOutcome] = field(default_factory=list)
    strategy_scores: list[StrategyAcrossMarkets] = field(default_factory=list)
    overall_champion_id: str | None = None
    overall_champion_label: str | None = None
    overall_champion_consenti_short: bool = False
    # Come sarebbe andata dividendo i soldi fra gli stessi mercati e stando
    # fermi: e' il metro di paragone vero, piu' del singolo titolo.
    portafoglio: dict | None = None
    verdict_note: str = ""
    settings: dict = field(default_factory=dict)


def run_multi_market_search(
    symbols: list[str],
    interval: str = "1d",
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    scan_mode: str = "rapida",
    start: str = "",
    end: str = "",
    strategy_ids: list[str] | None = None,
    consenti_short: bool = False,
    flat_at_close: bool = False,
    prove_del_caso: int = 0,
    download_data: Callable[..., pd.DataFrame] = download_price_data,
    progress_callback: ProgressCallback | None = None,
    max_workers: int | None = None,
    checkpoint: dict | None = None,
    on_row: Callable[[str, dict, float, int], None] | None = None,
) -> MultiMarketSearchResult:
    """Esegue la ricerca su più mercati e aggrega la robustezza per strategia.

    ``checkpoint`` contiene il lavoro già svolto in una ricerca interrotta
    (``{"markets": {simbolo: {"rows": {...}, "benchmark_return_pct": ..., "bars": ...}}}``):
    i candidati già valutati non vengono ricalcolati e i mercati completati non
    vengono nemmeno riscaricati. ``on_row`` riceve ogni candidato completato per
    salvarlo su disco.
    """
    clean_symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not clean_symbols:
        raise ValueError("Indica almeno un simbolo da analizzare.")

    n_strategies = len(strategy_ids) if strategy_ids else N_STRATEGIES
    # Avanzamento in combinazioni provate: il totale dei mercati non ancora
    # scaricati viene stimato da quello corrente (stesso periodo e timeframe,
    # quindi numero di barre pressoché identico).
    combinazioni_concluse = 0
    # Info per mercato, tenute finché non conosciamo il campione complessivo.
    market_info: dict[str, dict] = {}
    # Chiusure dei mercati scaricati: servono a costruire il portafoglio noioso
    # con cui confrontare il risultato.
    chiusure: dict[str, pd.Series] = {}
    # strategy_id -> liste di risultati per mercato (resa su dati nuovi, sharpe sviluppo, affidabile)
    per_strategy: dict[str, dict[str, list]] = {}

    attesi = [chiave_candidato(c) for c in costruisci_candidati(strategy_ids, consenti_short)]

    for index, symbol in enumerate(clean_symbols):
        mercati_rimanenti = len(clean_symbols) - index - 1
        salvate = (checkpoint or {}).get("markets", {}).get(symbol, {})
        righe_salvate: dict[str, dict] = salvate.get("rows", {})

        # Mercato già completato prima dell'interruzione: si riusa tutto, senza
        # nemmeno riscaricare i dati.
        if righe_salvate and all(chiave in righe_salvate for chiave in attesi):
            ranking = [StrategyRanking(**riga) for riga in righe_salvate.values()]
            ranking.sort(
                key=lambda r: (r.error is None, r.dev_oos_trades > 0, r.avg_oos_sharpe),
                reverse=True,
            )
            market_info[symbol] = _info_da_righe(ranking, salvate)
            combinazioni_concluse += estimate_search_combinations(
                int(salvate.get("bars", 0)), scan_mode=scan_mode,
                strategy_ids=strategy_ids, consenti_short=consenti_short,
            )
            if progress_callback is not None:
                progress_callback(combinazioni_concluse, combinazioni_concluse,
                                  f"{symbol} · già completato")
            _aggrega(per_strategy, ranking)
            continue

        barre_correnti = [int(salvate.get("bars", 0))]

        def _riga_completata(riga, benchmark: float, _sym=symbol) -> None:
            if on_row is not None:
                on_row(_sym, dataclasses.asdict(riga), benchmark, barre_correnti[0])

        def inner_progress(
            done: int, market_total: int, label: str,
            _sym=symbol, _base=combinazioni_concluse, _rimanenti=mercati_rimanenti,
        ) -> None:
            if progress_callback is not None:
                stima_totale = _base + market_total * (_rimanenti + 1)
                progress_callback(_base + done, stima_totale, f"{_sym} · {label}")

        try:
            data = download_data(symbol=symbol, start=start, end=end, interval=interval)
            barre_correnti[0] = len(data)
            if "close" in data.columns:
                chiusure[symbol] = data["close"].astype(float)
            result = run_strategy_search(
                data=data, symbol=symbol, interval=interval,
                initial_capital=initial_capital, fee_bps=fee_bps,
                slippage_bps=slippage_bps, scan_mode=scan_mode, strategy_ids=strategy_ids, progress_callback=inner_progress,
                consenti_short=consenti_short, flat_at_close=flat_at_close,
                prove_del_caso=prove_del_caso, max_workers=max_workers,
                precomputed_rows=righe_salvate or None,
                benchmark_return_pct=float(salvate.get("benchmark_return_pct", 0.0)),
                on_row=_riga_completata,
            )
        except Exception as exc:
            market_info[symbol] = {"error": str(exc)}
            if progress_callback is not None:
                progress_callback(combinazioni_concluse, combinazioni_concluse, f"{symbol} · saltato")
            continue

        combinazioni_concluse += estimate_search_combinations(
            len(data), scan_mode=scan_mode, strategy_ids=strategy_ids,
            consenti_short=consenti_short,
        )

        by_strategy = {
            Candidato(row.strategy_id, row.consenti_short): {
                "return": row.holdout_return_pct, "reliability": row.reliability,
            }
            for row in result.ranking if row.error is None
        }
        market_info[symbol] = {
            "error": None,
            "prova_del_caso": result.prova_del_caso,
            "tipo_vittoria": result.tipo_vittoria,
            "bars": int(result.data_span.get("bars", 0)),
            "benchmark": result.holdout_benchmark_return_pct,
            "local_return": float(result.holdout.get("total_return_pct", 0.0)) if result.holdout else 0.0,
            "local_reliability": result.reliability,
            "local_champion_label": result.champion_label,
            "by_strategy": by_strategy,
        }

        _aggrega(per_strategy, result.ranking)

    # Il confronto ha senso solo se le due parti pagano lo stesso prezzo per
    # operare: un portafoglio che ribilancia gratis e' un avversario finto.
    portafoglio = costruisci_portafoglio(
        chiusure, fee_bps=fee_bps, slippage_bps=slippage_bps,
    )
    strategy_scores = _aggregate(per_strategy)
    # Quante ricerche hanno riconosciuto una vittoria vera, cioe' una che ha
    # superato la prova del caso e quella dei vicini. Se sono zero non si
    # incorona nessuno: il semaforo di affidabilita' da solo non basta piu'.
    vittorie_riconosciute = sum(
        1 for info in market_info.values() if info.get("tipo_vittoria")
    )
    overall = strategy_scores[0] if strategy_scores else None
    campione = None
    if overall and (overall.markets_reliable > 0 or overall.markets_beat_market > 0):
        campione = Candidato(overall.strategy_id, overall.consenti_short)
    overall_id = campione.strategy_id if campione else None
    overall_label = overall.label if campione else None

    # Ogni scheda mostra come è andato il campione complessivo su quel mercato
    # (coerente con l'intestazione); se non c'è un campione complessivo, ripiega
    # sul campione locale del singolo mercato.
    markets = [_market_outcome(symbol, market_info.get(symbol, {"error": "nessun dato"}),
                               campione, overall_label)
               for symbol in clean_symbols]

    return MultiMarketSearchResult(
        symbols=clean_symbols,
        interval=interval,
        scan_mode=scan_mode,
        markets=markets,
        strategy_scores=strategy_scores,
        overall_champion_id=overall_id,
        overall_champion_label=overall_label,
        overall_champion_consenti_short=bool(campione.consenti_short) if campione else False,
        portafoglio=dataclasses.asdict(portafoglio) if portafoglio else None,
        verdict_note=_overall_note(
            overall, len(clean_symbols), portafoglio, vittorie_riconosciute,
            capitale=initial_capital,
        ),
        settings={
            "initial_capital": float(initial_capital),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "flat_at_close": bool(flat_at_close),
            "prove_del_caso": int(prove_del_caso),
        },
    )


def _aggrega(per_strategy: dict, righe: list) -> None:
    """Somma le righe di un mercato nell'aggregato per candidato."""
    for row in righe:
        if row.error is not None:
            continue
        bucket = per_strategy.setdefault(
            Candidato(row.strategy_id, row.consenti_short),
            {"returns": [], "excess": [], "dev_sharpe": [], "reliable": 0, "beat": 0,
             "label": row.label},
        )
        bucket["returns"].append(row.holdout_return_pct)
        bucket["excess"].append(row.holdout_excess_return_pct)
        bucket["dev_sharpe"].append(row.avg_oos_sharpe)
        if row.reliability == RELIABILITY_HIGH:
            bucket["reliable"] += 1
        if row.holdout_excess_return_pct >= MARGINE_MINIMO_PCT:
            bucket["beat"] += 1


def _info_da_righe(ranking: list, salvate: dict) -> dict:
    """Ricostruisce la scheda di un mercato dalle righe salvate su disco."""
    campione = next((r for r in ranking if r.error is None and r.windows > 0), None)
    return {
        "error": None,
        "prova_del_caso": salvate.get("prova_del_caso"),
        "tipo_vittoria": salvate.get("tipo_vittoria", ""),
        "bars": int(salvate.get("bars", 0)),
        "benchmark": float(salvate.get("benchmark_return_pct", 0.0)),
        "local_return": float(campione.holdout_return_pct) if campione else 0.0,
        "local_reliability": campione.reliability if campione else "insufficiente",
        "local_champion_label": campione.label if campione else None,
        "by_strategy": {
            Candidato(r.strategy_id, r.consenti_short): {
                "return": r.holdout_return_pct, "reliability": r.reliability,
            }
            for r in ranking if r.error is None
        },
    }


def _market_outcome(symbol: str, info: dict, campione, overall_label: str | None) -> MarketOutcome:
    """Scheda di un mercato: mostra il campione complessivo su quel mercato,
    oppure il campione locale se non c'è un vincitore complessivo."""
    if info.get("error"):
        return MarketOutcome(symbol=symbol, champion_label=None, reliability="insufficiente",
                             holdout_return_pct=0.0, benchmark_return_pct=0.0, bars=0, error=info["error"])
    by_strategy = info.get("by_strategy", {})
    if campione is not None and campione in by_strategy:
        entry = by_strategy[campione]
        return MarketOutcome(
            symbol=symbol, champion_label=overall_label,
            reliability=entry["reliability"], holdout_return_pct=entry["return"],
            benchmark_return_pct=info["benchmark"], bars=info["bars"],
            prova_del_caso=info.get("prova_del_caso"),
            tipo_vittoria=info.get("tipo_vittoria", ""),
        )
    return MarketOutcome(
        symbol=symbol, champion_label=info.get("local_champion_label"),
        reliability=info.get("local_reliability", "insufficiente"),
        holdout_return_pct=info.get("local_return", 0.0),
        benchmark_return_pct=info.get("benchmark", 0.0), bars=info.get("bars", 0),
        prova_del_caso=info.get("prova_del_caso"),
        tipo_vittoria=info.get("tipo_vittoria", ""),
    )


def _aggregate(per_strategy: dict[str, dict[str, list]]) -> list[StrategyAcrossMarkets]:
    scores: list[StrategyAcrossMarkets] = []
    for candidato, bucket in per_strategy.items():
        returns = bucket["returns"]
        excess = bucket["excess"]
        dev = bucket["dev_sharpe"]
        tested = len(returns)
        scores.append(
            StrategyAcrossMarkets(
                strategy_id=candidato.strategy_id,
                label=bucket.get("label") or STRATEGY_SPECS[candidato.strategy_id].label,
                consenti_short=candidato.consenti_short,
                markets_tested=tested,
                markets_reliable=bucket["reliable"],
                markets_beat_market=bucket["beat"],
                avg_holdout_return_pct=round(sum(returns) / tested, 2) if tested else 0.0,
                avg_holdout_excess_pct=round(sum(excess) / tested, 2) if tested else 0.0,
                avg_dev_sharpe=round(sum(dev) / tested, 3) if tested else 0.0,
            )
        )
    # La più robusta: prima chi è affidabile su più mercati, poi chi ha battuto
    # il comprare-e-tenere su più mercati, poi il margine medio più alto.
    scores.sort(
        key=lambda s: (s.markets_reliable, s.markets_beat_market, s.avg_holdout_excess_pct),
        reverse=True,
    )
    return scores


def _in_euro(punti: float, capitale: float | None) -> str:
    """La traduzione in euro, incastonata dopo un testo già iniziato."""
    tradotto = punti_in_euro(punti, capitale)
    return f", {tradotto}" if tradotto else ""


def _mercati(n: int) -> str:
    return "1 mercato" if n == 1 else f"{n} mercati"


# Sopra questa soglia i mercati salgono e scendono negli stessi giorni: dividere
# fra loro non riduce quasi niente, e chi guarda il confronto deve saperlo.
INSIEME_TROPPO = 0.85


def _nota_su_quanto_si_muovono_insieme(insieme: float) -> str:
    """Avvisa quando i mercati scelti sono, di fatto, lo stesso mercato.

    Venti titoli che si muovono negli stessi giorni sono un titolo solo comprato
    venti volte: il confronto col portafoglio diviso resta valido, ma chi lo
    legge crederebbe di avere una protezione che non ha.
    """
    if insieme < INSIEME_TROPPO:
        return ""
    return (
        " Attenzione però: questi mercati salgono e scendono quasi sempre negli stessi "
        "giorni, quindi dividere i soldi fra loro non ripara granché — nel giorno "
        "brutto vanno giù tutti insieme."
    )


def _overall_note(
    overall: "StrategyAcrossMarkets | None", n_markets: int, portafoglio=None,
    vittorie_riconosciute: int = 0, capitale: float | None = None,
) -> str:
    confronto = ""
    if portafoglio is not None:
        confronto = (
            f" Per confronto, dividendo gli stessi soldi fra tutti i mercati in parti uguali "
            f"e stando fermi si sarebbe ottenuto il {portafoglio.rendimento_fermo_pct:+.1f}% "
            f"(ribilanciando ogni mese, commissioni comprese: "
            f"{portafoglio.rendimento_ribilanciato_pct:+.1f}%), "
            f"con un calo peggiore del {abs(portafoglio.calo_peggiore_fermo_pct):.0f}%."
            + _nota_su_quanto_si_muovono_insieme(portafoglio.quanto_si_muovono_insieme)
        )
    # Nessuna ricerca ha riconosciuto una vittoria: qualunque cosa sia arrivata
    # prima in classifica, non e' un risultato di cui fidarsi. Dirlo chiaro vale
    # piu' di incoronare il meno peggio.
    if overall is not None and vittorie_riconosciute == 0:
        return (
            "Nessuna strategia ha superato i controlli su nessuno dei mercati provati: "
            f"{overall.label} e' arrivata prima in classifica, ma il suo vantaggio non "
            "sopravvive al confronto con la fortuna o si dissolve spostando di un passo i "
            "parametri. Non c'e' niente da cui fidarsi." + confronto
        )

    if overall is None:
        return "Nessun mercato ha prodotto risultati validi. Prova con altri simboli o più storia."
    if overall.markets_reliable > 0:
        return (
            f"{overall.label} è la più solida: affidabile su dati nuovi in "
            f"{_mercati(overall.markets_reliable)} su {n_markets} testati, "
            f"con una resa media su dati nuovi del {overall.avg_holdout_return_pct:+.1f}% "
            f"({overall.avg_holdout_excess_pct:+.1f} punti rispetto a comprare e tenere"
            + _in_euro(overall.avg_holdout_excess_pct, capitale) + ")."
         + confronto
        )
    if overall.markets_beat_market > 0:
        return (
            f"Nessuna strategia è risultata pienamente affidabile su più mercati. "
            f"La meno debole è {overall.label}: ha fatto meglio del comprare e tenere in "
            f"{_mercati(overall.markets_beat_market)} su {n_markets}." + confronto
        )
    return (
        "Nessuna strategia ha battuto il semplice comprare e tenere su dati nuovi in questi "
        "mercati: è il segno che batterli stabilmente è molto difficile." + confronto
    )
