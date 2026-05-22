from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.backtest import run_backtest
from trading_bot.strategies import build_combined_signal, donchian_breakout, rsi_mean_reversion, sma_crossover


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


def _donchian_data(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "close": closes,
            "high":  highs  if highs  is not None else [c + 1.0 for c in closes],
            "low":   lows   if lows   is not None else [c - 1.0 for c in closes],
        },
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


def test_donchian_breakout_returns_binary_positions() -> None:
    closes = [100.0, 99.0, 101.0, 100.0, 98.0, 102.0, 105.0, 107.0, 106.0, 108.0]
    data = _donchian_data(closes)
    signal = donchian_breakout(data, entry_period=5, exit_period=3)
    assert set(signal.unique()).issubset({0.0, 1.0})


def test_donchian_breakout_entry_fires_on_new_high() -> None:
    # Prime 3 barre: high fermo a 101. Quarta barra: high = 110 -> breakout
    closes = [100.0, 100.0, 100.0, 110.0, 110.0]
    highs  = [101.0, 101.0, 101.0, 110.0, 110.0]
    lows   = [ 99.0,  99.0,  99.0,  99.0,  99.0]
    data = _donchian_data(closes, highs, lows)
    signal = donchian_breakout(data, entry_period=3, exit_period=2)
    # Alla barra 3 (indice 3): close=110 >= max high(101,101,110)=110 -> entrata
    assert signal.iloc[3] == 1.0


def test_donchian_breakout_exit_fires_on_new_low() -> None:
    # Prezzi range-bound -> breakout a rialzo (ingresso) -> crollo sotto il canale (uscita)
    # entry_period=3, exit_period=2
    closes = [100.0, 101.0, 100.0, 101.0, 101.0, 121.0, 120.0, 73.0]
    highs  = [101.0, 102.0, 101.0, 102.0, 102.0, 121.0,  81.0, 74.0]
    lows   = [ 99.0,  99.0,  99.0,  99.0,  99.0,  99.0,  80.0, 73.0]
    data = _donchian_data(closes, highs, lows)
    signal = donchian_breakout(data, entry_period=3, exit_period=2)
    # Ingresso alla barra 5: close 121 >= max high(102,102,121)=121
    assert signal.iloc[5] == 1.0
    # Uscita alla barra 7: close 73 <= min low(80,73)=73
    assert signal.iloc[7] == 0.0


def test_donchian_breakout_raises_if_exit_period_not_smaller() -> None:
    data = _donchian_data([100.0] * 10)
    with pytest.raises(ValueError, match="exit period"):
        donchian_breakout(data, entry_period=10, exit_period=10)


def test_donchian_breakout_raises_without_high_low_columns() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 101.0, 102.0, 103.0]},
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )
    with pytest.raises(ValueError, match="colonne"):
        donchian_breakout(data, entry_period=3, exit_period=2)


def test_build_combined_signal_supports_and_logic() -> None:
    data = pd.DataFrame(
        {"close": [100, 99, 98, 99, 101, 103, 102, 104, 105, 107]},
        index=pd.date_range("2024-01-01", periods=10, freq="D"),
    )

    signal = build_combined_signal(
        data=data,
        rules=[
            ("sma_cross", {"fast": 2, "slow": 4}),
            ("ema_cross", {"fast": 2, "slow": 5}),
        ],
        combination_mode="all",
    )

    assert set(signal.dropna().unique()).issubset({0.0, 1.0})
    assert float(signal.max()) == 1.0
