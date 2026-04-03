from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from trading_bot.application.constants import INTERVAL_OPTIONS, RULE_LOGIC_OPTIONS, STRATEGY_OPTIONS
from trading_bot.errors import FormValidationError
from trading_bot.strategies import STRATEGY_SPECS, parse_strategy_parameters


def _text_value(raw: Mapping[str, object], name: str, default: str = "") -> str:
    value = raw.get(name, default)
    return str(value).strip() if value is not None else default


@dataclass(frozen=True)
class StrategyRuleSelection:
    slot: str
    strategy_id: str
    parameters: dict[str, int | float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STRATEGY_OPTIONS[self.strategy_id]["label"]

    def metadata(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "strategy": self.strategy_id,
            "strategy_label": self.label,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class BacktestRequest:
    symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    secondary_strategy: str = ""
    tertiary_strategy: str = ""
    rule_logic: str = "all"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    parameters: dict[str, int | float] = field(default_factory=dict)
    rules: tuple[StrategyRuleSelection, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "BacktestRequest":
        symbol = _text_value(raw, "symbol").upper()
        start = _text_value(raw, "start")
        end = _text_value(raw, "end")
        interval = _text_value(raw, "interval", "1d")
        strategy = _text_value(raw, "strategy", "sma_cross")
        secondary_strategy = _text_value(raw, "secondary_strategy")
        tertiary_strategy = _text_value(raw, "tertiary_strategy")
        rule_logic = _text_value(raw, "rule_logic", "all")

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
        for field_name, strategy_id in (("secondary_strategy", secondary_strategy), ("tertiary_strategy", tertiary_strategy)):
            if strategy_id and strategy_id not in STRATEGY_OPTIONS:
                raise FormValidationError(
                    f"Strategia non supportata: {strategy_id}.",
                    fields=(field_name,),
                )
        if interval not in INTERVAL_OPTIONS:
            raise FormValidationError(
                f"Intervallo non supportato: {interval}.",
                fields=("interval",),
            )
        if rule_logic not in RULE_LOGIC_OPTIONS:
            raise FormValidationError(
                "Scegli come combinare le regole selezionate.",
                fields=("rule_logic",),
            )

        rules = _parse_rule_selections(
            raw=raw,
            primary_strategy=strategy,
            secondary_strategy=secondary_strategy,
            tertiary_strategy=tertiary_strategy,
        )

        return cls(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            strategy=strategy,
            secondary_strategy=secondary_strategy,
            tertiary_strategy=tertiary_strategy,
            rule_logic=rule_logic,
            initial_capital=float(_text_value(raw, "initial_capital", "10000")),
            fee_bps=float(_text_value(raw, "fee_bps", "5")),
            parameters=rules[0].parameters,
            rules=tuple(rules),
        )

    @property
    def strategy_label(self) -> str:
        if not self.is_composite:
            return STRATEGY_OPTIONS[self.strategy]["label"]
        return f"Regole combinate ({self.rule_logic.upper()})"

    @property
    def rule_logic_label(self) -> str:
        return RULE_LOGIC_OPTIONS[self.rule_logic]

    @property
    def is_composite(self) -> bool:
        return len(self.rules) > 1

    @property
    def strategy_slug(self) -> str:
        if not self.is_composite:
            return self.strategy
        return f"multi_rules_{self.rule_logic}"

    def strategy_parameters(self) -> dict[str, int | float]:
        return dict(self.parameters)

    def active_rules(self) -> list[StrategyRuleSelection]:
        return list(self.rules)

    def metadata(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "interval": self.interval,
            "artifact_type": "report",
            "strategy": self.strategy_slug,
            "strategy_label": self.strategy_label,
            "primary_strategy": self.strategy,
            "primary_strategy_label": STRATEGY_OPTIONS[self.strategy]["label"],
            "secondary_strategy": self.secondary_strategy,
            "tertiary_strategy": self.tertiary_strategy,
            "rule_logic": self.rule_logic,
            "rule_logic_label": self.rule_logic_label,
            "is_composite": self.is_composite,
            "active_rules": [rule.metadata() for rule in self.rules],
            "initial_capital": self.initial_capital,
            "fee_bps": self.fee_bps,
            "parameters": self.strategy_parameters(),
        }


def _parse_rule_selections(
    *,
    raw: Mapping[str, object],
    primary_strategy: str,
    secondary_strategy: str,
    tertiary_strategy: str,
) -> list[StrategyRuleSelection]:
    raw_selections = [
        ("primary", "strategy", primary_strategy),
        ("secondary", "secondary_strategy", secondary_strategy),
        ("tertiary", "tertiary_strategy", tertiary_strategy),
    ]
    seen_fields_by_strategy: dict[str, str] = {}
    rules: list[StrategyRuleSelection] = []

    for slot, field_name, strategy_id in raw_selections:
        if not strategy_id:
            continue
        if strategy_id in seen_fields_by_strategy:
            raise FormValidationError(
                "Ogni regola deve essere diversa: non selezionare la stessa strategia piu' volte.",
                fields=(seen_fields_by_strategy[strategy_id], field_name),
                display_field=field_name,
            )

        rules.append(
            StrategyRuleSelection(
                slot=slot,
                strategy_id=strategy_id,
                parameters=parse_strategy_parameters(strategy_id, raw),
            )
        )
        seen_fields_by_strategy[strategy_id] = field_name

    return rules


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
        if base_request.is_composite:
            raise FormValidationError(
                "Lo sweep multiplo richiede una sola regola primaria. Rimuovi le regole aggiuntive oppure usa Test singolo.",
                fields=("run_mode", "secondary_strategy", "tertiary_strategy"),
                display_field="run_mode",
            )
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
