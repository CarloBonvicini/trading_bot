from __future__ import annotations

from datetime import datetime

from trading_bot.application.constants import COSTI_DEFAULT, INTERVAL_OPTIONS, STRATEGY_OPTIONS
from trading_bot.application.requests import BacktestRequest, sweep_parameter_names
from trading_bot.data import INTRADAY_LOOKBACK_DAYS
from trading_bot.strategies import STRATEGY_SPECS, default_parameter_values, strategy_field_name


def _sweep_range_defaults() -> dict[str, object]:
    """Default dei campi range sweep (``<strategia>__<parametro>_start/_end/_step``).

    Copre ogni strategia ``supports_sweep`` con un range centrato sul default
    dello spec (metà → doppio, passo ≈ un sesto dell'ampiezza). Il namespace
    strategia evita collisioni tra strategie che condividono i nomi parametro
    (es. fast/slow di sma_cross, ema_cross e obv_trend).
    """
    defaults: dict[str, object] = {}
    for spec in STRATEGY_SPECS.values():
        if not spec.supports_sweep:
            continue
        parameter_map = spec.parameter_map()
        for name in sweep_parameter_names(spec.key):
            parameter = parameter_map[name]
            if parameter.value_type == "int":
                start = int(parameter.default) // 2
                if parameter.minimum is not None:
                    start = max(int(parameter.minimum), start)
                end = int(parameter.default) * 2
                step = max(1, (end - start) // 6)
            else:
                start = float(parameter.default) / 2
                if parameter.minimum is not None:
                    start = max(float(parameter.minimum), start)
                end = float(parameter.default) * 2
                step = round((end - start) / 6, 4) or float(parameter.step or 1.0)
            defaults[f"{spec.key}__{name}_start"] = start
            defaults[f"{spec.key}__{name}_end"] = end
            defaults[f"{spec.key}__{name}_step"] = step
    return defaults


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
        "slippage_bps": 0.0,
        "costi_operazione": COSTI_DEFAULT,
        "sort_by": "total_return_pct",
        "sl_pct": "",
        "tp_pct": "",
        "sizing_method": "full",
        "sizing_param": 100.0,
        "consenti_short": False,
        "flat_at_close": False,
        "wf_is_days": 252,
        "wf_oos_days": 63,
        "wf_optimize_by": "sharpe_ratio",
        **_sweep_range_defaults(),
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
            "slippage_bps": backtest_request.slippage_bps,
            "consenti_short": backtest_request.consenti_short,
            "flat_at_close": backtest_request.flat_at_close,
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
            "slippage_bps": metadata.get("slippage_bps", values["slippage_bps"]),
            # I report salvati prima del supporto al ribasso non hanno la
            # chiave: erano tutti solo al rialzo.
            "consenti_short": bool(metadata.get("consenti_short", False)),
            "flat_at_close": bool(metadata.get("flat_at_close", False)),
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
