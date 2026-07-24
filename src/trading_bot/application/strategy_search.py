"""Ricerca automatica della strategia migliore con validazione severa.

Data il solo contesto (mercato, periodo, capitale, commissioni), questo modulo
sceglie la strategia più promettente fra tutte quelle disponibili, con la
validazione più rigorosa che il codebase permette, in tre strati:

1. **Holdout finale intoccato** — l'ultima fetta di dati (default 20%) viene
   messa da parte e non partecipa *in alcun modo* alla selezione. Serve solo
   per il verdetto finale sul campione, così il numero che leggi è calcolato su
   dati che il processo di scelta non ha mai visto (difesa dal problema del
   confronto multiplo: scegliere "la migliore fra 15" è di per sé una fonte di
   overfitting).

2. **Walk-forward sullo sviluppo** — sul restante 80% ogni strategia viene
   valutata in walk-forward (finestre IS che ottimizzano i parametri, finestre
   OOS che li testano). Si classifica per Sharpe out-of-sample medio: è la
   performance *non* gonfiata dall'ottimizzazione.

3. **Verdetto sul holdout** — il campione viene riottimizzato sull'intero
   sviluppo e valutato una sola volta sul holdout. Se lì regge, la scelta è
   confermata; se crolla, viene segnalato il possibile overfitting.

Note sul realismo: il backtest usa dati di mercato reali (yfinance), applica le
commissioni in basis point e lo shift di una barra che impedisce il lookahead.
Non modella lo slippage: le metriche sono al netto delle sole commissioni.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS
from trading_bot.backtest import run_backtest
from trading_bot.strategies import (
    STRATEGY_SPECS,
    build_strategy_signal,
    validate_strategy_parameters,
)
from trading_bot.walkforward import WalkForwardResult, run_walk_forward

HOLDOUT_RATIO = 0.20        # fetta finale riservata al verdetto (intoccata)
TARGET_WINDOWS = 5          # numero indicativo di finestre walk-forward sullo sviluppo
OVERFIT_SOGLIA = 0.40       # calo Sharpe holdout > 40% vs sviluppo → verdetto debole
MIN_TOTAL_BARS = 150        # sotto questa soglia la validazione severa non ha senso
MIN_DEV_BARS = 100          # barre minime nello sviluppo per il walk-forward


@dataclass
class StrategyRanking:
    """Riga di classifica: performance walk-forward di una strategia sullo sviluppo."""

    strategy_id: str
    label: str
    avg_oos_sharpe: float
    avg_oos_return_pct: float
    wf_efficiency: float
    windows: int
    error: str | None = None  # motivo se la strategia non è stata valutabile


@dataclass
class StrategySearchResult:
    ranking: list[StrategyRanking]
    champion_id: str | None
    champion_label: str | None
    champion_params: dict[str, int | float]
    holdout: dict[str, object]
    development: dict[str, object]
    verdict: str            # "confermata" | "debole" | "insufficiente"
    verdict_note: str
    data_span: dict[str, object]
    settings: dict[str, object]


def _auto_windows(dev_len: int, target_windows: int = TARGET_WINDOWS) -> tuple[int, int]:
    """Dimensiona le finestre IS/OOS per ottenere ~``target_windows`` finestre.

    Il rapporto IS≈4×OOS con OOS≈dev_len/(target+3) mantiene il numero di
    finestre pressoché costante al variare della quantità di dati, così il costo
    computazionale non esplode sulle storie molto lunghe.
    """
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
    holdout_ratio: float = HOLDOUT_RATIO,
    target_windows: int = TARGET_WINDOWS,
    optimize_by: str = "sharpe_ratio",
    strategy_ids: list[str] | None = None,
) -> StrategySearchResult:
    """Cerca la strategia migliore per il contesto dato con validazione severa.

    ``strategy_ids`` limita l'insieme testato (default: tutte quelle con griglia).
    """
    candidate_ids = strategy_ids or list(AUTOSETTING_GRIDS.keys())

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
            "Dati insufficienti per separare sviluppo e holdout: "
            f"servono più barre storiche (sviluppo {dev_len}, minimo {MIN_DEV_BARS})."
        )

    dev_data = data.iloc[:dev_len]
    holdout_index = data.index[dev_len:]
    is_days, oos_days = _auto_windows(dev_len, target_windows)

    # --- Strato 2: walk-forward per ciascuna strategia sullo sviluppo ---
    ranking: list[StrategyRanking] = []
    wf_by_id: dict[str, WalkForwardResult] = {}

    for strategy_id in candidate_ids:
        spec = STRATEGY_SPECS.get(strategy_id)
        if spec is None:
            continue
        try:
            wf = run_walk_forward(
                data=dev_data,
                strategy_id=strategy_id,
                is_days=is_days,
                oos_days=oos_days,
                optimize_by=optimize_by,
                fee_bps=fee_bps,
                initial_capital=initial_capital,
            )
        except Exception as exc:  # una strategia non valutabile non blocca la ricerca
            ranking.append(
                StrategyRanking(
                    strategy_id=strategy_id,
                    label=spec.label,
                    avg_oos_sharpe=float("-inf"),
                    avg_oos_return_pct=0.0,
                    wf_efficiency=0.0,
                    windows=0,
                    error=str(exc),
                )
            )
            continue

        wf_by_id[strategy_id] = wf
        ranking.append(
            StrategyRanking(
                strategy_id=strategy_id,
                label=spec.label,
                avg_oos_sharpe=wf.avg_oos_sharpe,
                avg_oos_return_pct=wf.avg_oos_return_pct,
                wf_efficiency=wf.wf_efficiency,
                windows=len(wf.windows),
            )
        )

    # Classifica: prima le valutabili per Sharpe OOS decrescente, gli errori in fondo.
    ranking.sort(key=lambda r: (r.error is None, r.avg_oos_sharpe), reverse=True)

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
    }
    settings = {"initial_capital": float(initial_capital), "fee_bps": float(fee_bps)}

    # Campione: prima riga valutabile con almeno una finestra completata.
    champion = next(
        (r for r in ranking if r.error is None and r.windows > 0), None
    )
    if champion is None:
        return StrategySearchResult(
            ranking=ranking,
            champion_id=None,
            champion_label=None,
            champion_params={},
            holdout={},
            development={},
            verdict="insufficiente",
            verdict_note=(
                "Nessuna strategia ha completato la walk-forward su questo periodo. "
                "Prova con più storia o un timeframe diverso."
            ),
            data_span=data_span,
            settings=settings,
        )

    champion_wf = wf_by_id[champion.strategy_id]

    # --- Strato 3: riottimizza il campione sull'intero sviluppo, valuta sul holdout ---
    champion_params = _optimize_on_development(
        data=dev_data,
        strategy_id=champion.strategy_id,
        fee_bps=fee_bps,
        initial_capital=initial_capital,
        optimize_by=optimize_by,
    )

    holdout_result = _evaluate_on_holdout(
        full_data=data,
        dev_len=dev_len,
        holdout_index=holdout_index,
        strategy_id=champion.strategy_id,
        params=champion_params,
        fee_bps=fee_bps,
        initial_capital=initial_capital,
    )
    holdout_summary = holdout_result.summary

    verdict, verdict_note = _giudizio(
        dev_oos_sharpe=champion.avg_oos_sharpe,
        holdout_summary=holdout_summary,
    )

    development = {
        "avg_oos_sharpe": champion_wf.avg_oos_sharpe,
        "avg_is_sharpe": champion_wf.avg_is_sharpe,
        "avg_oos_return_pct": champion_wf.avg_oos_return_pct,
        "wf_efficiency": champion_wf.wf_efficiency,
        "windows": len(champion_wf.windows),
    }
    holdout = {
        "sharpe_ratio": round(float(holdout_summary.get("sharpe_ratio", 0.0)), 3),
        "total_return_pct": round(float(holdout_summary.get("total_return_pct", 0.0)), 2),
        "benchmark_return_pct": round(float(holdout_summary.get("benchmark_return_pct", 0.0)), 2),
        "excess_return_pct": round(float(holdout_summary.get("excess_return_pct", 0.0)), 2),
        "max_drawdown_pct": round(float(holdout_summary.get("max_drawdown_pct", 0.0)), 2),
        "trade_count": int(holdout_summary.get("trade_count", 0)),
    }

    return StrategySearchResult(
        ranking=ranking,
        champion_id=champion.strategy_id,
        champion_label=champion.label,
        champion_params=champion_params,
        holdout=holdout,
        development=development,
        verdict=verdict,
        verdict_note=verdict_note,
        data_span=data_span,
        settings=settings,
    )


def _optimize_on_development(
    *,
    data: pd.DataFrame,
    strategy_id: str,
    fee_bps: float,
    initial_capital: float,
    optimize_by: str,
) -> dict[str, int | float]:
    """Trova i parametri migliori del campione sull'intero set di sviluppo.

    Sono i parametri "di produzione" che verrebbero poi applicati: valutarli sul
    holdout dà la stima onesta di ciò che ci si può aspettare.
    """
    grid = AUTOSETTING_GRIDS[strategy_id]
    names = list(grid.keys())
    values = [grid[name] for name in names]
    ascending = optimize_by == "max_drawdown_pct"

    best_params: dict[str, int | float] = dict(zip(names, (v[0] for v in values)))
    best_score = float("-inf")

    for combo in itertools.product(*values):
        params = dict(zip(names, combo))
        try:
            validate_strategy_parameters(strategy_id, params)
            signal = build_strategy_signal(strategy_id=strategy_id, data=data, parameters=params)
            result = run_backtest(
                data=data,
                signal=signal,
                initial_capital=initial_capital,
                fee_bps=fee_bps,
            )
        except Exception:
            continue
        raw = float(result.summary.get(optimize_by, 0.0))
        score = -raw if ascending else raw
        if score > best_score:
            best_score = score
            best_params = params

    return best_params


def _evaluate_on_holdout(
    *,
    full_data: pd.DataFrame,
    dev_len: int,
    holdout_index: pd.Index,
    strategy_id: str,
    params: dict[str, int | float],
    fee_bps: float,
    initial_capital: float,
) -> "object":
    """Valuta i parametri del campione sul holdout, con buffer di warm-up.

    Gli indicatori vengono innescati usando la coda dello sviluppo come contesto,
    ma il backtest misura solo le barre del holdout: nessun dato di selezione
    entra nel risultato finale.
    """
    spec = STRATEGY_SPECS[strategy_id]
    int_params = [p.name for p in spec.parameters if p.value_type == "int"]
    warmup = max((int(params[name]) for name in int_params if name in params), default=30)
    warmup = min(warmup * 3, dev_len)  # buffer generoso per indicatori a lunga memoria

    context = full_data.iloc[dev_len - warmup:]
    signal_ctx = build_strategy_signal(strategy_id=strategy_id, data=context, parameters=params)
    signal_holdout = signal_ctx.reindex(holdout_index).fillna(0.0)
    holdout_data = full_data.loc[holdout_index]
    return run_backtest(
        data=holdout_data,
        signal=signal_holdout,
        initial_capital=initial_capital,
        fee_bps=fee_bps,
    )


def _giudizio(*, dev_oos_sharpe: float, holdout_summary: dict) -> tuple[str, str]:
    """Confronta lo Sharpe walk-forward (sviluppo) con quello sul holdout."""
    trades = int(holdout_summary.get("trade_count", 0))
    holdout_sharpe = float(holdout_summary.get("sharpe_ratio", 0.0))

    if trades == 0:
        return (
            "insufficiente",
            "Sul periodo di holdout la strategia non apre operazioni: dati non conclusivi.",
        )
    if holdout_sharpe <= 0:
        return (
            "debole",
            f"Fuori campione lo Sharpe è {holdout_sharpe:.2f}: la strategia non regge "
            "su dati mai visti nella selezione.",
        )
    if dev_oos_sharpe > 0:
        calo = (dev_oos_sharpe - holdout_sharpe) / dev_oos_sharpe
        if calo > OVERFIT_SOGLIA:
            return (
                "debole",
                f"Lo Sharpe cala del {calo * 100:.0f}% sul holdout "
                f"({dev_oos_sharpe:.2f} → {holdout_sharpe:.2f}): possibile overfitting.",
            )
    return (
        "confermata",
        f"Lo Sharpe regge sul holdout ({holdout_sharpe:.2f}), dati mai usati nella "
        "selezione: la scelta è robusta.",
    )


def _fmt(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]
