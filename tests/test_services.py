from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trading_bot.services import (
    FloatRange,
    IntegerRange,
    STRATEGY_OPTIONS,
    StrategySearchResult,
    SweepRequest,
    list_strategy_presets,
    run_sma_sweep_request,
    run_strategy_search,
    save_strategy_preset,
)


def _synth_ohlcv(n: int = 340, seed: int = 7) -> pd.DataFrame:
    """Serie OHLCV sintetica con trend e rumore per i test di ricerca strategia."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(100.0, 150.0, n)
    noise = rng.normal(0.0, 1.2, n).cumsum() * 0.3
    closes = trend + noise
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": rng.integers(1000, 5000, n),
        },
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
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


def test_run_sma_sweep_request_supports_parabolic_sar_float_ranges(monkeypatch, tmp_path: Path) -> None:
    """Regressione: lo sweep deve funzionare anche con parametri float
    (step/max_step di Parabolic SAR) tramite FloatRange."""
    closes = [100.0, 101.0, 103.0, 102.0, 105.0, 107.0, 106.0, 110.0, 111.0, 113.0,
              112.0, 116.0, 115.0, 118.0, 117.0, 114.0, 112.0, 110.0, 108.0, 106.0]
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
        strategy="parabolic_sar",
        parameter_ranges={
            "step": FloatRange(0.01, 0.03, 0.01),
            "max_step": FloatRange(0.1, 0.3, 0.1),
        },
        fee_bps=0.0,
    )

    completed = run_sma_sweep_request(sweep_request=sweep_request, output_dir=tmp_path)

    # 3 valori di step x 3 di max_step, tutti validi (step < max_step)
    assert completed.summary["run_count"] == 9
    best = completed.summary.get("best_parameters", {})
    assert "step" in best and "max_step" in best
    assert (tmp_path / completed.sweep_dir.name / "results.csv").exists()


def test_save_strategy_preset_saves_namespaced_sweep_settings(tmp_path: Path) -> None:
    """Le impostazioni sweep vengono salvate con chiavi namespaced; i campi in
    forma globale (form pre-namespacing) vengono normalizzati."""
    saved = save_strategy_preset(
        raw={
            "preset_name": "Donchian sweep",
            "symbol": "SPY",
            "start": "2024-01-01",
            "end": "2024-03-01",
            "interval": "1d",
            "strategy": "donchian_breakout",
            "initial_capital": "10000",
            "fee_bps": "5",
            "run_mode": "sweep",
            "sort_by": "sharpe_ratio",
            "donchian_breakout__entry_period_start": "10",
            "donchian_breakout__entry_period_end": "40",
            "donchian_breakout__entry_period_step": "10",
            # exit_period in forma globale: deve essere normalizzato
            "exit_period_start": "5",
            "exit_period_end": "15",
            "exit_period_step": "5",
        },
        output_dir=tmp_path,
    )

    assert saved["run_mode"] == "sweep"
    assert saved["sweep_settings"] == {
        "sort_by": "sharpe_ratio",
        "donchian_breakout__entry_period_start": 10,
        "donchian_breakout__entry_period_end": 40,
        "donchian_breakout__entry_period_step": 10,
        "donchian_breakout__exit_period_start": 5,
        "donchian_breakout__exit_period_end": 15,
        "donchian_breakout__exit_period_step": 5,
    }


def test_run_strategy_search_ranks_and_validates_on_holdout() -> None:
    """La ricerca automatica classifica le strategie in walk-forward sullo
    sviluppo e valida il campione sul holdout intoccato."""
    data = _synth_ohlcv(n=340)

    result = run_strategy_search(
        data=data,
        symbol="TEST",
        interval="1d",
        fee_bps=0.0,
        strategy_ids=["sma_cross", "ema_cross"],
    )

    assert isinstance(result, StrategySearchResult)
    assert len(result.ranking) == 2
    # Il campione è una delle strategie testate e ha parametri di produzione.
    assert result.champion_id in {"sma_cross", "ema_cross"}
    assert result.champion_params  # non vuoto
    assert result.verdict in {"confermata", "debole", "insufficiente"}

    # La classifica è ordinata per Sharpe OOS medio (valutabili prima degli errori).
    valid = [r for r in result.ranking if r.error is None]
    sharpes = [r.avg_oos_sharpe for r in valid]
    assert sharpes == sorted(sharpes, reverse=True)

    # Lo split sviluppo/holdout copre tutte le barre e il holdout è ~20%.
    span = result.data_span
    assert span["dev_bars"] + span["holdout_bars"] == 340
    assert span["holdout_bars"] == round(340 * 0.20)

    # Il verdetto sul holdout riporta metriche misurate fuori campione.
    assert set(result.holdout) >= {"sharpe_ratio", "total_return_pct", "trade_count"}


def test_run_strategy_search_requires_enough_history() -> None:
    data = _synth_ohlcv(n=80)
    with pytest.raises(ValueError, match="validazione severa"):
        run_strategy_search(data=data, symbol="TEST", strategy_ids=["sma_cross"])


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
