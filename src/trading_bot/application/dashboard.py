from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
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
    best_sharpe = None
    best_sharpe_label = "Nessuna sessione"
    best_drawdown = None
    best_drawdown_label = "Nessuna sessione"
    best_win_rate = None
    best_win_rate_label = "Nessuna sessione"
    best_win_rate_trades = 0
    deltas: list[float] = []
    symbol_counter: Counter[str] = Counter()

    for item in saved_items:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        summary = item.get("summary", {}) if isinstance(item.get("summary"), dict) else {}
        symbol = str(metadata.get("symbol") or item.get("name") or "").strip()
        item_label = _build_dashboard_item_label(item)
        if symbol:
            symbol_counter[symbol] += 1

        if item.get("artifact_type") == "sweep":
            return_value = _to_float(summary.get("best_total_return_pct"))
            delta_value = _to_float(summary.get("best_excess_return_pct"))
            sharpe_value = _to_float(summary.get("best_sharpe_ratio"))
            drawdown_value = _to_float(summary.get("best_max_drawdown_pct"))
        else:
            return_value = _to_float(summary.get("total_return_pct"))
            delta_value = _to_float(summary.get("excess_return_pct"))
            sharpe_value = _to_float(summary.get("sharpe_ratio"))
            drawdown_value = _to_float(summary.get("max_drawdown_pct"))

        win_rate_payload = _read_win_rate(item)
        win_rate_value = win_rate_payload["win_rate"] if win_rate_payload else None

        if delta_value is not None:
            deltas.append(delta_value)
        if return_value is not None and (best_return is None or return_value > best_return):
            best_return = return_value
            best_label = item_label
        if sharpe_value is not None and (best_sharpe is None or sharpe_value > best_sharpe):
            best_sharpe = sharpe_value
            best_sharpe_label = item_label
        if drawdown_value is not None and (best_drawdown is None or drawdown_value > best_drawdown):
            best_drawdown = drawdown_value
            best_drawdown_label = item_label
        if win_rate_value is not None and (best_win_rate is None or win_rate_value > best_win_rate):
            best_win_rate = win_rate_value
            best_win_rate_label = item_label
            best_win_rate_trades = int(win_rate_payload["trade_count"])

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
            "label": "Miglior win ratio",
            "value": _format_plain_pct(best_win_rate),
            "hint": (
                f"{best_win_rate_label} · {best_win_rate_trades} trade"
                if best_win_rate is not None
                else "Servono trade chiusi per calcolarlo"
            ),
        },
        {
            "label": "Best Sharpe",
            "value": _format_ratio(best_sharpe),
            "hint": best_sharpe_label,
        },
    ]

    top_symbols = [
        {"symbol": symbol, "count": count}
        for symbol, count in symbol_counter.most_common(4)
    ]
    resume_reports = [_build_resume_report_item(item) for item in reports[:8]]
    lead_symbol = top_symbols[0] if top_symbols else None
    highlights = [
        {
            "label": "Delta medio vs hold",
            "value": _format_pct(average_delta),
            "hint": "Media sulle sessioni con benchmark disponibile",
        },
        {
            "label": "Run sopra hold",
            "value": f"{positive_edge_count}/{total_saved}" if total_saved else "0/0",
            "hint": "Quante sessioni battono il benchmark",
        },
        {
            "label": "Drawdown migliore",
            "value": _format_pct(best_drawdown),
            "hint": best_drawdown_label,
        },
        {
            "label": "Simbolo piu' usato",
            "value": lead_symbol["symbol"] if lead_symbol else "n/a",
            "hint": f"{lead_symbol['count']} sessioni" if lead_symbol else "Nessuna sessione ancora",
        },
    ]

    return {
        "cards": cards,
        "highlights": highlights,
        "total_saved": total_saved,
        "report_count": len(reports),
        "sweep_count": len(sweeps),
        "strategy_count": len(strategies),
        "latest_label": latest_label,
        "top_symbols": top_symbols,
        "best_label": best_label,
        "best_return": _format_pct(best_return),
        "best_win_rate": _format_plain_pct(best_win_rate),
        "best_win_rate_label": best_win_rate_label,
        "best_win_rate_trades": best_win_rate_trades,
        "best_sharpe": _format_ratio(best_sharpe),
        "best_sharpe_label": best_sharpe_label,
        "best_drawdown": _format_pct(best_drawdown),
        "best_drawdown_label": best_drawdown_label,
        "average_delta": _format_pct(average_delta),
        "positive_edge_count": positive_edge_count,
        "positive_edge_display": f"{positive_edge_count}/{total_saved}" if total_saved else "0/0",
        "lead_symbol": lead_symbol,
        "resume_reports": resume_reports,
    }


