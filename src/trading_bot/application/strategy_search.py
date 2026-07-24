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
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS, AUTOSETTING_GRIDS_BY_MODE
from trading_bot.backtest import run_backtest
from trading_bot.strategies import (
    STRATEGY_SPECS,
    build_strategy_signal,
    validate_strategy_parameters,
)
from trading_bot.walkforward import WalkForwardResult, run_walk_forward

HOLDOUT_RATIO = 0.20        # fetta finale riservata alla prova su dati nuovi
TARGET_WINDOWS = 5          # numero indicativo di finestre walk-forward sullo sviluppo
OVERFIT_SOGLIA = 0.40       # calo Sharpe holdout > 40% vs sviluppo → affidabilità ridotta
MIN_TOTAL_BARS = 150        # sotto questa soglia la validazione severa non ha senso
MIN_DEV_BARS = 100          # barre minime nello sviluppo per il walk-forward

# Semaforo di affidabilità in lingua semplice.
RELIABILITY_HIGH = "alta"
RELIABILITY_MEDIUM = "media"
RELIABILITY_LOW = "bassa"
RELIABILITY_NONE = "insufficiente"

ProgressCallback = Callable[[int, int, str], None]


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
    holdout_ratio: float = HOLDOUT_RATIO,
    target_windows: int = TARGET_WINDOWS,
    optimize_by: str = "sharpe_ratio",
    scan_mode: str = "rapida",
    strategy_ids: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> StrategySearchResult:
    """Cerca la strategia migliore per un singolo mercato con validazione severa."""
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
            "Dati insufficienti per separare sviluppo e prova su dati nuovi: "
            f"servono più barre storiche (sviluppo {dev_len}, minimo {MIN_DEV_BARS})."
        )

    dev_data = data.iloc[:dev_len]
    holdout_index = data.index[dev_len:]
    is_days, oos_days = _auto_windows(dev_len, target_windows)

    ranking: list[StrategyRanking] = []
    benchmark_return_pct = 0.0
    total = len(candidate_ids)

    for done, strategy_id in enumerate(candidate_ids, start=1):
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
                scan_mode=scan_mode,
            )
            # Parametri di produzione + prova su dati nuovi (holdout).
            params = _optimize_on_development(
                data=dev_data, strategy_id=strategy_id, fee_bps=fee_bps,
                initial_capital=initial_capital, optimize_by=optimize_by, scan_mode=scan_mode,
            )
            holdout_result = _evaluate_on_holdout(
                full_data=data, dev_len=dev_len, holdout_index=holdout_index,
                strategy_id=strategy_id, params=params, fee_bps=fee_bps,
                initial_capital=initial_capital,
            )
            hs = holdout_result.summary
            benchmark_return_pct = float(hs.get("benchmark_return_pct", benchmark_return_pct))
            reliability = _reliability(
                dev_oos_sharpe=wf.avg_oos_sharpe,
                holdout_return_pct=float(hs.get("total_return_pct", 0.0)),
                holdout_sharpe=float(hs.get("sharpe_ratio", 0.0)),
                holdout_trades=int(hs.get("trade_count", 0)),
            )
            ranking.append(
                StrategyRanking(
                    strategy_id=strategy_id, label=spec.label,
                    avg_oos_sharpe=wf.avg_oos_sharpe, avg_is_sharpe=wf.avg_is_sharpe,
                    avg_oos_return_pct=wf.avg_oos_return_pct,
                    wf_efficiency=wf.wf_efficiency, windows=len(wf.windows),
                    params=params,
                    holdout_return_pct=round(float(hs.get("total_return_pct", 0.0)), 2),
                    holdout_sharpe=round(float(hs.get("sharpe_ratio", 0.0)), 3),
                    holdout_max_drawdown_pct=round(float(hs.get("max_drawdown_pct", 0.0)), 2),
                    holdout_trades=int(hs.get("trade_count", 0)),
                    reliability=reliability,
                )
            )
        except Exception as exc:  # una strategia non valutabile non blocca la ricerca
            ranking.append(
                StrategyRanking(
                    strategy_id=strategy_id, label=spec.label,
                    avg_oos_sharpe=float("-inf"), avg_is_sharpe=0.0, avg_oos_return_pct=0.0,
                    wf_efficiency=0.0, windows=0, params={},
                    holdout_return_pct=0.0, holdout_sharpe=0.0,
                    holdout_max_drawdown_pct=0.0, holdout_trades=0,
                    reliability=RELIABILITY_NONE, error=str(exc),
                )
            )
        if progress_callback is not None:
            progress_callback(done, total, spec.label)

    # Classifica di selezione: valutabili per Sharpe OOS decrescente, errori in fondo.
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
        "scan_mode": scan_mode,
    }
    settings = {"initial_capital": float(initial_capital), "fee_bps": float(fee_bps)}

    champion = next((r for r in ranking if r.error is None and r.windows > 0), None)
    if champion is None:
        return StrategySearchResult(
            symbol=symbol, ranking=ranking, champion_id=None, champion_label=None,
            champion_params={}, holdout={}, development={},
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
        champion_params=champion.params, holdout=holdout, development=development,
        reliability=champion.reliability,
        verdict_note=_verdict_note(champion, benchmark_return_pct),
        holdout_benchmark_return_pct=round(benchmark_return_pct, 2),
        data_span=data_span, settings=settings,
    )


