from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from trading_bot.application.constants import DEFAULT_REPORTS_DIR, SWEEP_SORT_OPTIONS
from trading_bot.application.requests import BacktestRequest, SweepRequest
from trading_bot.backtest import BacktestResult, run_backtest, save_report
from trading_bot.data import download_price_data
from trading_bot.strategies import build_strategy_signal


@dataclass(frozen=True)
class CompletedBacktest:
    request: BacktestRequest
    report_dir: Path
    result: BacktestResult


@dataclass(frozen=True)
class CompletedSweep:
    request: SweepRequest
    sweep_dir: Path
    results: pd.DataFrame
    summary: dict[str, object]
    best_result: BacktestResult


def run_backtest_request(
    backtest_request: BacktestRequest,
    output_dir: str | Path = DEFAULT_REPORTS_DIR,
    *,
    download_data: Callable[..., pd.DataFrame] = download_price_data,
) -> CompletedBacktest:
    data = download_data(
        symbol=backtest_request.symbol,
        start=backtest_request.start,
        end=backtest_request.end,
        interval=backtest_request.interval,
    )
    signal = build_strategy_signal(
        strategy_id=backtest_request.strategy,
        data=data,
        parameters=backtest_request.strategy_parameters(),
    )
    result = run_backtest(
        data=data,
        signal=signal,
        initial_capital=backtest_request.initial_capital,
        fee_bps=backtest_request.fee_bps,
    )

    report_dir = save_report(
        result=result,
        output_dir=Path(output_dir),
        symbol=backtest_request.symbol,
        strategy_name=backtest_request.strategy,
    )
    write_report_metadata(report_dir=report_dir, backtest_request=backtest_request)
    return CompletedBacktest(request=backtest_request, report_dir=report_dir, result=result)


def run_sma_sweep_request(
    sweep_request: SweepRequest,
    output_dir: str | Path = DEFAULT_REPORTS_DIR,
    *,
    download_data: Callable[..., pd.DataFrame] = download_price_data,
) -> CompletedSweep:
    if sweep_request.sort_by not in SWEEP_SORT_OPTIONS:
        raise ValueError(f"Ordinamento sweep non supportato: {sweep_request.sort_by}.")

    data = download_data(
        symbol=sweep_request.symbol,
        start=sweep_request.start,
        end=sweep_request.end,
        interval=sweep_request.interval,
    )

    results: list[dict[str, object]] = []
    completed_by_parameters: dict[tuple[int, int], BacktestResult] = {}
    invalid_combinations = 0

    for fast, slow in sweep_request.iter_parameter_combinations():
        if fast >= slow:
            invalid_combinations += 1
            continue

        parameters = {"fast": fast, "slow": slow}
        signal = build_strategy_signal(strategy_id=sweep_request.strategy, data=data, parameters=parameters)
        result = run_backtest(
            data=data,
            signal=signal,
            initial_capital=sweep_request.initial_capital,
            fee_bps=sweep_request.fee_bps,
        )
        results.append({"fast": fast, "slow": slow, **result.summary})
        completed_by_parameters[(fast, slow)] = result

    if not results:
        raise ValueError("Nessuna combinazione valida da testare. Controlla i range SMA e assicurati che fast < slow.")

    results_df = pd.DataFrame(results)
    sort_columns = _resolve_sweep_sort_columns(sweep_request.sort_by, results_df)
    ascending = [False] * len(sort_columns)
    results_df = results_df.sort_values(by=sort_columns, ascending=ascending, kind="stable").reset_index(drop=True)
    results_df.insert(0, "rank", range(1, len(results_df) + 1))

    best_result, summary = _build_sweep_summary(results_df=results_df, completed_by_parameters=completed_by_parameters, sort_by=sweep_request.sort_by)
    sweep_dir = save_sweep_report(
        sweep_request=sweep_request,
        results=results_df,
        summary={**summary, "invalid_combinations": int(invalid_combinations)},
        best_result=best_result,
        output_dir=output_dir,
    )
    return CompletedSweep(
        request=sweep_request,
        sweep_dir=sweep_dir,
        results=results_df,
        summary={**summary, "invalid_combinations": int(invalid_combinations)},
        best_result=best_result,
    )


def write_report_metadata(report_dir: Path, backtest_request: BacktestRequest) -> None:
    metadata = {
        **backtest_request.metadata(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "report_name": report_dir.name,
    }
    with (report_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)


def save_sweep_report(
    sweep_request: SweepRequest,
    results: pd.DataFrame,
    summary: dict[str, object],
    best_result: BacktestResult,
    output_dir: str | Path,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sweep_dir = Path(output_dir) / f"{sweep_request.symbol.replace('/', '_')}-{sweep_request.strategy}-sweep-{timestamp}"
    sweep_dir.mkdir(parents=True, exist_ok=True)

    with (sweep_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with (sweep_dir / "best_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(best_result.summary, handle, indent=2)
    with (sweep_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                **sweep_request.metadata(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "report_name": sweep_dir.name,
            },
            handle,
            indent=2,
        )

    results.to_csv(sweep_dir / "results.csv", index=False)
    best_result.equity_curve.to_csv(sweep_dir / "best_equity_curve.csv", index_label="date")
    best_result.trades.to_csv(sweep_dir / "best_trades.csv", index=False)
    return sweep_dir


def _resolve_sweep_sort_columns(sort_by: str, results_df: pd.DataFrame) -> list[str]:
    sort_columns: list[str] = []
    for column in [sort_by, "sharpe_ratio", "max_drawdown_pct"]:
        if column in results_df.columns and column not in sort_columns:
            sort_columns.append(column)
    return sort_columns


def _build_sweep_summary(
    *,
    results_df: pd.DataFrame,
    completed_by_parameters: dict[tuple[int, int], BacktestResult],
    sort_by: str,
) -> tuple[BacktestResult, dict[str, object]]:
    best_row = results_df.iloc[0].to_dict()
    best_parameters = (int(best_row["fast"]), int(best_row["slow"]))
    best_result = completed_by_parameters[best_parameters]
    summary = {
        "artifact_type": "sweep",
        "run_count": int(len(results_df)),
        "sort_by": sort_by,
        "best_fast": int(best_row["fast"]),
        "best_slow": int(best_row["slow"]),
        "best_total_return_pct": round(float(best_row["total_return_pct"]), 2),
        "best_sharpe_ratio": round(float(best_row["sharpe_ratio"]), 3),
        "best_max_drawdown_pct": round(float(best_row["max_drawdown_pct"]), 2),
        "best_final_equity": round(float(best_row["final_equity"]), 2),
        "best_benchmark_return_pct": round(float(best_row["benchmark_return_pct"]), 2),
        "best_excess_return_pct": round(float(best_row["excess_return_pct"]), 2),
        "best_fees_paid": round(float(best_row["fees_paid"]), 2),
    }
    return best_result, summary