def build_session_catalog(saved_items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_build_session_item(item) for item in saved_items]


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _format_plain_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _build_dashboard_item_label(item: dict[str, object]) -> str:
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    symbol = str(metadata.get("symbol") or item.get("name") or "").strip() or "Sessione"
    if item.get("artifact_type") == "sweep":
        strategy_label = str(metadata.get("strategy_label") or metadata.get("strategy") or "Sweep").strip()
        return f"{symbol} - Sweep {strategy_label}"

    strategy_label = str(metadata.get("strategy_label") or metadata.get("strategy") or "Backtest").strip()
    return f"{symbol} - {strategy_label}"


def _read_win_rate(item: dict[str, object]) -> dict[str, float | int] | None:
    item_path = item.get("path")
    if not item_path:
        return None

    trades_file = Path(item_path) / ("best_trades.csv" if item.get("artifact_type") == "sweep" else "trades.csv")
    if not trades_file.exists():
        return None

    try:
        with trades_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            total = 0
            wins = 0
            for row in reader:
                pnl_value = _to_float(row.get("pnl_pct"))
                if pnl_value is None:
                    continue
                total += 1
                if pnl_value > 0:
                    wins += 1
    except OSError:
        return None

    if total == 0:
        return None

    return {
        "win_rate": round((wins / total) * 100, 2),
        "trade_count": total,
    }


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


def _build_session_item(item: dict[str, object]) -> dict[str, object]:
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    summary = item.get("summary", {}) if isinstance(item.get("summary"), dict) else {}
    artifact_type = str(item.get("artifact_type") or "report")
    symbol = str(metadata.get("symbol") or item.get("name") or "Sessione").strip()
    strategy_label = str(metadata.get("strategy_label") or metadata.get("strategy") or "Backtest").strip()
    interval = str(metadata.get("interval") or "n/a").strip()
    period_label = " -> ".join(
        part
        for part in (
            str(metadata.get("start") or "").strip(),
            str(metadata.get("end") or "").strip(),
        )
        if part
    ) or "Periodo non disponibile"
    created_at_display = _format_session_created_at(metadata.get("created_at"))

    if artifact_type == "sweep":
        delta_value = _to_float(summary.get("best_excess_return_pct"))
        return {
            "name": str(item.get("name") or ""),
            "artifact_type": artifact_type,
            "artifact_label": "Sweep",
            "title": symbol,
            "subtitle": f"Sweep - {strategy_label}",
            "interval": interval,
            "period_label": period_label,
            "created_at_display": created_at_display,
            "description": (
                f"Sweep {strategy_label} su {symbol} con migliore combinazione "
                f"{summary.get('best_fast', 'n/d')} / {summary.get('best_slow', 'n/d')}."
            ),
            "list_metric": _format_pct(_to_float(summary.get("best_total_return_pct"))),
            "list_metric_label": "Best return",
            "tone": _tone_from_delta(delta_value),
            "metrics": [
                {"label": "Best return", "value": _format_pct(_to_float(summary.get("best_total_return_pct")))},
                {"label": "Run valide", "value": str(summary.get("run_count", "n/d"))},
                {
                    "label": "Best params",
                    "value": f"{summary.get('best_fast', 'n/d')} / {summary.get('best_slow', 'n/d')}",
                },
                {"label": "Delta hold", "value": _format_pct(delta_value)},
            ],
            "preview_chart": item.get("preview_chart"),
        }

    delta_value = _to_float(summary.get("excess_return_pct"))
    trade_count_value = _to_float(summary.get("trade_count"))
    return {
        "name": str(item.get("name") or ""),
        "artifact_type": artifact_type,
        "artifact_label": "Backtest",
        "title": symbol,
        "subtitle": strategy_label,
        "interval": interval,
        "period_label": period_label,
        "created_at_display": created_at_display,
        "description": f"Backtest {strategy_label} su {symbol} nel timeframe {interval}.",
        "list_metric": _format_pct(_to_float(summary.get("total_return_pct"))),
        "list_metric_label": "Rendimento",
        "tone": _tone_from_delta(delta_value),
        "metrics": [
            {"label": "Rendimento", "value": _format_pct(_to_float(summary.get("total_return_pct")))},
            {"label": "Buy & hold", "value": _format_pct(_to_float(summary.get("benchmark_return_pct")))},
            {"label": "Delta hold", "value": _format_pct(delta_value)},
            {
                "label": "Trade",
                "value": str(int(trade_count_value)) if trade_count_value is not None else "n/d",
            },
        ],
        "preview_chart": item.get("preview_chart"),
    }


def _format_session_created_at(value: object) -> str:
    if value in ("", None):
        return "Data non disponibile"

    parsed: datetime | None = None
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value))
    else:
        text = str(value).strip()
        for parser in (
            lambda raw: datetime.fromisoformat(raw),
            lambda raw: datetime.strptime(raw, "%Y%m%d-%H%M%S"),
        ):
            try:
                parsed = parser(text)
                break
            except ValueError:
                continue
        if parsed is None:
            return text

    return parsed.strftime("%d/%m/%Y %H:%M")


def _tone_from_delta(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
