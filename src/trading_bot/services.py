from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from trading_bot.backtest import BacktestResult, run_backtest, save_report
from trading_bot.data import download_price_data
from trading_bot.strategies import rsi_mean_reversion, sma_crossover

DEFAULT_REPORTS_DIR = Path("reports")
INTERVAL_OPTIONS = ("1h", "1d", "1wk", "1mo")
RUN_MODE_OPTIONS = ("single", "sweep")
SWEEP_SORT_OPTIONS = {
    "total_return_pct": "Best rendimento totale",
    "excess_return_pct": "Best delta vs hold",
    "sharpe_ratio": "Best Sharpe",
    "max_drawdown_pct": "Best max drawdown",
}

STRATEGY_OPTIONS = {
    "sma_cross": {
        "label": "SMA Crossover",
        "description": "Va long quando la media mobile veloce supera quella lenta.",
    },
    "rsi_mean_reversion": {
        "label": "RSI Mean Reversion",
        "description": "Compra dopo ipervenduto RSI e chiude quando il momentum rientra.",
    },
}


@dataclass(frozen=True)
class BacktestRequest:
    symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    fast: int = 20
    slow: int = 100
    rsi_period: int = 14
    rsi_lower: float = 30.0
    rsi_upper: float = 55.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "BacktestRequest":
        def text(name: str, default: str = "") -> str:
            value = raw.get(name, default)
            return str(value).strip() if value is not None else default

        symbol = text("symbol").upper()
        start = text("start")
        end = text("end")
        interval = text("interval", "1d")
        strategy = text("strategy", "sma_cross")

        if not symbol:
            raise ValueError("Inserisci un simbolo, per esempio SPY o BTC-USD.")
        if not start or not end:
            raise ValueError("Inserisci data iniziale e finale.")
        if strategy not in STRATEGY_OPTIONS:
            raise ValueError(f"Strategia non supportata: {strategy}.")
        if interval not in INTERVAL_OPTIONS:
            raise ValueError(f"Intervallo non supportato: {interval}.")

        return cls(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            strategy=strategy,
            initial_capital=float(text("initial_capital", "10000")),
            fee_bps=float(text("fee_bps", "5")),
            fast=int(text("fast", "20")),
            slow=int(text("slow", "100")),
            rsi_period=int(text("rsi_period", "14")),
            rsi_lower=float(text("rsi_lower", "30")),
            rsi_upper=float(text("rsi_upper", "55")),
        )

    @property
    def strategy_label(self) -> str:
        return STRATEGY_OPTIONS[self.strategy]["label"]

    def strategy_parameters(self) -> dict[str, float | int]:
        if self.strategy == "sma_cross":
            return {"fast": self.fast, "slow": self.slow}
        return {
            "rsi_period": self.rsi_period,
            "rsi_lower": self.rsi_lower,
            "rsi_upper": self.rsi_upper,
        }

    def metadata(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "interval": self.interval,
            "artifact_type": "report",
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "initial_capital": self.initial_capital,
            "fee_bps": self.fee_bps,
            "parameters": self.strategy_parameters(),
        }


@dataclass(frozen=True)
class CompletedBacktest:
    request: BacktestRequest
    report_dir: Path
    result: BacktestResult


@dataclass(frozen=True)
class IntegerRange:
    start: int
    end: int
    step: int

    def values(self) -> list[int]:
        if self.step <= 0:
            raise ValueError("Il passo deve essere maggiore di zero.")
        if self.end < self.start:
            raise ValueError("Il valore finale deve essere maggiore o uguale a quello iniziale.")
        return list(range(self.start, self.end + 1, self.step))

    def as_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end, "step": self.step}


