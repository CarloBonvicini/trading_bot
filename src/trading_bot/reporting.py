from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

SUMMARY_LABELS = {
    "initial_capital": "Capitale iniziale",
    "final_equity": "Equity finale",
    "total_return_pct": "Rendimento totale",
    "annual_return_pct": "Rendimento annuo",
    "annual_volatility_pct": "Volatilita' annua",
    "sharpe_ratio": "Sharpe",
    "max_drawdown_pct": "Max drawdown",
    "trade_count": "Numero trade",
    "exposure_pct": "Esposizione",
    "benchmark_return_pct": "Benchmark",
}

REPORT_NAME_PATTERN = re.compile(
    r"^(?P<symbol>.+)-(?P<strategy>sma_cross|rsi_mean_reversion)-(?P<timestamp>\d{8}-\d{6})$"
)


def list_reports(output_dir: str | Path) -> list[dict[str, object]]:
    output_path = Path(output_dir)
    if not output_path.exists():
        return []

    reports: list[dict[str, object]] = []
    for report_dir in output_path.iterdir():
        if not report_dir.is_dir():
            continue
        summary_file = report_dir / "summary.json"
        if not summary_file.exists():
            continue
        summary = _read_json(summary_file)
        metadata = read_report_metadata(report_dir)
        reports.append(
            {
                "name": report_dir.name,
                "path": report_dir,
                "summary": summary,
                "metadata": metadata,
                "created_at": metadata.get("created_at", ""),
            }
        )

    reports.sort(
        key=lambda item: (
            str(item["created_at"]),
            item["name"],
        ),
        reverse=True,
    )
    return reports


def load_report(output_dir: str | Path, report_name: str) -> dict[str, object]:
    report_dir = Path(output_dir) / report_name
    if not report_dir.exists():
        raise FileNotFoundError(f"Report '{report_name}' not found.")

    summary = _read_json(report_dir / "summary.json")
    metadata = read_report_metadata(report_dir)
    equity_curve = pd.read_csv(report_dir / "equity_curve.csv")
    trades = pd.read_csv(report_dir / "trades.csv")

    return {
        "name": report_name,
        "path": report_dir,
        "summary": summary,
        "metadata": metadata,
        "summary_cards": build_summary_cards(summary),
        "equity_chart": build_line_chart(
            {
                "Strategy": equity_curve["equity"],
                "Benchmark": equity_curve["benchmark_equity"],
            },
            colors={"Strategy": "#0f766e", "Benchmark": "#c084fc"},
        ),
        "drawdown_chart": build_line_chart(
            {"Drawdown": equity_curve["drawdown"] * 100},
            colors={"Drawdown": "#ef4444"},
        ),
        "equity_curve_rows": equity_curve.tail(20).to_dict(orient="records"),
        "trades": trades.fillna("").to_dict(orient="records"),
        "trade_preview": trades.fillna("").head(20).to_dict(orient="records"),
    }


def build_summary_cards(summary: dict[str, object]) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for key in (
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "trade_count",
        "benchmark_return_pct",
    ):
        value = summary.get(key, "")
        suffix = "%" if key.endswith("_pct") else ""
        display_value = f"{value}{suffix}" if suffix else str(value)
        cards.append({"label": SUMMARY_LABELS.get(key, key), "value": display_value})
    return cards


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
