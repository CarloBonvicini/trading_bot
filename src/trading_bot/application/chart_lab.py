from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from trading_bot.application.constants import STRATEGY_OPTIONS
from trading_bot.application.requests import BacktestRequest
from trading_bot.strategies import STRATEGY_SPECS

MARKET_COLUMNS = ("open", "high", "low", "close", "volume")


def build_chart_lab_state(metadata: Mapping[str, object]) -> dict[str, object]:
    active_strategy_ids = _active_strategy_ids(metadata)
    rule_logic = str(metadata.get("rule_logic", "all") or "all")
    parameters_by_strategy = _parameters_by_strategy(metadata, active_strategy_ids)
    baseline_label = str(
        metadata.get("strategy_label")
        or metadata.get("primary_strategy_label")
        or metadata.get("strategy")
        or "Sistema salvato"
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
