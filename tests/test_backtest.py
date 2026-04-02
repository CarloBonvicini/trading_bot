from __future__ import annotations

import pandas as pd

from trading_bot.backtest import run_backtest
from trading_bot.strategies import rsi_mean_reversion, sma_crossover


def test_sma_crossover_returns_binary_positions() -> None:
    data = pd.DataFrame(
        {"close": [100, 101, 102, 103, 104, 105]},
        index=pd.date_range("2024-01-01", periods=6, freq="D"),
    )

    signal = sma_crossover(data, fast=2, slow=3)

    assert set(signal.dropna().unique()).issubset({0.0, 1.0})


def test_rsi_mean_reversion_returns_binary_positions() -> None:
    data = pd.DataFrame(
        {"close": [100, 90, 88, 89, 91, 94, 97, 99]},
        index=pd.date_range("2024-01-01", periods=8, freq="D"),
    )

    signal = rsi_mean_reversion(data, period=2, lower=35, upper=55)

    assert set(signal.unique()).issubset({0.0, 1.0})


def test_backtest_shifts_signal_to_avoid_lookahead() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 110.0, 121.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    signal = pd.Series([1.0, 1.0, 1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=0.0)

    assert result.equity_curve["position"].tolist() == [0.0, 1.0, 1.0]
    assert round(result.summary["final_equity"], 2) == 1210.0
    assert round(result.summary["gross_final_equity"], 2) == 1210.0
    assert round(result.summary["benchmark_final_equity"], 2) == 1210.0
    assert round(result.summary["excess_return_pct"], 2) == 0.0
    assert round(result.summary["fees_paid"], 2) == 0.0
    assert round(result.summary["fee_drag_equity"], 2) == 0.0


def test_backtest_tracks_fees_paid() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 110.0, 100.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    signal = pd.Series([1.0, 0.0, 0.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=100.0)

    assert result.summary["fees_paid"] > 0
    assert result.summary["gross_final_equity"] > result.summary["final_equity"]
    assert round(result.summary["fee_drag_equity"], 2) >= round(result.summary["fees_paid"], 2)
