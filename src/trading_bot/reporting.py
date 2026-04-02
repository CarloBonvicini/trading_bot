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
        summary = enrich_summary(_read_json(summary_file), report_dir)
        metadata = read_report_metadata(report_dir)
        equity_curve = _read_equity_curve(report_dir)
        reports.append(
            {
                "name": report_dir.name,
                "path": report_dir,
                "summary": summary,
                "metadata": metadata,
                "created_at": metadata.get("created_at", ""),
                "comparison": build_comparison(summary),
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

    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    metadata = read_report_metadata(report_dir)
    equity_curve = _read_equity_curve(report_dir)
    trades = pd.read_csv(report_dir / "trades.csv")

    return {
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
        "trade_preview": trades.fillna("").head(20).to_dict(orient="records"),
    }


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
