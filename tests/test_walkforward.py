"""Test per la walk-forward validation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.walkforward import _build_param_grid, run_walk_forward
from trading_bot.strategies import STRATEGY_SPECS


def _synth_data(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """Serie sintetica con trend e rumore: abbastanza barre per IS+OOS multipli."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(100.0, 140.0, n)
    noise = rng.normal(0.0, 1.5, n).cumsum() * 0.3
    closes = trend + noise
    return pd.DataFrame(
        {
            "close": closes,
            "high":  closes + 1.0,
            "low":   closes - 1.0,
            "open":  closes,
            "volume": rng.integers(1000, 5000, n),
        },
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )


def test_build_param_grid_returns_combinations_for_sma() -> None:
    grid = _build_param_grid(STRATEGY_SPECS["sma_cross"])
    assert len(grid) > 0
    # Tutte le combinazioni devono soddisfare fast < slow
    for params in grid:
        assert params["fast"] < params["slow"]


def test_build_param_grid_returns_combinations_for_donchian() -> None:
    """Regressione: prima il param grid usava p.sweep_range inesistente."""
    grid = _build_param_grid(STRATEGY_SPECS["donchian_breakout"])
    assert len(grid) > 0
    for params in grid:
        assert params["exit_period"] < params["entry_period"]


def test_run_walk_forward_completes_at_least_one_window() -> None:
    data = _synth_data(n=500)
    wf = run_walk_forward(
        data=data,
        strategy_id="sma_cross",
        is_days=252,
        oos_days=63,
        optimize_by="sharpe_ratio",
        fee_bps=0.0,
    )
    assert len(wf.windows) >= 1
    for window in wf.windows:
        assert isinstance(window.best_params, dict)
        assert "fast" in window.best_params and "slow" in window.best_params


def test_run_walk_forward_raises_if_data_too_short() -> None:
    data = _synth_data(n=100)
    with pytest.raises(ValueError, match="Dati insufficienti"):
        run_walk_forward(
            data=data,
            strategy_id="sma_cross",
            is_days=252,
            oos_days=63,
            fee_bps=0.0,
        )


def test_run_walk_forward_rejects_non_sweep_strategy() -> None:
    data = _synth_data(n=500)
    with pytest.raises(ValueError, match="sweep"):
        run_walk_forward(
            data=data,
            strategy_id="rsi_mean_reversion",  # supports_sweep=False
            is_days=200,
            oos_days=50,
            fee_bps=0.0,
        )
