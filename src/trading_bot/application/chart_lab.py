from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from trading_bot.application.constants import STRATEGY_OPTIONS
from trading_bot.application.requests import BacktestRequest
from trading_bot.strategies import (
    STRATEGY_SPECS,
    adx_components,
    commodity_channel_index,
    on_balance_volume,
    relative_strength_index,
    williams_r_indicator,
)

MARKET_COLUMNS = ("open", "high", "low", "close", "volume")


def build_chart_lab_state(metadata: Mapping[str, object]) -> dict[str, object]:
    active_strategy_ids = _active_strategy_ids(metadata)
    rule_logic = str(metadata.get("rule_logic", "all") or "all")
    parameters_by_strategy = _parameters_by_strategy(metadata, active_strategy_ids)
    baseline_label = str(
        metadata.get("strategy_label")
        or metadata.get("primary_strategy_label")
        or metadata.get("strategy")
        or "Setup iniziale del report"
    )

    return {
        "active_strategy_ids": active_strategy_ids,
        "rule_logic": rule_logic,
        "parameters_by_strategy": parameters_by_strategy,
        "baseline_label": baseline_label,
    }


def build_preview_request(
    metadata: Mapping[str, object],
    raw: Mapping[str, object],
) -> BacktestRequest:
    chart_lab_state = build_chart_lab_state(metadata)
    active_strategy_ids = list(raw.get("active_strategies") or chart_lab_state["active_strategy_ids"])
    if not active_strategy_ids:
        active_strategy_ids = chart_lab_state["active_strategy_ids"]

    merged: dict[str, object] = {
        "symbol": metadata.get("symbol", ""),
        "start": metadata.get("start", ""),
        "end": metadata.get("end", ""),
        "interval": metadata.get("interval", "1d"),
        "initial_capital": metadata.get("initial_capital", 10_000),
        "fee_bps": raw.get("fee_bps", metadata.get("fee_bps", 5)),
        "rule_logic": raw.get("rule_logic", chart_lab_state["rule_logic"]),
        "active_strategies": active_strategy_ids,
        "strategy": active_strategy_ids[0],
    }

    for strategy_id, parameters in chart_lab_state["parameters_by_strategy"].items():
        for parameter_name, value in parameters.items():
            merged[f"{strategy_id}__{parameter_name}"] = value

    for key, value in raw.items():
        merged[key] = value

    return BacktestRequest.from_mapping(merged)


def load_market_data_from_saved_equity(path: Path) -> pd.DataFrame:
    equity_curve = pd.read_csv(path)
    return market_data_from_equity_curve(equity_curve)


def market_data_from_equity_curve(equity_curve: pd.DataFrame) -> pd.DataFrame:
    if "date" not in equity_curve.columns:
        raise ValueError("Il report non contiene la colonna date necessaria per il Chart Lab.")

    market_columns = [column for column in MARKET_COLUMNS if column in equity_curve.columns]
    market_data = equity_curve.loc[:, ["date", *market_columns]].copy()
    market_data["date"] = pd.to_datetime(market_data["date"], errors="coerce")
    market_data = market_data.dropna(subset=["date"]).set_index("date")
    if market_data.empty:
        raise ValueError("Il report non contiene abbastanza dati per costruire la preview sul grafico.")
    if "close" not in market_data.columns:
        raise ValueError("Nel report manca la colonna close richiesta per la preview strategica.")
    return market_data.sort_index()


def build_preview_indicator_payload(
    backtest_request: BacktestRequest,
    market_data: pd.DataFrame,
) -> list[dict[str, object]]:
    indicators: list[dict[str, object]] = []
    for rule in backtest_request.active_rules():
        indicator_payload = _indicator_payload_for_rule(
            strategy_id=rule.strategy_id,
            label=rule.label,
            parameters=rule.parameters,
            data=market_data,
        )
        if indicator_payload is not None:
            indicators.append(indicator_payload)
    return indicators


def _active_strategy_ids(metadata: Mapping[str, object]) -> list[str]:
    raw_ids = metadata.get("active_strategy_ids") or []
    active_strategy_ids = [str(strategy_id) for strategy_id in raw_ids if str(strategy_id) in STRATEGY_OPTIONS]
    if active_strategy_ids:
        return active_strategy_ids

    primary_strategy = str(metadata.get("primary_strategy") or metadata.get("strategy") or "").strip()
    if primary_strategy in STRATEGY_OPTIONS:
        return [primary_strategy]

    return ["sma_cross"]


