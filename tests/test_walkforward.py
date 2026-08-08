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


def test_run_walk_forward_supports_non_sweep_strategy() -> None:
    """La walk-forward gira su qualsiasi strategia con griglia autosetting,
    non solo su quelle marcate supports_sweep (es. RSI mean reversion)."""
    data = _synth_data(n=500)
    wf = run_walk_forward(
        data=data,
        strategy_id="rsi_mean_reversion",
        is_days=200,
        oos_days=50,
        fee_bps=0.0,
    )
    assert len(wf.windows) >= 1
    for window in wf.windows:
        assert "period" in window.best_params


def _forza_griglia(monkeypatch, griglia: dict[str, list]) -> None:
    """Sostituisce la griglia autosetting di sma_cross con una scelta a mano,
    così il test controlla esattamente quali combinazioni vengono provate."""
    monkeypatch.setattr(
        "trading_bot.walkforward.AUTOSETTING_GRIDS_BY_MODE",
        {"rapida": {"sma_cross": griglia}},
    )


def test_walk_forward_scalda_gli_indicatori_sulla_storia_precedente(monkeypatch) -> None:
    """Regressione: una media a 200 barre su una finestra da 60 partiva a freddo
    e restava piatta a zero, facendo sembrare inattiva la combinazione."""
    _forza_griglia(monkeypatch, {"fast": [50], "slow": [200]})
    data = _synth_data(n=700)

    wf = run_walk_forward(
        data=data, strategy_id="sma_cross", is_days=300, oos_days=60, fee_bps=0.0,
    )

    assert len(wf.windows) >= 1
    # Con il warm-up la strategia è investita nelle finestre di collaudo: senza,
    # ogni finestra avrebbe zero operazioni e Sharpe esattamente 0.
    assert sum(w.oos_trades for w in wf.windows) > 0
    assert any(w.oos_sharpe != 0.0 for w in wf.windows)


def test_walk_forward_non_sceglie_parametri_che_non_operano(monkeypatch) -> None:
    """Una combinazione inerte totalizza 0 secco e batterebbe ogni combinazione
    in perdita: deve perdere comunque contro chi ha davvero operato."""
    # slow=900 su 500 barre non produce mai un segnale: è la combinazione inerte.
    _forza_griglia(monkeypatch, {"fast": [5], "slow": [10, 900]})
    data = _synth_data(n=500, seed=5)

    wf = run_walk_forward(
        data=data, strategy_id="sma_cross", is_days=250, oos_days=60, fee_bps=50.0,
    )

    assert all(w.best_params["slow"] == 10 for w in wf.windows)


def test_run_walk_forward_raises_for_unknown_strategy() -> None:
    data = _synth_data(n=500)
    with pytest.raises(ValueError, match="non trovata"):
        run_walk_forward(
            data=data,
            strategy_id="strategia_inesistente",
            is_days=200,
            oos_days=50,
            fee_bps=0.0,
        )
