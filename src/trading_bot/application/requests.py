from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from trading_bot.application.constants import INTERVAL_OPTIONS, STRATEGY_OPTIONS
from trading_bot.errors import FormValidationError
from trading_bot.strategies import STRATEGY_SPECS, parse_strategy_parameters


def _text_value(raw: Mapping[str, object], name: str, default: str = "") -> str:
    value = raw.get(name, default)
    return str(value).strip() if value is not None else default


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
        symbol = _text_value(raw, "symbol").upper()
        start = _text_value(raw, "start")
        end = _text_value(raw, "end")
        interval = _text_value(raw, "interval", "1d")
        strategy = _text_value(raw, "strategy", "sma_cross")

        if not symbol:
            raise FormValidationError(
                "Inserisci un simbolo, per esempio SPY o BTC-USD.",
                fields=("symbol",),
            )
        if not start or not end:
            missing_fields = tuple(field for field, value in (("start", start), ("end", end)) if not value)
            raise FormValidationError(
                "Inserisci data iniziale e finale.",
                fields=missing_fields or ("start", "end"),
                display_field=missing_fields[0] if missing_fields else "start",
            )
        if strategy not in STRATEGY_OPTIONS:
            raise FormValidationError(
                f"Strategia non supportata: {strategy}.",
                fields=("strategy",),
            )
        if interval not in INTERVAL_OPTIONS:
            raise FormValidationError(
                f"Intervallo non supportato: {interval}.",
                fields=("interval",),
            )

        return cls(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            strategy=strategy,
            initial_capital=float(_text_value(raw, "initial_capital", "10000")),
            fee_bps=float(_text_value(raw, "fee_bps", "5")),
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
        strategy_spec = STRATEGY_SPECS[base_request.strategy]
        if not strategy_spec.supports_sweep:
            raise FormValidationError(
                "La modalita' sweep e' disponibile solo sulle strategie che supportano il test multiplo dei parametri.",
                fields=("run_mode", "strategy"),
                display_field="run_mode",
            )

        return cls(
            symbol=base_request.symbol,
            start=base_request.start,
            end=base_request.end,
            interval=base_request.interval,
            strategy=base_request.strategy,
            initial_capital=base_request.initial_capital,
            fee_bps=base_request.fee_bps,
            fast_range=IntegerRange(
                start=int(_text_value(raw, "fast_start", "10")),
                end=int(_text_value(raw, "fast_end", "40")),
                step=int(_text_value(raw, "fast_step", "10")),
            ),
            slow_range=IntegerRange(
                start=int(_text_value(raw, "slow_start", "80")),
                end=int(_text_value(raw, "slow_end", "200")),
                step=int(_text_value(raw, "slow_step", "20")),
            ),
            sort_by=_text_value(raw, "sort_by", "total_return_pct"),
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
            "parameter_labels": {
                "fast": STRATEGY_SPECS[self.strategy].parameter_map()["fast"].label,
                "slow": STRATEGY_SPECS[self.strategy].parameter_map()["slow"].label,
            },
            "sort_by": self.sort_by,
        }

    def iter_parameter_combinations(self) -> list[tuple[int, int]]:
        return [(fast, slow) for fast in self.fast_range.values() for slow in self.slow_range.values()]
