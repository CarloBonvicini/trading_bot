from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

SUMMARY_LABELS = {
    "initial_capital": "Capitale iniziale",
    "final_equity": "Equity finale",
    "gross_final_equity": "Equity senza fee",
    "benchmark_final_equity": "Equity buy & hold",
    "total_return_pct": "Rendimento totale",
    "annual_return_pct": "Rendimento annuo",
    "annual_volatility_pct": "Volatilita' annua",
    "sharpe_ratio": "Sharpe",
    "max_drawdown_pct": "Max drawdown",
    "trade_count": "Numero trade",
    "exposure_pct": "Esposizione",
    "benchmark_return_pct": "Buy & hold",
    "excess_return_pct": "Delta vs hold",
    "fees_paid": "Spese totali",
    "fees_paid_pct_initial_capital": "Spese su capitale",
    "fee_drag_equity": "Impatto fee",
}

REPORT_NAME_PATTERN = re.compile(r"^(?P<symbol>.+)-(?P<strategy>[a-z_]+)-(?P<timestamp>\d{8}-\d{6})$")


def list_saved_items(output_dir: str | Path) -> list[dict[str, object]]:
    output_path = Path(output_dir)
    if not output_path.exists():
        return []

    items: list[dict[str, object]] = []
    for item_dir in output_path.iterdir():
        if not item_dir.is_dir():
            continue
        summary_file = item_dir / "summary.json"
        if not summary_file.exists():
            continue
        metadata = read_report_metadata(item_dir)
        artifact_type = str(metadata.get("artifact_type", "report"))
        if artifact_type == "sweep":
            items.append(_build_sweep_list_item(item_dir=item_dir, metadata=metadata))
        else:
            items.append(_build_report_list_item(report_dir=item_dir, metadata=metadata))

    items.sort(
        key=lambda item: (
            str(item["created_at"]),
            item["name"],
        ),
        reverse=True,
    )
    return items


def list_reports(output_dir: str | Path) -> list[dict[str, object]]:
    return [item for item in list_saved_items(output_dir) if item.get("artifact_type") == "report"]


