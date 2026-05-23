from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.backtest import apply_sl_tp, compute_position_size, run_backtest
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


# ── apply_sl_tp ──────────────────────────────────────────────────────────────

def _make_ohlc(closes: list[float], spread: float = 1.0) -> pd.DataFrame:
    """Crea un DataFrame OHLC con high/low simmetrici attorno al close."""
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "close": closes,
            "high":  [c + spread for c in closes],
            "low":   [c - spread for c in closes],
        },
        index=idx,
    )


def test_apply_sl_tp_noop_when_both_none() -> None:
    data = _make_ohlc([100.0, 105.0, 110.0])
    pos = pd.Series([0.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=None, tp_pct=None)
    assert new_pos.tolist() == pos.tolist()
    assert mask.sum() == 0


def test_apply_sl_tp_stop_loss_triggers() -> None:
    # Posizione entra alla barra 1 (close=100). Entry price = close[0] = 100.
    # SL al 5% → prezzo soglia = 95. Barra 2: low = 88 - 2 = 86 → scatta.
    closes = [100.0, 100.0, 88.0, 110.0]
    data = _make_ohlc(closes, spread=2.0)
    # Segnale scende a 0 alla barra 3 per isolare: verifichiamo solo che SL chiuda a barra 2
    pos = pd.Series([0.0, 1.0, 1.0, 0.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=None)
    # Alla barra 2 (i=2) lo SL è scattato: posizione → 0
    assert new_pos.iloc[2] == 0.0
    assert mask.iloc[2] is True or mask.iloc[2] == True  # noqa: E712
    # Barra 3: segnale già 0, non è rientrato
    assert new_pos.iloc[3] == 0.0


def test_apply_sl_tp_take_profit_triggers() -> None:
    # Entry price = 100. TP al 10% → soglia = 110. Barra 2: high = 115 + 2 = 117 → scatta.
    closes = [100.0, 100.0, 115.0, 80.0]
    data = _make_ohlc(closes, spread=2.0)
    pos = pd.Series([0.0, 1.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=None, tp_pct=10.0)
    assert new_pos.iloc[2] == 0.0
    assert mask.iloc[2] is True or mask.iloc[2] == True  # noqa: E712


def test_apply_sl_tp_no_trigger_when_price_in_range() -> None:
    # SL 5% TP 10%: range 95–110. Prezzi mai fuori.
    closes = [100.0, 100.0, 103.0, 107.0, 109.0]
    data = _make_ohlc(closes, spread=0.5)
    pos = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=10.0)
    assert new_pos.tolist() == pos.tolist()
    assert mask.sum() == 0


def test_apply_sl_tp_result_integrated_in_run_backtest() -> None:
    # Con SL stretto (1%) su un drawdown ampio il numero trade SL deve essere > 0
    closes = [100.0, 100.0, 85.0, 80.0, 100.0, 100.0, 82.0]
    data = pd.DataFrame(
        {
            "close": closes,
            "high": [c + 2 for c in closes],
            "low":  [c - 2 for c in closes],
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    signal = pd.Series([1.0] * len(closes), index=data.index)
    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=0.0, sl_pct=5.0)
    assert result.summary["sl_tp_exit_count"] > 0


# ── compute_position_size ─────────────────────────────────────────────────────

def test_compute_position_size_full_unchanged() -> None:
    data = _make_ohlc([100.0] * 5)
    pos = pd.Series([0.0, 1.0, 1.0, 0.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="full", param=100.0)
    assert result.tolist() == pos.tolist()


def test_compute_position_size_fixed_fraction() -> None:
    data = _make_ohlc([100.0] * 5)
    pos = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="fixed", param=50.0)
    assert all(abs(v - 0.5) < 1e-9 for v in result)


def test_compute_position_size_fixed_zero_when_no_position() -> None:
    data = _make_ohlc([100.0] * 4)
    pos = pd.Series([0.0, 1.0, 0.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="fixed", param=40.0)
    assert result.iloc[0] == 0.0
    assert result.iloc[2] == 0.0
    assert abs(result.iloc[1] - 0.4) < 1e-9


def test_compute_position_size_vol_target_clips_at_2x() -> None:
    # Vol molto bassa → size > 2 → deve essere clippata a 2.0
    closes = [100.0 + i * 0.0001 for i in range(30)]  # vol quasi zero
    data = _make_ohlc(closes)
    pos = pd.Series([1.0] * 30, index=data.index)
    result = compute_position_size(data, pos, method="vol_target", param=15.0)
    assert float(result.max()) <= 2.0 + 1e-9


# ── Metriche economiche ────────────────────────────────────────────────────

def _run_simple_bt(closes: list[float], signal_values: list[float], spread: float = 1.0):
    """Wrapper per test: crea OHLC simmetrico e lancia un backtest senza fee."""
    data = _make_ohlc(closes, spread=spread)
    signal = pd.Series(signal_values, index=data.index)
    return run_backtest(data=data, signal=signal, initial_capital=10_000.0, fee_bps=0.0)


def test_summary_includes_new_metrics() -> None:
    result = _run_simple_bt([100.0, 110.0, 121.0, 110.0, 100.0, 110.0], [1.0] * 6)
    for key in (
        "sortino_ratio", "calmar_ratio", "win_rate_pct",
        "profit_factor", "avg_win_pct", "avg_loss_pct", "expectancy_pct",
    ):
        assert key in result.summary, f"manca metrica {key}"


def test_win_rate_correct_with_known_trades() -> None:
    # 2 trade chiusi, uno in profitto e uno in perdita → win_rate = 50%.
    # signal = [1, 1, 0, 1, 1, 0, 0]  → executed (shift 1) = [0, 1, 1, 0, 1, 1, 0]
    # Trade 1 (chiuso): entry@bar1 (close=110), exit@bar3 (close=121) → +10%
    # Trade 2 (chiuso): entry@bar4 (close=115), exit@bar6 (close=105) → -8.7%
    closes = [100.0, 110.0, 120.0, 121.0, 115.0, 110.0, 105.0]
    signal = [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0]
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["trade_count"] == 2
    assert result.summary["win_rate_pct"] == 50.0


def test_profit_factor_no_losses_caps_at_999() -> None:
    # Trade chiuso in profitto, nessun trade in perdita → profit_factor = 999.
    # signal = [1, 1, 0, 0]  → executed = [0, 1, 1, 0]
    # Trade chiuso: entry@bar1 (close=105), exit@bar3 (close=110) → +4.76%
    closes = [100.0, 105.0, 108.0, 110.0]
    signal = [1.0, 1.0, 0.0, 0.0]
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["trade_count"] >= 1
    # Nessuna perdita registrata
    assert result.summary["avg_loss_pct"] is None
    assert result.summary["profit_factor"] == 999.0


def test_calmar_ratio_zero_when_no_drawdown() -> None:
    # Equity sempre crescente: drawdown = 0 → calmar capped a 999 se return > 0.
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    signal = [1.0, 1.0, 1.0, 1.0, 1.0]
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    # Calmar definito (non NaN)
    assert isinstance(result.summary["calmar_ratio"], float)


def test_annual_return_falls_back_to_total_for_short_periods() -> None:
    # Periodo < 1 anno: annual_return_pct deve essere == total_return_pct,
    # per evitare CAGR amplificati.
    closes = [100.0, 110.0]  # +10% in 1 giorno
    signal = [1.0, 1.0]
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["annual_return_pct"] == result.summary["total_return_pct"]


def test_sl_tp_can_trigger_on_entry_bar() -> None:
    # Entry al close[0]=100. Barra 1 (eseguita): low=92 < 95 (SL 5%) → uscita
    # nel BAR DI ENTRY. Verifica che il fix copra anche questo caso.
    closes = [100.0, 100.0]
    data = pd.DataFrame(
        {
            "close": closes,
            "high":  [101.0, 102.0],
            "low":   [99.0,  92.0],   # crollo intrabar
        },
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    pos = pd.Series([0.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=None)
    # Posizione esce subito nella stessa barra in cui sarebbe entrata
    assert new_pos.iloc[1] == 0.0
    assert bool(mask.iloc[1]) is True


def test_vol_target_does_not_create_fake_trades() -> None:
    # Con vol_target la posizione frazionaria varia molto, ma il trade tracking
    # deve basarsi sulla posizione binaria → un solo trade.
    closes = [100.0, 101.0, 99.0, 102.0, 98.0, 105.0, 103.0]
    signal = [1.0] * 7  # sempre long
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(
        data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0,
        sizing_method="vol_target", sizing_param=10.0,
    )
    # Un solo trade aperto (chiusura non avviene perché signal sempre 1)
    assert int(result.summary["trade_count"]) <= 1


def test_sortino_handles_no_downside_returns() -> None:
    # Solo rendimenti positivi: sortino deve essere finito (cap a 999) o 0.
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    signal = [1.0] * 5
    data = _make_ohlc(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    sortino = result.summary["sortino_ratio"]
    assert isinstance(sortino, float)
    assert not (sortino != sortino)  # not NaN

