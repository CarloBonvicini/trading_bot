from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from trading_bot.backtest import BacktestResult, run_backtest, save_report
from trading_bot.data import INTRADAY_LOOKBACK_DAYS, download_price_data
from trading_bot.strategies import (
    STRATEGY_SPECS,
    build_strategy_signal,
    default_parameter_values,
    parse_strategy_parameters,
    strategy_field_name,
    strategy_options,
)

DEFAULT_REPORTS_DIR = Path("reports")
INTERVAL_OPTIONS = ("1m", "2m", "5m", "15m", "30m", "1h", "90m", "1d", "1wk", "1mo")
RUN_MODE_OPTIONS = ("single", "sweep")
SWEEP_SORT_OPTIONS = {
    "total_return_pct": "Best rendimento totale",
    "excess_return_pct": "Best delta vs hold",
    "sharpe_ratio": "Best Sharpe",
    "max_drawdown_pct": "Best max drawdown",
}
STRATEGY_OPTIONS = strategy_options()
PRESETS_FILENAME = "strategy_presets.json"
PRESET_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class BacktestRequest:
    symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    parameters: dict[str, int | float] = field(default_factory=dict)

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
            parameters=parse_strategy_parameters(strategy, raw),
        )

    @property
    def strategy_label(self) -> str:
        return STRATEGY_OPTIONS[self.strategy]["label"]

    def strategy_parameters(self) -> dict[str, int | float]:
        return dict(self.parameters)

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
            "parameter_space": {
                "fast": self.fast_range.as_dict(),
                "slow": self.slow_range.as_dict(),
            },
            "sort_by": self.sort_by,
        }

    def iter_parameter_combinations(self) -> list[tuple[int, int]]:
        return [(fast, slow) for fast in self.fast_range.values() for slow in self.slow_range.values()]


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

        parameters = {"fast": fast, "slow": slow}
        signal = build_strategy_signal(strategy_id="sma_cross", data=data, parameters=parameters)
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


def preset_storage_path(output_dir: str | Path = DEFAULT_REPORTS_DIR) -> Path:
    return Path(output_dir) / PRESETS_FILENAME


def list_strategy_presets(output_dir: str | Path = DEFAULT_REPORTS_DIR) -> list[dict[str, object]]:
    path = preset_storage_path(output_dir)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        presets = json.load(handle)
    return sorted(presets, key=lambda item: str(item.get("saved_at", "")), reverse=True)


def save_strategy_preset(raw: Mapping[str, object], output_dir: str | Path = DEFAULT_REPORTS_DIR) -> dict[str, object]:
    preset_name = str(raw.get("preset_name", "")).strip()
    if not preset_name:
        raise ValueError("Dammi un nome per salvare il preset strategia.")

    request = BacktestRequest.from_mapping(raw)
    run_mode = str(raw.get("run_mode", "single")).strip().lower()
    if run_mode not in RUN_MODE_OPTIONS:
        run_mode = "single"
    if run_mode == "sweep" and request.strategy != "sma_cross":
        run_mode = "single"

    preset = {
        "id": _preset_slug(preset_name),
        "name": preset_name,
        "strategy": request.strategy,
        "strategy_label": request.strategy_label,
        "interval": request.interval,
        "initial_capital": request.initial_capital,
        "fee_bps": request.fee_bps,
        "run_mode": run_mode,
        "parameters": request.strategy_parameters(),
        "sweep_settings": {
            "sort_by": str(raw.get("sort_by", "total_return_pct")),
            "fast_start": int(float(raw.get("fast_start", 10))),
            "fast_end": int(float(raw.get("fast_end", 40))),
            "fast_step": int(float(raw.get("fast_step", 10))),
            "slow_start": int(float(raw.get("slow_start", 80))),
            "slow_end": int(float(raw.get("slow_end", 200))),
            "slow_step": int(float(raw.get("slow_step", 20))),
        },
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }

    existing = list_strategy_presets(output_dir)
    updated = [item for item in existing if str(item.get("id")) != preset["id"]]
    updated.insert(0, preset)

    path = preset_storage_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(updated, handle, indent=2)
    return preset


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
        "initial_capital": 10_000.0,
        "fee_bps": 5.0,
        "sort_by": "total_return_pct",
        "fast_start": 10,
        "fast_end": 40,
        "fast_step": 10,
        "slow_start": 80,
        "slow_end": 200,
        "slow_step": 20,
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
            "initial_capital": backtest_request.initial_capital,
            "fee_bps": backtest_request.fee_bps,
        }
    )
    for parameter_name, parameter_value in backtest_request.strategy_parameters().items():
        values[strategy_field_name(backtest_request.strategy, parameter_name)] = parameter_value
    return values


def _preset_slug(name: str) -> str:
    normalized = PRESET_NAME_PATTERN.sub("-", name.lower()).strip("-")
    return normalized or "strategy-preset"


def interval_helper_texts() -> dict[str, str]:
    hints: dict[str, str] = {}
    for interval in INTERVAL_OPTIONS:
        lookback_days = INTRADAY_LOOKBACK_DAYS.get(interval)
        if lookback_days is None:
            hints[interval] = "Storico ampio disponibile."
        else:
            hints[interval] = f"Yahoo limita questo timeframe agli ultimi {lookback_days} giorni."
    return hints
