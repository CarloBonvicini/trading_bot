from __future__ import annotations

"""Compatibility facade for the application layer.

This module keeps the public imports stable while the real implementation lives
in smaller, purpose-built modules under ``trading_bot.application``.
"""

from pathlib import Path

from trading_bot.application.constants import (
    DEFAULT_REPORTS_DIR,
    INTERVAL_OPTIONS,
    RULE_LOGIC_OPTIONS,
    RUN_MODE_OPTIONS,
    STRATEGY_OPTIONS,
    SWEEP_SORT_OPTIONS,
)
from trading_bot.application.execution import (
    CompletedBacktest,
    CompletedSweep,
    run_backtest_request as _run_backtest_request,
    run_sma_sweep_request as _run_sma_sweep_request,
)
from trading_bot.application.forms import as_form_values, default_form_values, interval_helper_texts
from trading_bot.application.presets import list_strategy_presets, preset_storage_path, save_strategy_preset
from trading_bot.application.requests import BacktestRequest, IntegerRange, SweepRequest
from trading_bot.data import download_price_data

__all__ = [
    "BacktestRequest",
    "CompletedBacktest",
    "CompletedSweep",
    "DEFAULT_REPORTS_DIR",
    "INTERVAL_OPTIONS",
    "IntegerRange",
    "RULE_LOGIC_OPTIONS",
    "RUN_MODE_OPTIONS",
    "STRATEGY_OPTIONS",
    "SWEEP_SORT_OPTIONS",
    "SweepRequest",
    "as_form_values",
    "default_form_values",
    "download_price_data",
    "interval_helper_texts",
    "list_strategy_presets",
    "preset_storage_path",
    "run_backtest_request",
    "run_sma_sweep_request",
    "save_strategy_preset",
]


def run_backtest_request(
    backtest_request: BacktestRequest,
    output_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> CompletedBacktest:
    return _run_backtest_request(
        backtest_request=backtest_request,
        output_dir=output_dir,
        download_data=download_price_data,
    )


def run_sma_sweep_request(
    sweep_request: SweepRequest,
    output_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> CompletedSweep:
    return _run_sma_sweep_request(
        sweep_request=sweep_request,
        output_dir=output_dir,
        download_data=download_price_data,
    )
