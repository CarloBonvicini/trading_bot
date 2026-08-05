"""Walk-forward validation.

Divide il periodo storico in finestre IS/OOS sovrapposte:
per ogni finestra in-sample ottimizza i parametri tramite sweep,
poi applica i parametri migliori alla finestra out-of-sample.
Concatena i risultati OOS per produrre la curva walk-forward.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS, AUTOSETTING_GRIDS_BY_MODE
from trading_bot.backtest import SIZING_FULL, run_backtest
from trading_bot.strategies import STRATEGY_SPECS, build_strategy_signal, validate_strategy_parameters

TRADING_DAYS_PER_YEAR = 252


@dataclass
class WalkForwardWindow:
    window_index: int
    is_start: str          # data inizio IS (YYYY-MM-DD)
    is_end: str
    oos_start: str
    oos_end: str
    best_params: dict[str, int | float]
    is_sharpe: float
    oos_sharpe: float
    oos_return_pct: float
    oos_max_drawdown_pct: float
    oos_trades: int


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    oos_equity_curve: pd.DataFrame        # curva equity OOS concatenata
    wf_efficiency: float                  # OOS Sharpe medio / IS Sharpe medio
    avg_is_sharpe: float
    avg_oos_sharpe: float
    avg_oos_return_pct: float
    strategy_id: str
    optimize_by: str


def run_walk_forward(
    data: pd.DataFrame,
    strategy_id: str,
    is_days: int = 252,
    oos_days: int = 63,
    optimize_by: str = "sharpe_ratio",
    fee_bps: float = 5.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    sizing_method: str = SIZING_FULL,
    sizing_param: float = 100.0,
    initial_capital: float = 10_000.0,
    scan_mode: str = "rapida",
    on_combination: "Callable[[], None] | None" = None,
) -> WalkForwardResult:
    """Esegue la walk-forward validation su ``data`` per la strategia indicata.

    ``scan_mode`` seleziona la densità della griglia parametri (rapida → xl):
    profondità maggiori provano molte più combinazioni ma sono più lente.
    """
    spec = STRATEGY_SPECS.get(strategy_id)
    if spec is None:
        raise ValueError(f"Strategia non trovata: {strategy_id}")

    # La walk-forward richiede una griglia di parametri candidati. Non serve che
    # la strategia sia marcata ``supports_sweep`` (limite legato al form a due
    # box fast/slow): basta che esista una griglia autosetting, disponibile per
    # tutte le strategie. Così la validazione severa copre l'intero catalogo.
    param_grid = _build_param_grid(spec, scan_mode=scan_mode)
    if not param_grid:
        raise ValueError(
            f"Nessuna griglia di parametri disponibile per '{spec.label}': "
            "walk-forward non applicabile."
        )

    n = len(data)
    min_required = is_days + oos_days
    if n < min_required:
        raise ValueError(
            f"Dati insufficienti per walk-forward: servono almeno {min_required} barre, "
            f"disponibili {n}."
        )

    windows: list[WalkForwardWindow] = []
    oos_curves: list[pd.DataFrame] = []
    window_idx = 0
    start_i = 0

    while start_i + is_days + oos_days <= n:
        is_data = data.iloc[start_i : start_i + is_days]
        oos_data = data.iloc[start_i + is_days : start_i + is_days + oos_days]

        # Ottimizza parametri su IS
        best_params, is_sharpe = _optimize_params(
            data=is_data,
            strategy_id=strategy_id,
            param_grid=param_grid,
            optimize_by=optimize_by,
            fee_bps=fee_bps,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            sizing_method=sizing_method,
            sizing_param=sizing_param,
            initial_capital=initial_capital,
            on_combination=on_combination,
        )

        # Applica parametri migliori a OOS
        oos_signal = build_strategy_signal(
            strategy_id=strategy_id, data=oos_data, parameters=best_params
        )
        oos_result = run_backtest(
            data=oos_data,
            signal=oos_signal,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            sizing_method=sizing_method,
            sizing_param=sizing_param,
        )

        oos_curves.append(oos_result.equity_curve)
        is_start_str = _fmt_date(is_data.index[0])
        is_end_str = _fmt_date(is_data.index[-1])
        oos_start_str = _fmt_date(oos_data.index[0])
        oos_end_str = _fmt_date(oos_data.index[-1])

        windows.append(
            WalkForwardWindow(
                window_index=window_idx + 1,
                is_start=is_start_str,
                is_end=is_end_str,
                oos_start=oos_start_str,
                oos_end=oos_end_str,
                best_params=best_params,
                is_sharpe=round(is_sharpe, 3),
                oos_sharpe=round(float(oos_result.summary.get("sharpe_ratio", 0.0)), 3),
                oos_return_pct=round(float(oos_result.summary.get("total_return_pct", 0.0)), 2),
                oos_max_drawdown_pct=round(float(oos_result.summary.get("max_drawdown_pct", 0.0)), 2),
                oos_trades=int(oos_result.summary.get("trade_count", 0)),
            )
        )

        start_i += oos_days  # avanza di un passo OOS (walk forward)
        window_idx += 1

    if not windows:
        raise ValueError("Nessuna finestra walk-forward completata — periodo troppo breve.")

    # Concatena le equity curve OOS e ri-calcola la sequenza di equity continua
    oos_equity_curve = _stitch_oos_curves(oos_curves, initial_capital)

    avg_is = float(np.mean([w.is_sharpe for w in windows]))
    avg_oos = float(np.mean([w.oos_sharpe for w in windows]))
    wf_efficiency = (avg_oos / avg_is) if avg_is != 0 else 0.0
    avg_ret = float(np.mean([w.oos_return_pct for w in windows]))

    return WalkForwardResult(
        windows=windows,
        oos_equity_curve=oos_equity_curve,
        wf_efficiency=round(wf_efficiency, 3),
        avg_is_sharpe=round(avg_is, 3),
        avg_oos_sharpe=round(avg_oos, 3),
        avg_oos_return_pct=round(avg_ret, 2),
        strategy_id=strategy_id,
        optimize_by=optimize_by,
    )


# ── Helpers interni ──────────────────────────────────────────────────────────

def _build_param_grid(spec, scan_mode: str = "rapida") -> list[dict[str, int | float]]:
    """Costruisce la griglia di parametri da testare per la strategia.

    Usa le griglie del modulo ``autosetting`` alla densità ``scan_mode``
    (rapida/media/lunga/xl), così walk-forward e autosetting condividono la
    fonte di verità sui parametri candidati. Filtra le combinazioni che violano
    i vincoli di validazione (es. fast < slow, exit < entry).
    """
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    grid = grids.get(spec.key)
    if not grid:
        return []

    param_names = list(grid.keys())
    param_values = [grid[name] for name in param_names]

    combos: list[dict[str, int | float]] = []
    for combo in itertools.product(*param_values):
        params = dict(zip(param_names, combo))
        try:
            validate_strategy_parameters(spec.key, params)
        except ValueError:
            continue
        combos.append(params)
    return combos


def _optimize_params(
    *,
    data: pd.DataFrame,
    strategy_id: str,
    param_grid: list[dict[str, int | float]],
    optimize_by: str,
    fee_bps: float,
    sl_pct: float | None,
    tp_pct: float | None,
    sizing_method: str,
    sizing_param: float,
    initial_capital: float,
    on_combination: Callable[[], None] | None = None,
) -> tuple[dict[str, int | float], float]:
    """Trova i parametri ottimali sulla finestra IS. Restituisce (params, sharpe_IS).

    ``on_combination`` viene invocata dopo ogni combinazione provata: serve a
    contare le opzioni controllate per l'avanzamento mostrato all'utente.
    """
    best_score = float("-inf")
    best_params: dict[str, int | float] = param_grid[0]
    best_sharpe = 0.0
    ascending = optimize_by == "max_drawdown_pct"  # drawdown: vogliamo il meno negativo

    for params in param_grid:
        try:
            signal = build_strategy_signal(
                strategy_id=strategy_id, data=data, parameters=params
            )
            result = run_backtest(
                data=data,
                signal=signal,
                initial_capital=initial_capital,
                fee_bps=fee_bps,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                sizing_method=sizing_method,
                sizing_param=sizing_param,
            )
            raw_score = float(result.summary.get(optimize_by, 0.0))
            score = raw_score if not ascending else -raw_score
            if score > best_score:
                best_score = score
                best_params = params
                best_sharpe = float(result.summary.get("sharpe_ratio", 0.0))
        except Exception:
            continue
        finally:
            if on_combination is not None:
                on_combination()

    return best_params, best_sharpe


def _stitch_oos_curves(curves: list[pd.DataFrame], initial_capital: float) -> pd.DataFrame:
    """Concatena le equity curve OOS riscalando ogni segmento in continuità."""
    if not curves:
        return pd.DataFrame()

    segments = []
    running_capital = initial_capital

    for curve in curves:
        if curve.empty:
            continue
        first_eq = float(curve["equity"].iloc[0])
        if first_eq <= 0:
            segments.append(curve)
            continue
        scale = running_capital / first_eq
        scaled = curve.copy()
        for col in ("equity", "gross_equity", "benchmark_equity"):
            if col in scaled.columns:
                scaled[col] = scaled[col] * scale
        running_capital = float(scaled["equity"].iloc[-1])
        segments.append(scaled)

    if not segments:
        return pd.DataFrame()

    combined = pd.concat(segments)
    combined["drawdown"] = combined["equity"] / combined["equity"].cummax() - 1
    return combined


def _fmt_date(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]