def load_report(output_dir: str | Path, report_name: str) -> dict[str, object]:
    report_dir = Path(output_dir) / report_name
    if not report_dir.exists():
        raise FileNotFoundError(f"Report '{report_name}' not found.")

    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    metadata = read_report_metadata(report_dir)
    equity_curve = _read_equity_curve(report_dir)
    trades = pd.read_csv(report_dir / "trades.csv")

    return {
        "artifact_type": "report",
        "name": report_name,
        "path": report_dir,
        "summary": summary,
        "metadata": metadata,
        "summary_cards": build_summary_cards(summary),
        "comparison": build_comparison(summary),
        "equity_chart": build_line_chart(
            {
                "Strategy": equity_curve["equity"],
                "Buy & hold": equity_curve["benchmark_equity"],
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
        ),
        "drawdown_chart": build_line_chart(
            {"Drawdown": equity_curve["drawdown"] * 100},
            colors={"Drawdown": "#ef4444"},
        ),
        "equity_curve_rows": equity_curve.tail(20).to_dict(orient="records"),
        "trades": trades.fillna("").to_dict(orient="records"),
        "trade_preview": build_trade_preview(trades, limit=20),
    }


def load_sweep(output_dir: str | Path, sweep_name: str) -> dict[str, object]:
    sweep_dir = Path(output_dir) / sweep_name
    if not sweep_dir.exists():
        raise FileNotFoundError(f"Sweep '{sweep_name}' not found.")

    metadata = read_report_metadata(sweep_dir)
    summary = _read_json(sweep_dir / "summary.json")
    results = pd.read_csv(sweep_dir / "results.csv")
    best_summary = enrich_summary(_read_json(sweep_dir / "best_summary.json"), sweep_dir)
    best_equity_curve = _read_best_equity_curve(sweep_dir)
    best_trades = pd.read_csv(sweep_dir / "best_trades.csv")

    top_results = results.sort_values(by=["rank"], ascending=True).head(40).copy()
    ranking_chart = build_line_chart(
        {"Top total return": sample_series(top_results["total_return_pct"], max_points=40)},
        colors={"Top total return": "#0f766e"},
        width=860,
        height=220,
        padding=24,
    )

    return {
        "artifact_type": "sweep",
        "name": sweep_name,
        "path": sweep_dir,
        "metadata": metadata,
        "summary": summary,
        "summary_cards": build_sweep_summary_cards(summary),
        "best_summary_cards": build_summary_cards(best_summary),
        "best_parameters": {
            "fast": summary.get("best_fast", ""),
            "slow": summary.get("best_slow", ""),
        },
        "best_comparison": build_comparison(best_summary),
        "best_equity_chart": build_line_chart(
            {
                "Strategy": best_equity_curve["equity"],
                "Buy & hold": best_equity_curve["benchmark_equity"],
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
        ),
        "best_drawdown_chart": build_line_chart(
            {"Drawdown": best_equity_curve["drawdown"] * 100},
            colors={"Drawdown": "#ef4444"},
        ),
        "ranking_chart": ranking_chart,
        "top_results": top_results.to_dict(orient="records"),
        "top_results_columns": [
            "rank",
            "fast",
            "slow",
            "total_return_pct",
            "benchmark_return_pct",
            "excess_return_pct",
            "sharpe_ratio",
            "max_drawdown_pct",
            "fees_paid",
        ],
        "best_trade_preview": build_trade_preview(best_trades, limit=20),
    }


def load_report_chart_window(output_dir: str | Path, report_name: str, focus: str = "equity") -> dict[str, object]:
    report_dir = Path(output_dir) / report_name
    if not report_dir.exists():
        raise FileNotFoundError(f"Report '{report_name}' not found.")

    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    metadata = read_report_metadata(report_dir)
    equity_curve = _read_equity_curve(report_dir)
    trades = pd.read_csv(report_dir / "trades.csv")

    return _build_chart_window_context(
        artifact_type="report",
        artifact_name=report_name,
        metadata=metadata,
        summary=summary,
        equity_curve=equity_curve,
        trades=trades,
        focus=focus,
        title=f"{metadata.get('symbol') or report_name} - {metadata.get('strategy_label') or metadata.get('strategy') or 'Backtest'}",
        subtitle=(
            f"Periodo {metadata.get('start', 'n/a')} -> {metadata.get('end', 'n/a')} - "
            f"Intervallo {metadata.get('interval', 'n/a')} - Fee {metadata.get('fee_bps', 'n/a')} bps"
        ),
    )


def load_sweep_chart_window(output_dir: str | Path, sweep_name: str, focus: str = "equity") -> dict[str, object]:
    sweep_dir = Path(output_dir) / sweep_name
    if not sweep_dir.exists():
        raise FileNotFoundError(f"Sweep '{sweep_name}' not found.")

    metadata = read_report_metadata(sweep_dir)
    summary = _read_json(sweep_dir / "summary.json")
    best_summary = enrich_summary(_read_json(sweep_dir / "best_summary.json"), sweep_dir)
    best_equity_curve = _read_best_equity_curve(sweep_dir)
    best_trades = pd.read_csv(sweep_dir / "best_trades.csv")
    parameter_labels = metadata.get("parameter_labels", {"fast": "Fast", "slow": "Slow"})

    return _build_chart_window_context(
        artifact_type="sweep",
        artifact_name=sweep_name,
        metadata=metadata,
        summary=best_summary,
        equity_curve=best_equity_curve,
        trades=best_trades,
        focus=focus,
        title=f"{metadata.get('symbol') or sweep_name} - Best {metadata.get('strategy_label') or metadata.get('strategy') or 'Sweep'}",
        subtitle=(
            f"Best {parameter_labels.get('fast', 'Fast')} {summary.get('best_fast', 'n/a')} / "
            f"{parameter_labels.get('slow', 'Slow')} {summary.get('best_slow', 'n/a')} - "
            f"Periodo {metadata.get('start', 'n/a')} -> {metadata.get('end', 'n/a')} - "
            f"Intervallo {metadata.get('interval', 'n/a')}"
        ),
    )


def build_summary_cards(summary: dict[str, object]) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for key in (
        "total_return_pct",
        "benchmark_return_pct",
        "excess_return_pct",
        "final_equity",
        "gross_final_equity",
        "benchmark_final_equity",
        "fees_paid",
        "fees_paid_pct_initial_capital",
        "max_drawdown_pct",
        "sharpe_ratio",
    ):
        value = summary.get(key, "")
        suffix = "%" if key.endswith("_pct") else ""
        if key.endswith("_equity") or key == "fees_paid":
            display_value = f"{value:,.2f}" if isinstance(value, (float, int)) else str(value)
        else:
            display_value = f"{value}{suffix}" if suffix else str(value)
        cards.append({"label": SUMMARY_LABELS.get(key, key), "value": display_value})
    return cards


def build_sweep_summary_cards(summary: dict[str, object]) -> list[dict[str, object]]:
    labels = {
        "run_count": "Combinazioni valide",
        "invalid_combinations": "Combinazioni scartate",
        "best_fast": "Best fast",
        "best_slow": "Best slow",
        "best_total_return_pct": "Best rendimento",
        "best_sharpe_ratio": "Best Sharpe",
        "best_max_drawdown_pct": "Best max drawdown",
        "best_fees_paid": "Best spese",
    }
    cards: list[dict[str, object]] = []
    for key in (
        "run_count",
        "invalid_combinations",
        "best_fast",
        "best_slow",
        "best_total_return_pct",
        "best_sharpe_ratio",
        "best_max_drawdown_pct",
        "best_fees_paid",
    ):
        value = summary.get(key, "")
        if key.endswith("_pct"):
            display_value = f"{value}%"
        elif key.endswith("_paid"):
            display_value = f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
        else:
            display_value = str(value)
        cards.append({"label": labels[key], "value": display_value})
    return cards


def build_comparison(summary: dict[str, object]) -> dict[str, object]:
    delta = float(summary.get("excess_return_pct", 0.0))
    if delta > 0:
        verdict = "La strategia ha battuto il semplice hold."
    elif delta < 0:
        verdict = "La strategia ha fatto peggio del semplice hold."
    else:
        verdict = "La strategia ha fatto come il semplice hold."

    return {
        "strategy_return_pct": summary.get("total_return_pct", ""),
        "hold_return_pct": summary.get("benchmark_return_pct", ""),
        "delta_pct": summary.get("excess_return_pct", ""),
        "strategy_final_equity": summary.get("final_equity", ""),
        "gross_strategy_final_equity": summary.get("gross_final_equity", ""),
        "hold_final_equity": summary.get("benchmark_final_equity", ""),
        "fees_paid": summary.get("fees_paid", ""),
        "fees_pct_initial_capital": summary.get("fees_paid_pct_initial_capital", ""),
        "fee_drag_equity": summary.get("fee_drag_equity", ""),
        "verdict": verdict,
    }


def build_market_snapshot(equity_curve: pd.DataFrame) -> dict[str, object]:
    timestamp_display = _extract_date_labels(equity_curve)[-1] if not equity_curve.empty else ""
    snapshot = {
        "has_market": False,
        "timestamp_display": timestamp_display,
        "open_display": "n/a",
        "high_display": "n/a",
        "low_display": "n/a",
        "close_display": "n/a",
        "change_display": "n/a",
        "change_pct_display": "n/a",
        "change_class": "neutral",
        "volume_display": "",
    }

    if equity_curve.empty or "close" not in equity_curve.columns:
        return snapshot

    last_row = equity_curve.iloc[-1]
    previous_row = equity_curve.iloc[-2] if len(equity_curve) > 1 else None

    close_value = _to_float(last_row.get("close"))
    if close_value is None:
        return snapshot

    open_value = _to_float(last_row.get("open"))
    high_value = _to_float(last_row.get("high"))
    low_value = _to_float(last_row.get("low"))
    previous_close = _to_float(previous_row.get("close")) if previous_row is not None else open_value
    volume_value = _to_float(last_row.get("volume"))

    change_value = (close_value - previous_close) if previous_close is not None else None
    change_pct_value = ((change_value / previous_close) * 100) if previous_close not in (None, 0) and change_value is not None else None
    if change_value is None:
        change_class = "neutral"
    elif change_value > 0:
        change_class = "positive"
    elif change_value < 0:
        change_class = "negative"
    else:
        change_class = "neutral"

    snapshot.update(
        {
            "has_market": True,
            "open_display": _format_terminal_number(open_value) if open_value is not None else "n/a",
            "high_display": _format_terminal_number(high_value) if high_value is not None else "n/a",
            "low_display": _format_terminal_number(low_value) if low_value is not None else "n/a",
            "close_display": _format_terminal_number(close_value),
            "change_display": _format_signed_number(change_value) if change_value is not None else "n/a",
            "change_pct_display": _format_signed_percent(change_pct_value) if change_pct_value is not None else "n/a",
            "change_class": change_class,
            "volume_display": _format_compact_number(volume_value) if volume_value is not None else "",
        }
    )
    return snapshot


def build_chart_layers(payload: dict[str, object]) -> list[dict[str, object]]:
    market = payload.get("market", {})
    equity = payload.get("equity", {})
    entry_markers = payload.get("entry_markers", {})
    exit_markers = payload.get("exit_markers", {})
    return [
        {"key": "price", "label": "Prezzo", "enabled": True, "locked": True},
        {
            "key": "volume",
            "label": "Volume",
            "enabled": any(value not in (None, 0, 0.0) for value in market.get("volume", [])),
            "locked": False,
        },
        {"key": "entry", "label": "Entry", "enabled": bool(entry_markers.get("x")), "locked": False},
        {"key": "exit", "label": "Exit", "enabled": bool(exit_markers.get("x")), "locked": False},
        {"key": "strategy", "label": "Strategia", "enabled": bool(equity.get("strategy")), "locked": True},
        {"key": "benchmark", "label": "Buy & hold", "enabled": bool(equity.get("benchmark")), "locked": False},
        {"key": "gross", "label": "Senza fee", "enabled": bool(equity.get("gross")), "locked": False},
        {"key": "drawdown", "label": "Drawdown", "enabled": True, "locked": False},
    ]


def enrich_summary(summary: dict[str, object], report_dir: Path) -> dict[str, object]:
    enriched = dict(summary)
    if (
        "benchmark_return_pct" in enriched
        and "benchmark_final_equity" in enriched
        and "excess_return_pct" in enriched
        and "fees_paid" in enriched
        and "fees_paid_pct_initial_capital" in enriched
        and "fee_drag_equity" in enriched
        and "gross_final_equity" in enriched
    ):
        return enriched

    initial_capital = float(enriched.get("initial_capital", 0.0))
    total_return_pct = float(enriched.get("total_return_pct", 0.0))

    equity_curve = _read_equity_curve(report_dir)
    benchmark_final_equity = float(equity_curve["benchmark_equity"].iloc[-1])
    benchmark_return_pct = round(((benchmark_final_equity / initial_capital) - 1) * 100, 2) if initial_capital else 0.0
    gross_equity = _ensure_gross_equity(equity_curve, initial_capital)
    transaction_cost_amount = _ensure_transaction_cost_amount(equity_curve, initial_capital)
    gross_final_equity = float(gross_equity.iloc[-1]) if len(gross_equity) else float(initial_capital)
    fees_paid = float(transaction_cost_amount.sum())

    enriched["benchmark_final_equity"] = round(benchmark_final_equity, 2)
    enriched["benchmark_return_pct"] = benchmark_return_pct
    enriched["excess_return_pct"] = round(total_return_pct - benchmark_return_pct, 2)
    enriched["gross_final_equity"] = round(gross_final_equity, 2)
    enriched["fees_paid"] = round(fees_paid, 2)
    enriched["fees_paid_pct_initial_capital"] = round((fees_paid / initial_capital) * 100, 2) if initial_capital else 0.0
    enriched["fee_drag_equity"] = round(gross_final_equity - float(enriched.get("final_equity", 0.0)), 2)
    return enriched


def read_report_metadata(report_dir: Path) -> dict[str, object]:
    metadata_file = report_dir / "metadata.json"
    if metadata_file.exists():
        metadata = _read_json(metadata_file)
    else:
        metadata = {}

    if "symbol" not in metadata or "strategy" not in metadata:
        metadata.update(_metadata_from_report_name(report_dir.name))
    if "created_at" not in metadata:
        metadata["created_at"] = report_dir.stat().st_mtime
    if "artifact_type" not in metadata:
        metadata["artifact_type"] = "report"
    return metadata


def build_line_chart(
    series_map: dict[str, pd.Series],
    colors: dict[str, str],
    width: int = 860,
    height: int = 280,
    padding: int = 24,
) -> dict[str, object]:
    prepared = {label: series.astype(float).reset_index(drop=True) for label, series in series_map.items()}
    if not prepared:
        raise ValueError("At least one series is required to build a chart.")

    values = pd.concat(prepared.values(), axis=0)
    minimum = float(values.min())
    maximum = float(values.max())
    if minimum == maximum:
        minimum -= 1.0
        maximum += 1.0

    chart_series = []
    for label, series in prepared.items():
        chart_series.append(
            {
                "label": label,
                "color": colors[label],
                "points": _series_to_points(
                    series=series,
                    minimum=minimum,
                    maximum=maximum,
                    width=width,
                    height=height,
                    padding=padding,
                ),
                "latest": round(float(series.iloc[-1]), 2),
            }
        )

    return {
        "width": width,
        "height": height,
        "min_label": round(minimum, 2),
        "max_label": round(maximum, 2),
        "zero_y": _value_to_y(
            value=0.0,
            minimum=minimum,
            maximum=maximum,
            height=height,
            padding=padding,
        ),
        "series": chart_series,
    }


def sample_series(series: pd.Series, max_points: int = 140) -> pd.Series:
    if len(series) <= max_points:
        return series.astype(float).reset_index(drop=True)

    step = max(len(series) // max_points, 1)
    sampled = series.iloc[::step]
    if sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])
    return sampled.astype(float).reset_index(drop=True)


def _series_to_points(
    series: pd.Series,
    minimum: float,
    maximum: float,
    width: int,
    height: int,
    padding: int,
) -> str:
    values = series.tolist()
    plot_width = max(width - (padding * 2), 1)
    denominator = max(len(values) - 1, 1)
    points = []
    for index, value in enumerate(values):
        x = padding + (plot_width * index / denominator)
        y = _value_to_y(
            value=float(value),
            minimum=minimum,
            maximum=maximum,
            height=height,
            padding=padding,
        )
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def _value_to_y(value: float, minimum: float, maximum: float, height: int, padding: int) -> float:
    scale = (value - minimum) / (maximum - minimum)
    plot_height = height - (padding * 2)
    return height - padding - (scale * plot_height)


def _metadata_from_report_name(report_name: str) -> dict[str, object]:
    match = REPORT_NAME_PATTERN.match(report_name)
    if not match:
        return {"strategy_label": "Backtest"}

    metadata = match.groupdict()
    strategy = str(metadata["strategy"])
    return {
        "symbol": metadata["symbol"],
        "strategy": strategy,
        "strategy_label": strategy.replace("_", " ").title(),
        "created_at": metadata["timestamp"],
    }


def _read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_equity_curve(report_dir: Path) -> pd.DataFrame:
    return pd.read_csv(report_dir / "equity_curve.csv")


def _read_best_equity_curve(sweep_dir: Path) -> pd.DataFrame:
    return pd.read_csv(sweep_dir / "best_equity_curve.csv")


def _build_chart_window_context(
    artifact_type: str,
    artifact_name: str,
    metadata: dict[str, object],
    summary: dict[str, object],
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    focus: str,
    title: str,
    subtitle: str,
) -> dict[str, object]:
    normalized_trades = trades.fillna("")
    payload = {
        "focus": focus,
        "dates": _extract_date_labels(equity_curve),
        "market": {
            "has_candles": all(column in equity_curve.columns for column in ("open", "high", "low")),
            "open": _series_to_json_list(equity_curve.get("open")),
            "high": _series_to_json_list(equity_curve.get("high")),
            "low": _series_to_json_list(equity_curve.get("low")),
            "close": _series_to_json_list(equity_curve.get("close")),
            "volume": _series_to_json_list(equity_curve.get("volume")),
        },
        "equity": {
            "strategy": _series_to_json_list(equity_curve.get("equity")),
            "gross": _series_to_json_list(equity_curve.get("gross_equity")),
            "benchmark": _series_to_json_list(equity_curve.get("benchmark_equity")),
        },
        "drawdown_pct": _series_to_json_list((equity_curve.get("drawdown", pd.Series(dtype=float)).fillna(0.0) * 100)),
        "entry_markers": _build_trade_markers(normalized_trades, side="entry"),
        "exit_markers": _build_trade_markers(normalized_trades, side="exit"),
    }

    return {
        "artifact_type": artifact_type,
        "artifact_name": artifact_name,
        "title": title,
        "subtitle": subtitle,
        "metadata": metadata,
        "summary": summary,
        "market_snapshot": build_market_snapshot(equity_curve),
        "layers": build_chart_layers(payload),
        "summary_cards": build_summary_cards(summary),
        "trade_preview": build_trade_preview(normalized_trades, limit=30),
        "chart_payload": payload,
    }


def _build_report_list_item(report_dir: Path, metadata: dict[str, object]) -> dict[str, object]:
    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    equity_curve = _read_equity_curve(report_dir)
    return {
        "artifact_type": "report",
        "name": report_dir.name,
        "path": report_dir,
        "summary": summary,
        "metadata": metadata,
        "created_at": metadata.get("created_at", ""),
        "comparison": build_comparison(summary),
        "detail_url": f"/reports/{report_dir.name}",
        "preview_chart": build_line_chart(
            {
                "Strategy": sample_series(equity_curve["equity"], max_points=72),
                "Buy & hold": sample_series(equity_curve["benchmark_equity"], max_points=72),
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
            width=300,
            height=94,
            padding=10,
        ),
    }


def _build_sweep_list_item(item_dir: Path, metadata: dict[str, object]) -> dict[str, object]:
    summary = _read_json(item_dir / "summary.json")
    results = pd.read_csv(item_dir / "results.csv")
    sorted_results = results.sort_values(by=["rank"], ascending=True) if "rank" in results.columns else results
    preview_chart = build_line_chart(
        {"Top total return": sample_series(sorted_results["total_return_pct"], max_points=50)},
        colors={"Top total return": "#0f766e"},
        width=300,
        height=94,
        padding=10,
    )
    return {
        "artifact_type": "sweep",
        "name": item_dir.name,
        "path": item_dir,
        "summary": summary,
        "metadata": metadata,
        "created_at": metadata.get("created_at", ""),
        "detail_url": f"/sweeps/{item_dir.name}",
        "preview_chart": preview_chart,
    }


def _extract_date_labels(equity_curve: pd.DataFrame) -> list[str]:
    if "date" in equity_curve.columns:
        dates = pd.to_datetime(equity_curve["date"], errors="coerce")
    else:
        dates = pd.to_datetime(equity_curve.index, errors="coerce")

    labels: list[str] = []
    for value in dates:
        if pd.isna(value):
            labels.append("")
            continue
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            labels.append(value.strftime("%Y-%m-%d"))
        else:
            labels.append(value.strftime("%Y-%m-%d %H:%M"))
    return labels


def _series_to_json_list(series: pd.Series | None) -> list[float | None]:
    if series is None:
        return []
    values: list[float | None] = []
    for value in series.tolist():
        if pd.isna(value):
            values.append(None)
        else:
            values.append(round(float(value), 6))
    return values


def _build_trade_markers(trades: pd.DataFrame, side: str) -> dict[str, list[object]]:
    date_key = f"{side}_date"
    price_key = f"{side}_price"
    markers = {"x": [], "y": [], "text": []}

    for trade in trades.to_dict(orient="records"):
        trade_date = str(trade.get(date_key, "")).strip()
        if not trade_date:
            continue

        price = trade.get(price_key, "")
        try:
            y_value = float(price)
        except (TypeError, ValueError):
            continue

        pnl = str(trade.get("pnl_pct", "")).strip() or "open"
        markers["x"].append(trade_date)
        markers["y"].append(round(y_value, 6))
        markers["text"].append(f"{side.title()} - PnL {pnl}%")

    return markers


def build_trade_preview(trades: pd.DataFrame, limit: int) -> list[dict[str, object]]:
    if trades.empty:
        return []

    normalized = trades.fillna("").head(limit).to_dict(orient="records")
    return [_format_trade_preview_row(row) for row in normalized]


def _format_trade_preview_row(row: dict[str, object]) -> dict[str, object]:
    entry_raw = str(row.get("entry_date", "")).strip()
    exit_raw = str(row.get("exit_date", "")).strip()
    entry_date_display, entry_time_display = _split_trade_timestamp(entry_raw)
    exit_date_display, exit_time_display = _split_trade_timestamp(exit_raw) if exit_raw else ("In corso", "")
    pnl_value = _to_float(row.get("pnl_pct"))
    status_label, status_class = _trade_status(exit_raw=exit_raw, pnl_value=pnl_value)

    return {
        "status_label": status_label,
        "status_class": status_class,
        "entry_price_display": _format_trade_price(row.get("entry_price")),
        "exit_price_display": _format_trade_price(row.get("exit_price")) if exit_raw else "In corso",
        "entry_date_display": entry_date_display,
        "entry_time_display": entry_time_display,
        "exit_date_display": exit_date_display,
        "exit_time_display": exit_time_display,
        "pnl_display": f"{pnl_value:+.2f}%" if pnl_value is not None else "-",
        "duration_display": _format_trade_duration(
            entry_raw=entry_raw,
            exit_raw=exit_raw,
            fallback_days=row.get("holding_days"),
        ),
    }


def _split_trade_timestamp(raw: str) -> tuple[str, str]:
    if not raw:
        return "-", ""

    timestamp = pd.to_datetime(raw, errors="coerce")
    if pd.isna(timestamp):
        return raw, ""

    if ":" in raw:
        return timestamp.strftime("%d/%m/%Y"), timestamp.strftime("%H:%M")
    return timestamp.strftime("%d/%m/%Y"), ""


def _trade_status(exit_raw: str, pnl_value: float | None) -> tuple[str, str]:
    if not exit_raw:
        return "OPEN", "open"
    if pnl_value is None:
        return "CLOSED", "neutral"
    if pnl_value > 0:
        return "WIN", "positive"
    if pnl_value < 0:
        return "LOSS", "negative"
    return "FLAT", "neutral"


def _format_trade_duration(entry_raw: str, exit_raw: str, fallback_days: object) -> str:
    if not entry_raw or not exit_raw:
        return "In corso"

    entry_ts = pd.to_datetime(entry_raw, errors="coerce")
    exit_ts = pd.to_datetime(exit_raw, errors="coerce")
    if not pd.isna(entry_ts) and not pd.isna(exit_ts):
        total_minutes = max(int((exit_ts - entry_ts).total_seconds() // 60), 0)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60
        if days > 0:
            return f"{days} g {hours} h" if hours else f"{days} g"
        if hours > 0:
            return f"{hours} h {minutes} min" if minutes else f"{hours} h"
        if minutes > 0:
            return f"{minutes} min"
        return "< 1 min"

    days_value = _to_float(fallback_days)
    if days_value is None:
        return "-"
    if days_value == 1:
        return "1 g"
    return f"{int(days_value)} g"


def _format_trade_price(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:.4f}".rstrip("0").rstrip(".")


def _format_terminal_number(value: float | None, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _format_signed_number(value: float | None, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _format_signed_percent(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def _format_compact_number(value: float, decimals: int = 1) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    return _format_terminal_number(value, decimals=0)


def _to_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ensure_gross_equity(equity_curve: pd.DataFrame, initial_capital: float) -> pd.Series:
    if "gross_equity" in equity_curve.columns:
        return equity_curve["gross_equity"].astype(float)

    if "gross_strategy_return" in equity_curve.columns:
        gross_returns = equity_curve["gross_strategy_return"].astype(float)
    else:
        gross_returns = equity_curve["position"].astype(float) * equity_curve["market_return"].astype(float)
    return initial_capital * (1 + gross_returns).cumprod()


def _ensure_transaction_cost_amount(equity_curve: pd.DataFrame, initial_capital: float) -> pd.Series:
    if "transaction_cost_amount" in equity_curve.columns:
        return equity_curve["transaction_cost_amount"].astype(float)

    if "transaction_cost_rate" in equity_curve.columns:
        transaction_cost_rate = equity_curve["transaction_cost_rate"].astype(float)
    else:
        gross_returns = equity_curve["position"].astype(float) * equity_curve["market_return"].astype(float)
        transaction_cost_rate = (gross_returns - equity_curve["strategy_return"].astype(float)).clip(lower=0.0)

    equity_before = equity_curve["equity"].astype(float).shift(1).fillna(initial_capital)
    return equity_before * transaction_cost_rate