@dataclass(frozen=True)
class SweepRequest:
    symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    fast_range: IntegerRange = IntegerRange(10, 40, 10)
    slow_range: IntegerRange = IntegerRange(80, 200, 20)
    sort_by: str = "total_return_pct"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SweepRequest":
        base_request = BacktestRequest.from_mapping(raw)
        if base_request.strategy != "sma_cross":
            raise ValueError("La modalita' sweep e' disponibile per ora solo sulla strategia SMA Crossover.")

        def text(name: str, default: str = "") -> str:
            value = raw.get(name, default)
            return str(value).strip() if value is not None else default

        return cls(
            symbol=base_request.symbol,
            start=base_request.start,
            end=base_request.end,
            interval=base_request.interval,
            strategy=base_request.strategy,
            initial_capital=base_request.initial_capital,
            fee_bps=base_request.fee_bps,
            fast_range=IntegerRange(
                start=int(text("fast_start", "10")),
                end=int(text("fast_end", "40")),
                step=int(text("fast_step", "10")),
            ),
            slow_range=IntegerRange(
                start=int(text("slow_start", "80")),
                end=int(text("slow_end", "200")),
                step=int(text("slow_step", "20")),
            ),
            sort_by=text("sort_by", "total_return_pct"),
        )

    @property
    def strategy_label(self) -> str:
        return STRATEGY_OPTIONS[self.strategy]["label"]

    def parameter_space(self) -> dict[str, dict[str, int]]:
        return {
            "fast": self.fast_range.as_dict(),
            "slow": self.slow_range.as_dict(),
        }

    def metadata(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "interval": self.interval,
            "artifact_type": "sweep",
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "initial_capital": self.initial_capital,
            "fee_bps": self.fee_bps,
            "parameter_space": self.parameter_space(),
            "sort_by": self.sort_by,
        }

    def iter_parameter_combinations(self) -> list[tuple[int, int]]:
        combinations: list[tuple[int, int]] = []
        for fast in self.fast_range.values():
            for slow in self.slow_range.values():
                combinations.append((fast, slow))
        return combinations


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
) -> CompletedBacktest:
    data = download_price_data(
        symbol=backtest_request.symbol,
        start=backtest_request.start,
        end=backtest_request.end,
        interval=backtest_request.interval,
    )

    if backtest_request.strategy == "sma_cross":
        signal = sma_crossover(
            data,
            fast=backtest_request.fast,
            slow=backtest_request.slow,
        )
    else:
        signal = rsi_mean_reversion(
            data,
            period=backtest_request.rsi_period,
            lower=backtest_request.rsi_lower,
            upper=backtest_request.rsi_upper,
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
    return CompletedBacktest(
        request=backtest_request,
        report_dir=report_dir,
        result=result,
    )


def run_sma_sweep_request(
    sweep_request: SweepRequest,
    output_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> CompletedSweep:
    if sweep_request.sort_by not in SWEEP_SORT_OPTIONS:
        raise ValueError(f"Ordinamento sweep non supportato: {sweep_request.sort_by}.")

    data = download_price_data(
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

        signal = sma_crossover(data, fast=fast, slow=slow)
        result = run_backtest(
            data=data,
            signal=signal,
            initial_capital=sweep_request.initial_capital,
            fee_bps=sweep_request.fee_bps,
        )
        row = {
            "fast": fast,
            "slow": slow,
            **result.summary,
        }
        results.append(row)
        completed_by_parameters[(fast, slow)] = result

    if not results:
        raise ValueError("Nessuna combinazione valida da testare. Controlla i range SMA e assicurati che fast < slow.")

    results_df = pd.DataFrame(results)
    sort_columns: list[str] = []
    for column in [sweep_request.sort_by, "sharpe_ratio", "max_drawdown_pct"]:
        if column in results_df.columns and column not in sort_columns:
            sort_columns.append(column)
    ascending = [False, False, False][: len(sort_columns)]
    results_df = results_df.sort_values(by=sort_columns, ascending=ascending, kind="stable").reset_index(drop=True)
    results_df.insert(0, "rank", range(1, len(results_df) + 1))

    best_row = results_df.iloc[0].to_dict()
    best_parameters = (int(best_row["fast"]), int(best_row["slow"]))
    best_result = completed_by_parameters[best_parameters]
    summary = {
        "artifact_type": "sweep",
        "run_count": int(len(results_df)),
        "invalid_combinations": int(invalid_combinations),
        "sort_by": sweep_request.sort_by,
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

    sweep_dir = save_sweep_report(
        sweep_request=sweep_request,
        results=results_df,
        summary=summary,
        best_result=best_result,
        output_dir=output_dir,
    )
    return CompletedSweep(
        request=sweep_request,
        sweep_dir=sweep_dir,
        results=results_df,
        summary=summary,
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


def default_form_values() -> dict[str, object]:
    current_year = datetime.now().year
    return {
        "run_mode": "single",
        "symbol": "SPY",
        "start": f"{current_year - 6}-01-01",
        "end": f"{current_year - 1}-12-31",
        "interval": "1d",
        "strategy": "sma_cross",
        "initial_capital": 10_000.0,
        "fee_bps": 5.0,
        "sort_by": "total_return_pct",
        "fast": 20,
        "slow": 100,
        "fast_start": 10,
        "fast_end": 40,
        "fast_step": 10,
        "slow_start": 80,
        "slow_end": 200,
        "slow_step": 20,
        "rsi_period": 14,
        "rsi_lower": 30.0,
        "rsi_upper": 55.0,
    }


def as_form_values(backtest_request: BacktestRequest | None = None) -> dict[str, object]:
    values = default_form_values()
    if backtest_request is None:
        return values
    values.update(asdict(backtest_request))
    return values
