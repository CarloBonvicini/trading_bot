from __future__ import annotations

from datetime import datetime

from trading_bot.application.constants import INTERVAL_OPTIONS, STRATEGY_OPTIONS
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
        "active_strategies": ["sma_cross"],
        "rule_logic": "all",
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
            "active_strategies": list(backtest_request.active_strategy_ids),
            "rule_logic": backtest_request.rule_logic,
            "initial_capital": backtest_request.initial_capital,
            "fee_bps": backtest_request.fee_bps,
        }
    )
    for rule in backtest_request.active_rules():
        for parameter_name, parameter_value in rule.parameters.items():
            values[strategy_field_name(rule.strategy_id, parameter_name)] = parameter_value
    return values


def as_form_values_from_saved_metadata(metadata: dict[str, object]) -> dict[str, object]:
    values = default_form_values()

    strategy_id = str(
        metadata.get("primary_strategy")
        or metadata.get("strategy")
        or "sma_cross"
    ).strip()
    if strategy_id not in STRATEGY_OPTIONS:
        strategy_id = "sma_cross"

    active_strategy_ids = metadata.get("active_strategy_ids")
    if isinstance(active_strategy_ids, list):
        normalized_active_ids = [
            str(strategy_key).strip()
            for strategy_key in active_strategy_ids
            if str(strategy_key).strip() in STRATEGY_OPTIONS
        ]
    else:
        normalized_active_ids = []

    if not normalized_active_ids:
        normalized_active_ids = [strategy_id]

    values.update(
        {
            "preset_name": "",
            "run_mode": "single",
            "symbol": str(metadata.get("symbol") or values["symbol"]).strip(),
            "start": str(metadata.get("start") or values["start"]).strip(),
            "end": str(metadata.get("end") or values["end"]).strip(),
            "interval": str(metadata.get("interval") or values["interval"]).strip(),
            "strategy": strategy_id,
            "active_strategies": normalized_active_ids,
            "rule_logic": str(metadata.get("rule_logic") or values["rule_logic"]).strip(),
            "initial_capital": metadata.get("initial_capital", values["initial_capital"]),
            "fee_bps": metadata.get("fee_bps", values["fee_bps"]),
        }
    )

    active_rules = metadata.get("active_rules")
    if isinstance(active_rules, list) and active_rules:
        for rule in active_rules:
            if not isinstance(rule, dict):
                continue
            strategy_key = str(rule.get("strategy") or "").strip()
            if strategy_key not in STRATEGY_OPTIONS:
                continue
            parameters = rule.get("parameters")
            if not isinstance(parameters, dict):
                continue
            for parameter_name, parameter_value in parameters.items():
                values[strategy_field_name(strategy_key, str(parameter_name))] = parameter_value
        return values

    parameters = metadata.get("parameters")
    if isinstance(parameters, dict):
        for parameter_name, parameter_value in parameters.items():
            values[strategy_field_name(strategy_id, str(parameter_name))] = parameter_value
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
