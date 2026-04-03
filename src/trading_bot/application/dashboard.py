from __future__ import annotations

from collections import Counter
from statistics import mean

from trading_bot.application.forms import as_form_values_from_saved_metadata


def build_dashboard_context(
    saved_items: list[dict[str, object]],
    strategies: dict[str, object],
) -> dict[str, object]:
    total_saved = len(saved_items)
    reports = [item for item in saved_items if item.get("artifact_type") == "report"]
    sweeps = [item for item in saved_items if item.get("artifact_type") == "sweep"]

    best_return = None
    best_label = "Nessun test ancora"
    deltas: list[float] = []
    symbol_counter: Counter[str] = Counter()

    for item in saved_items:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        summary = item.get("summary", {}) if isinstance(item.get("summary"), dict) else {}
        symbol = str(metadata.get("symbol") or item.get("name") or "").strip()
        if symbol:
            symbol_counter[symbol] += 1

        if item.get("artifact_type") == "sweep":
            return_value = _to_float(summary.get("best_total_return_pct"))
            delta_value = _to_float(summary.get("best_excess_return_pct"))
            label = f"{symbol} - sweep"
        else:
            return_value = _to_float(summary.get("total_return_pct"))
            delta_value = _to_float(summary.get("excess_return_pct"))
            strategy_label = str(metadata.get("strategy_label") or metadata.get("strategy") or "backtest")
            label = f"{symbol} - {strategy_label}"

        if delta_value is not None:
            deltas.append(delta_value)
        if return_value is not None and (best_return is None or return_value > best_return):
            best_return = return_value
            best_label = label

    average_delta = round(mean(deltas), 2) if deltas else 0.0
    positive_edge_count = sum(1 for delta in deltas if delta > 0)
    latest_item = saved_items[0] if saved_items else None
    latest_metadata = latest_item.get("metadata", {}) if isinstance(latest_item, dict) and isinstance(latest_item.get("metadata"), dict) else {}
    latest_label = (
        f"{latest_metadata.get('symbol') or latest_item.get('name')} - "
        f"{latest_metadata.get('strategy_label') or latest_metadata.get('strategy') or latest_item.get('artifact_type', 'report')}"
        if latest_item
        else "Lancia il primo test"
    )

    cards = [
        {
            "label": "Sessioni salvate",
            "value": str(total_saved),
            "hint": f"{len(reports)} report e {len(sweeps)} sweep",
        },
        {
            "label": "Best return",
            "value": _format_pct(best_return),
            "hint": best_label,
        },
        {
            "label": "Run sopra hold",
            "value": f"{positive_edge_count}/{total_saved}" if total_saved else "0/0",
            "hint": "strategie che battono il benchmark",
        },
        {
            "label": "Strategie disponibili",
            "value": str(len(strategies)),
            "hint": "catalogo attuale",
        },
    ]

    top_symbols = [
        {"symbol": symbol, "count": count}
        for symbol, count in symbol_counter.most_common(4)
    ]
    resume_reports = [_build_resume_report_item(item) for item in reports[:8]]

    return {
        "cards": cards,
        "total_saved": total_saved,
        "report_count": len(reports),
        "sweep_count": len(sweeps),
        "strategy_count": len(strategies),
        "latest_label": latest_label,
        "top_symbols": top_symbols,
        "best_label": best_label,
        "best_return": _format_pct(best_return),
        "average_delta": _format_pct(average_delta),
        "positive_edge_count": positive_edge_count,
        "positive_edge_display": f"{positive_edge_count}/{total_saved}" if total_saved else "0/0",
        "resume_reports": resume_reports,
    }


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _build_resume_report_item(item: dict[str, object]) -> dict[str, object]:
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    summary = item.get("summary", {}) if isinstance(item.get("summary"), dict) else {}
    active_strategy_ids = metadata.get("active_strategy_ids")
    active_rule_count = len(active_strategy_ids) if isinstance(active_strategy_ids, list) and active_strategy_ids else 1
    return {
        "report_name": str(item.get("name") or metadata.get("report_name") or "report"),
        "symbol": str(metadata.get("symbol") or item.get("name") or "").strip(),
        "strategy_label": str(metadata.get("strategy_label") or metadata.get("strategy") or "Backtest"),
        "interval": str(metadata.get("interval") or "n/a"),
        "period_label": " -> ".join(
            part
            for part in (
                str(metadata.get("start") or "").strip(),
                str(metadata.get("end") or "").strip(),
            )
            if part
        ) or "Periodo non disponibile",
        "return_display": _format_pct(_to_float(summary.get("total_return_pct"))),
        "delta_display": _format_pct(_to_float(summary.get("excess_return_pct"))),
        "active_rule_count": active_rule_count,
        "form_values": as_form_values_from_saved_metadata(metadata),
    }
