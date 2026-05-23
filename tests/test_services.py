from __future__ import annotations

from pathlib import Path

import pandas as pd

from trading_bot.services import (
    IntegerRange,
    STRATEGY_OPTIONS,
    SweepRequest,
    list_strategy_presets,
    run_sma_sweep_request,
    save_strategy_preset,
)


def test_run_sma_sweep_request_generates_all_valid_combinations(monkeypatch, tmp_path: Path) -> None:
    data = pd.DataFrame(
        {
            "close": [100, 102, 101, 103, 105, 104, 108, 110, 109, 113, 116, 118],
        },
        index=pd.date_range("2024-01-01", periods=12, freq="D"),
    )
    monkeypatch.setattr("trading_bot.application.execution.download_price_data", lambda **_: data)

    sweep_request = SweepRequest(
        symbol="SPY",
        data_symbol="SPY",
        start="2024-01-01",
        end="2024-01-12",
        interval="1d",
        parameter_ranges={
            "fast": IntegerRange(2, 4, 1),
            "slow": IntegerRange(4, 6, 1),
        },
        fee_bps=0.0,
    )

    completed = run_sma_sweep_request(sweep_request=sweep_request, output_dir=tmp_path)

    assert completed.summary["run_count"] == 8
    assert completed.summary["invalid_combinations"] == 1
    assert completed.results["rank"].tolist() == list(range(1, 9))
    assert (tmp_path / completed.sweep_dir.name / "results.csv").exists()
    assert (tmp_path / completed.sweep_dir.name / "best_summary.json").exists()


def test_run_sma_sweep_request_supports_ema_crossover(monkeypatch, tmp_path: Path) -> None:
    data = pd.DataFrame(
        {
            "close": [100, 101, 103, 102, 105, 107, 106, 110, 111, 113, 112, 116],
        },
        index=pd.date_range("2024-01-01", periods=12, freq="D"),
    )
    monkeypatch.setattr("trading_bot.application.execution.download_price_data", lambda **_: data)

    sweep_request = SweepRequest(
        symbol="SPY",
        data_symbol="SPY",
        start="2024-01-01",
        end="2024-01-12",
        interval="1d",
        strategy="ema_cross",
        parameter_ranges={
            "fast": IntegerRange(2, 4, 1),
            "slow": IntegerRange(5, 7, 1),
        },
        fee_bps=0.0,
    )

    completed = run_sma_sweep_request(sweep_request=sweep_request, output_dir=tmp_path)

    assert completed.request.strategy == "ema_cross"
    assert completed.summary["run_count"] == 9
    assert completed.summary["best_fast"] >= 2
    assert completed.summary["best_slow"] >= 5


def test_run_sma_sweep_request_supports_donchian_breakout(monkeypatch, tmp_path: Path) -> None:
    """Regressione: lo sweep deve funzionare anche su strategie con parametri
    diversi da fast/slow (es. entry_period/exit_period per Donchian)."""
    # Serie con qualche breakout per evitare zero trade
    closes = [100.0, 99.0, 101.0, 100.0, 98.0, 102.0, 105.0, 107.0, 106.0, 108.0,
              110.0, 109.0, 107.0, 105.0, 103.0, 101.0, 100.0, 99.0, 98.0, 96.0]
    data = pd.DataFrame(
        {
            "close": closes,
            "high":  [c + 1.0 for c in closes],
            "low":   [c - 1.0 for c in closes],
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    monkeypatch.setattr("trading_bot.application.execution.download_price_data", lambda **_: data)

    sweep_request = SweepRequest(
        symbol="SPY",
        data_symbol="SPY",
        start="2024-01-01",
        end="2024-01-20",
        interval="1d",
        strategy="donchian_breakout",
        parameter_ranges={
            # Per Donchian, i primi due parametri interi sono entry_period e exit_period
            "entry_period": IntegerRange(5, 10, 5),
            "exit_period":  IntegerRange(2, 4, 2),
        },
        fee_bps=0.0,
    )

    completed = run_sma_sweep_request(sweep_request=sweep_request, output_dir=tmp_path)

    assert completed.summary["run_count"] >= 1
    # I parametri ottimali devono includere entry_period e exit_period
    best = completed.summary.get("best_parameters", {})
    assert "entry_period" in best and "exit_period" in best
    # File generati
    assert (tmp_path / completed.sweep_dir.name / "results.csv").exists()


def test_strategy_catalog_and_presets_cover_extended_setup(tmp_path: Path) -> None:
    assert len(STRATEGY_OPTIONS) >= 10
    assert "macd_trend" in STRATEGY_OPTIONS
    assert "obv_trend" in STRATEGY_OPTIONS
    assert STRATEGY_OPTIONS["ema_cross"]["supports_sweep"] is True

    saved = save_strategy_preset(
        raw={
            "preset_name": "MACD test",
            "symbol": "SPY",
            "start": "2024-01-01",
            "end": "2024-03-01",
            "interval": "1d",
            "strategy": "macd_trend",
            "initial_capital": "10000",
            "fee_bps": "5",
            "macd_trend__fast": "12",
            "macd_trend__slow": "26",
            "macd_trend__signal": "9",
        },
        output_dir=tmp_path,
    )

    presets = list_strategy_presets(tmp_path)

    assert saved["name"] == "MACD test"
    assert len(presets) == 1
    assert presets[0]["strategy"] == "macd_trend"
    assert presets[0]["parameters"] == {"fast": 12, "slow": 26, "signal": 9}


def test_save_strategy_preset_supports_combined_rules(tmp_path: Path) -> None:
    saved = save_strategy_preset(
        raw={
            "preset_name": "Trend + RSI filter",
            "symbol": "SPY",
            "start": "2024-01-01",
            "end": "2024-03-01",
            "interval": "1d",
            "active_strategies": ["ema_cross", "rsi_mean_reversion"],
            "rule_logic": "all",
            "initial_capital": "10000",
            "fee_bps": "5",
            "ema_cross__fast": "12",
            "ema_cross__slow": "26",
            "rsi_mean_reversion__period": "14",
            "rsi_mean_reversion__lower": "30",
            "rsi_mean_reversion__upper": "55",
        },
        output_dir=tmp_path,
    )

    assert saved["is_composite"] is True
    assert saved["active_strategy_ids"] == ["ema_cross", "rsi_mean_reversion"]
    assert saved["parameters_by_strategy"]["ema_cross"] == {"fast": 12, "slow": 26}
    assert saved["parameters_by_strategy"]["rsi_mean_reversion"] == {"period": 14, "lower": 30.0, "upper": 55.0}