def _parameters_by_strategy(
    metadata: Mapping[str, object],
    active_strategy_ids: list[str],
) -> dict[str, dict[str, int | float]]:
    parameters_by_strategy: dict[str, dict[str, int | float]] = {
        strategy_id: STRATEGY_SPECS[strategy_id].defaults() for strategy_id in active_strategy_ids
    }

    for rule in metadata.get("active_rules", []) or []:
        strategy_id = str(rule.get("strategy", "")).strip()
        if strategy_id not in parameters_by_strategy:
            continue
        raw_parameters = rule.get("parameters", {}) or {}
        parameters_by_strategy[strategy_id].update({str(key): value for key, value in raw_parameters.items()})

    primary_strategy = str(metadata.get("primary_strategy") or metadata.get("strategy") or "").strip()
    if primary_strategy in parameters_by_strategy:
        parameters_by_strategy[primary_strategy].update({str(key): value for key, value in (metadata.get("parameters", {}) or {}).items()})

    return parameters_by_strategy


def _indicator_payload_for_rule(
    *,
    strategy_id: str,
    label: str,
    parameters: Mapping[str, int | float],
    data: pd.DataFrame,
) -> dict[str, object] | None:
    close = data["close"].astype(float)

    if strategy_id == "sma_cross":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        fast_ma = close.rolling(window=fast, min_periods=fast).mean()
        slow_ma = close.rolling(window=slow, min_periods=slow).mean()
        return {
            "key": strategy_id,
            "label": label,
            "description": f"SMA veloce {fast} e SMA lenta {slow} sul prezzo.",
            "placement": "overlay",
            "series": [
                _indicator_series(f"{strategy_id}_fast", f"SMA {fast}", "#f59e0b", fast_ma),
                _indicator_series(f"{strategy_id}_slow", f"SMA {slow}", "#38bdf8", slow_ma),
            ],
            "thresholds": [],
        }

    if strategy_id == "ema_cross":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        return {
            "key": strategy_id,
            "label": label,
            "description": f"EMA veloce {fast} e EMA lenta {slow} sul prezzo.",
            "placement": "overlay",
            "series": [
                _indicator_series(f"{strategy_id}_fast", f"EMA {fast}", "#f97316", fast_ema),
                _indicator_series(f"{strategy_id}_slow", f"EMA {slow}", "#22c55e", slow_ema),
            ],
            "thresholds": [],
        }

    if strategy_id == "bollinger_reversion":
        period = int(parameters["period"])
        std_dev = float(parameters["std_dev"])
        basis = close.rolling(window=period, min_periods=period).mean()
        deviation = close.rolling(window=period, min_periods=period).std(ddof=0)
        upper_band = basis + (deviation * std_dev)
        lower_band = basis - (deviation * std_dev)
        return {
            "key": strategy_id,
            "label": label,
            "description": f"Bande di Bollinger: media {period}, deviazione {std_dev:g}.",
            "placement": "overlay",
            "series": [
                _indicator_series(f"{strategy_id}_basis", f"Basis {period}", "#c084fc", basis),
                _indicator_series(f"{strategy_id}_upper", "Upper band", "#60a5fa", upper_band, dash="dot"),
                _indicator_series(f"{strategy_id}_lower", "Lower band", "#60a5fa", lower_band, dash="dot"),
            ],
            "thresholds": [],
        }

    if strategy_id == "rsi_mean_reversion":
        period = int(parameters["period"])
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        rsi = relative_strength_index(close, period=period)
        return {
            "key": strategy_id,
            "label": label,
            "description": f"RSI {period} con soglie {lower:g} / {upper:g}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_rsi", f"RSI {period}", "#a78bfa", rsi),
            ],
            "thresholds": [
                _indicator_threshold("Ingresso", lower, "#ef4444"),
                _indicator_threshold("Uscita", upper, "#22c55e"),
            ],
        }

    if strategy_id == "macd_trend":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        signal_period = int(parameters["signal"])
        fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
        return {
            "key": strategy_id,
            "label": label,
            "description": f"MACD {fast}/{slow} con signal {signal_period}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_macd", "MACD", "#38bdf8", macd_line),
                _indicator_series(f"{strategy_id}_signal", "Signal", "#f59e0b", signal_line),
            ],
            "thresholds": [
                _indicator_threshold("Zero", 0.0, "#94a3b8"),
            ],
        }

    if strategy_id == "stochastic_reversion":
        _require_columns_for_indicator(data, ("high", "low"))
        k_period = int(parameters["k_period"])
        d_period = int(parameters["d_period"])
        smooth = int(parameters["smooth"])
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
        highest_high = high.rolling(window=k_period, min_periods=k_period).max()
        denominator = (highest_high - lowest_low).replace(0.0, pd.NA)
        raw_k = ((close - lowest_low) / denominator) * 100
        slow_k = raw_k.rolling(window=smooth, min_periods=smooth).mean()
        slow_d = slow_k.rolling(window=d_period, min_periods=d_period).mean()
        return {
            "key": strategy_id,
            "label": label,
            "description": f"Stochastic K {k_period}, D {d_period}, smooth {smooth}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_k", "%K", "#2dd4bf", slow_k),
                _indicator_series(f"{strategy_id}_d", "%D", "#f59e0b", slow_d),
            ],
            "thresholds": [
                _indicator_threshold("Ipervenduto", lower, "#ef4444"),
                _indicator_threshold("Ipercomprato", upper, "#22c55e"),
            ],
        }

    if strategy_id == "cci_reversion":
        period = int(parameters["period"])
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        cci = commodity_channel_index(data, period=period)
        return {
            "key": strategy_id,
            "label": label,
            "description": f"CCI {period} con soglie {lower:g} / {upper:g}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_cci", f"CCI {period}", "#38bdf8", cci),
            ],
            "thresholds": [
                _indicator_threshold("Lower", lower, "#ef4444"),
                _indicator_threshold("Upper", upper, "#22c55e"),
                _indicator_threshold("Zero", 0.0, "#94a3b8", dash="dash"),
            ],
        }

    if strategy_id == "williams_r_reversion":
        period = int(parameters["period"])
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        williams_r = williams_r_indicator(data, period=period)
        return {
            "key": strategy_id,
            "label": label,
            "description": f"Williams %R {period} con soglie {lower:g} / {upper:g}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_wr", f"Williams %R {period}", "#f472b6", williams_r),
            ],
            "thresholds": [
                _indicator_threshold("Lower", lower, "#ef4444"),
                _indicator_threshold("Upper", upper, "#22c55e"),
            ],
        }

    if strategy_id == "adx_trend":
        period = int(parameters["period"])
        threshold = float(parameters["threshold"])
        components = adx_components(data, period=period)
        return {
            "key": strategy_id,
            "label": label,
            "description": f"ADX {period} con soglia trend {threshold:g}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_adx", "ADX", "#f59e0b", components["adx"]),
                _indicator_series(f"{strategy_id}_plus_di", "+DI", "#22c55e", components["plus_di"]),
                _indicator_series(f"{strategy_id}_minus_di", "-DI", "#ef4444", components["minus_di"]),
            ],
            "thresholds": [
                _indicator_threshold("Soglia trend", threshold, "#94a3b8"),
            ],
        }

    if strategy_id == "obv_trend":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        obv = on_balance_volume(data)
        fast_ma = obv.ewm(span=fast, adjust=False, min_periods=fast).mean()
        slow_ma = obv.ewm(span=slow, adjust=False, min_periods=slow).mean()
        return {
            "key": strategy_id,
            "label": label,
            "description": f"OBV con medie {fast} / {slow}.",
            "placement": "panel",
            "series": [
                _indicator_series(f"{strategy_id}_obv", "OBV", "#a78bfa", obv),
                _indicator_series(f"{strategy_id}_fast", f"Fast {fast}", "#f59e0b", fast_ma),
                _indicator_series(f"{strategy_id}_slow", f"Slow {slow}", "#38bdf8", slow_ma),
            ],
            "thresholds": [],
        }

    return None


def _indicator_series(
    key: str,
    label: str,
    color: str,
    values: pd.Series,
    *,
    dash: str = "solid",
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "color": color,
        "dash": dash,
        "values": _series_to_json_list(values),
    }


def _indicator_threshold(
    label: str,
    value: float,
    color: str,
    *,
    dash: str = "dot",
) -> dict[str, object]:
    return {
        "label": label,
        "value": round(float(value), 6),
        "color": color,
        "dash": dash,
    }


def _series_to_json_list(series: pd.Series) -> list[float | None]:
    values: list[float | None] = []
    for value in series.tolist():
        if pd.isna(value):
            values.append(None)
        else:
            values.append(round(float(value), 6))
    return values


def _require_columns_for_indicator(data: pd.DataFrame, required_columns: tuple[str, ...]) -> None:
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(f"Dati mancanti per l'indicatore: servono le colonne {', '.join(missing)}.")