def _optimize_on_development(
    *, data: pd.DataFrame, strategy_id: str, fee_bps: float,
    initial_capital: float, optimize_by: str, scan_mode: str = "rapida",
) -> dict[str, int | float]:
    """Trova i parametri migliori della strategia sull'intero set di sviluppo."""
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    grid = grids[strategy_id]
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
            result = run_backtest(data=data, signal=signal, initial_capital=initial_capital, fee_bps=fee_bps)
        except Exception:
            continue
        raw = float(result.summary.get(optimize_by, 0.0))
        score = -raw if ascending else raw
        if score > best_score:
            best_score = score
            best_params = params
    return best_params


def _evaluate_on_holdout(
    *, full_data: pd.DataFrame, dev_len: int, holdout_index: pd.Index,
    strategy_id: str, params: dict[str, int | float], fee_bps: float, initial_capital: float,
):
    """Valuta i parametri sul holdout, con buffer di warm-up per innescare gli indicatori."""
    spec = STRATEGY_SPECS[strategy_id]
    int_params = [p.name for p in spec.parameters if p.value_type == "int"]
    warmup = max((int(params[name]) for name in int_params if name in params), default=30)
    warmup = min(warmup * 3, dev_len)

    context = full_data.iloc[dev_len - warmup:]
    signal_ctx = build_strategy_signal(strategy_id=strategy_id, data=context, parameters=params)
    signal_holdout = signal_ctx.reindex(holdout_index).fillna(0.0)
    holdout_data = full_data.loc[holdout_index]
    return run_backtest(data=holdout_data, signal=signal_holdout, initial_capital=initial_capital, fee_bps=fee_bps)


def _reliability(
    *, dev_oos_sharpe: float, holdout_return_pct: float, holdout_sharpe: float, holdout_trades: int
) -> str:
    """Traduce la tenuta su dati nuovi in un semaforo (alta/media/bassa/insufficiente)."""
    if holdout_trades == 0:
        return RELIABILITY_NONE
    if holdout_return_pct <= 0 or holdout_sharpe <= 0:
        return RELIABILITY_LOW
    # Ha guadagnato su dati nuovi: alta se ha retto anche il confronto con lo sviluppo.
    if dev_oos_sharpe > 0:
        calo = (dev_oos_sharpe - holdout_sharpe) / dev_oos_sharpe
        if calo <= OVERFIT_SOGLIA:
            return RELIABILITY_HIGH
        return RELIABILITY_MEDIUM
    return RELIABILITY_MEDIUM


def _verdict_note(champion: "StrategyRanking", benchmark_return_pct: float) -> str:
    """Frase di sintesi in lingua semplice sul campione."""
    r = champion.holdout_return_pct
    if champion.reliability == RELIABILITY_HIGH:
        return (f"Su dati nuovi mai visti ha guadagnato il {r:.1f}% e ha retto bene: "
                "è la più solida fra quelle testate.")
    if champion.reliability == RELIABILITY_MEDIUM:
        return (f"Su dati nuovi ha guadagnato il {r:.1f}%, ma meno di quanto prometteva sul passato: "
                "promettente ma da prendere con cautela.")
    if champion.reliability == RELIABILITY_NONE:
        return "Sul periodo di prova non ha aperto operazioni: risultato non conclusivo."
    # bassa
    confronto = ""
    if benchmark_return_pct:
        confronto = f" (comprando e basta: {benchmark_return_pct:+.1f}%)"
    return (f"La più promettente sul passato, su dati nuovi ha reso il {r:.1f}%{confronto}: "
            "non ha retto la prova, meglio non fidarsi.")


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
