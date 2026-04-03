from __future__ import annotations

from datetime import datetime

from trading_bot.application.constants import INTERVAL_OPTIONS
from trading_bot.application.requests import BacktestRequest
from trading_bot.data import INTRADAY_LOOKBACK_DAYS
from trading_bot.strategies import default_parameter_values, strategy_field_name


def default_form_values() -> dict[str, object]:
    current_year = datetime.now().year
    return {
        "preset_name": "",
        "run_mode": "single",
        "symbol": "SPY",
        "start": f"{current_year - 6}-01-01",
        "end": f"{current_year - 1}-12-31",
        "interval": "1d",
        "strategy": "sma_cross",
        "initial_capital": 10_000.0,
        "fee_bps": 5.0,
        "sort_by": "total_return_pct",
        "fast_start": 10,
        "fast_end": 40,
        "fast_step": 10,
        "slow_start": 80,
        "slow_end": 200,
        "slow_step": 20,
        **default_parameter_values(),
    }


def as_form_values(backtest_request: BacktestRequest | None = None) -> dict[str, object]:
    values = default_form_values()
    if backtest_request is None:
        return values

    values.update(
        {
            "symbol": backtest_request.symbol,
            "start": backtest_request.start,
            "end": backtest_request.end,
            "interval": backtest_request.interval,
            "strategy": backtest_request.strategy,
            "initial_capital": backtest_request.initial_capital,
            "fee_bps": backtest_request.fee_bps,
        }
    )
    for parameter_name, parameter_value in backtest_request.strategy_parameters().items():
        values[strategy_field_name(backtest_request.strategy, parameter_name)] = parameter_value
    return values


def interval_helper_texts() -> dict[str, str]:
    hints: dict[str, str] = {}
    for interval in INTERVAL_OPTIONS:
        lookback_days = INTRADAY_LOOKBACK_DAYS.get(interval)
        if lookback_days is None:
            hints[interval] = "Storico ampio disponibile."
        else:
            hints[interval] = f"Yahoo limita questo timeframe agli ultimi {lookback_days} giorni."
    return hints
