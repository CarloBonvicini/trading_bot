from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from trading_bot.backtest import BacktestResult, run_backtest, save_report
from trading_bot.data import download_price_data
from trading_bot.strategies import rsi_mean_reversion, sma_crossover

DEFAULT_REPORTS_DIR = Path("reports")
INTERVAL_OPTIONS = ("1h", "1d", "1wk", "1mo")

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


def write_report_metadata(report_dir: Path, backtest_request: BacktestRequest) -> None:
    metadata = {
        **backtest_request.metadata(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "report_name": report_dir.name,
    }
    with (report_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)


def default_form_values() -> dict[str, object]:
    current_year = datetime.now().year
    return {
        "symbol": "SPY",
        "start": f"{current_year - 6}-01-01",
        "end": f"{current_year - 1}-12-31",
        "interval": "1d",
        "strategy": "sma_cross",
        "initial_capital": 10_000.0,
        "fee_bps": 5.0,
        "fast": 20,
        "slow": 100,
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
