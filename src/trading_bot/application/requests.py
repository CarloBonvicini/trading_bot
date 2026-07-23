from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from trading_bot.application.constants import INTERVAL_OPTIONS, RULE_LOGIC_OPTIONS, STRATEGY_OPTIONS
from trading_bot.data import resolve_market_data_symbol
from trading_bot.errors import FormValidationError
from trading_bot.strategies import STRATEGY_SPECS, parse_strategy_parameters


def _text_value(raw: Mapping[str, object], name: str, default: str = "") -> str:
    value = raw.get(name, default)
    return str(value).strip() if value is not None else default


def _optional_positive_float(raw: Mapping[str, object], name: str) -> float | None:
    """Legge un float positivo opzionale. Restituisce None se assente o vuoto."""
    val = _text_value(raw, name, "")
    if not val:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except ValueError:
        return None


def _list_values(raw: Mapping[str, object], name: str) -> list[str]:
    if hasattr(raw, "getlist"):
        values = raw.getlist(name)
    else:
        value = raw.get(name, [])
        if isinstance(value, (list, tuple, set)):
            values = list(value)
        elif value in ("", None):
            values = []
        else:
            values = [value]

    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if "," in text:
            normalized.extend(part.strip() for part in text.split(",") if part.strip())
        else:
            normalized.append(text)
    return normalized


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
    data_symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    active_strategy_ids: tuple[str, ...] = ("sma_cross",)
    rule_logic: str = "all"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    parameters: dict[str, int | float] = field(default_factory=dict)
    rules: tuple[StrategyRuleSelection, ...] = field(default_factory=tuple)
    groups: tuple[dict[str, object], ...] = field(default_factory=tuple)
    expression: dict[str, object] | None = None
    # Gestione del rischio
    sl_pct: float | None = None       # stop loss percentuale (None = disabilitato)
    tp_pct: float | None = None       # take profit percentuale (None = disabilitato)
    sizing_method: str = "full"       # metodo di position sizing
    sizing_param: float = 100.0       # parametro del sizing (dipende dal metodo)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "BacktestRequest":
        symbol = _text_value(raw, "symbol").upper()
        data_symbol = resolve_market_data_symbol(symbol)
        start = _text_value(raw, "start")
        end = _text_value(raw, "end")
        interval = _text_value(raw, "interval", "1d")
        rule_logic = _text_value(raw, "rule_logic", "all")
        active_strategy_ids = _parse_active_strategy_ids(raw)
        strategy = active_strategy_ids[0]

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
        if not active_strategy_ids:
            raise FormValidationError(
                "Attiva almeno una regola strategica prima di lanciare il test.",
                fields=("active_strategies",),
                display_field="active_strategies",
            )
        if strategy not in STRATEGY_OPTIONS:
            raise FormValidationError(
                f"Strategia non supportata: {strategy}.",
                fields=("active_strategies",),
            )
        for strategy_id in active_strategy_ids:
            if strategy_id not in STRATEGY_OPTIONS:
                raise FormValidationError(
                    f"Strategia non supportata: {strategy_id}.",
                    fields=("active_strategies",),
                    display_field="active_strategies",
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
            active_strategy_ids=active_strategy_ids,
        )
        groups = tuple(_parse_groups(raw))
        expression = _parse_expression(raw)

        sl_pct = _optional_positive_float(raw, "sl_pct")
        tp_pct = _optional_positive_float(raw, "tp_pct")
        sizing_method = _text_value(raw, "sizing_method", "full")
        if sizing_method not in {"full", "fixed", "vol_target"}:
            sizing_method = "full"
        sizing_param = float(_text_value(raw, "sizing_param", "100") or "100")

        return cls(
            symbol=symbol,
            data_symbol=data_symbol,
            start=start,
            end=end,
            interval=interval,
            strategy=strategy,
            active_strategy_ids=tuple(active_strategy_ids),
            rule_logic=rule_logic,
            initial_capital=float(_text_value(raw, "initial_capital", "10000")),
            fee_bps=float(_text_value(raw, "fee_bps", "5")),
            parameters=rules[0].parameters,
            rules=tuple(rules),
            groups=groups,
            expression=expression,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            sizing_method=sizing_method,
            sizing_param=sizing_param,
        )

    @property
    def strategy_label(self) -> str:
        if not self.is_composite:
            return STRATEGY_OPTIONS[self.strategy]["label"]
        if self.groups:
            default_op = "OR" if self.rule_logic == "any" else "AND"
            parts: list[str] = []
            for i, g in enumerate(self.groups):
                strat_labels = [
                    STRATEGY_OPTIONS.get(str(s), {}).get("label", str(s))
                    for s in (g.get("strategies") or [])
                ]
                inner_logic = "OR" if str(g.get("logic", "all")) == "any" else "AND"
                if len(strat_labels) > 1:
                    parts.append(f"({f' {inner_logic} '.join(strat_labels)})")
                elif strat_labels:
                    parts.append(strat_labels[0])
                # Inserisce l'operatore inter-gruppo prima di ogni parte tranne la prima
                if i > 0 and len(parts) >= 2:
                    op = "OR" if str(g.get("op_before", self.rule_logic)) == "any" else "AND"
                    parts.insert(-1, op)
            if parts:
                return " ".join(parts)
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
            "data_symbol": self.data_symbol,
            "start": self.start,
            "end": self.end,
            "interval": self.interval,
            "artifact_type": "report",
            "strategy": self.strategy_slug,
            "strategy_label": self.strategy_label,
            "primary_strategy": self.strategy,
            "primary_strategy_label": STRATEGY_OPTIONS[self.strategy]["label"],
            "active_strategy_ids": list(self.active_strategy_ids),
            "rule_logic": self.rule_logic,
            "rule_logic_label": self.rule_logic_label,
            "is_composite": self.is_composite,
            "active_rules": [rule.metadata() for rule in self.rules],
            "groups": [dict(g) for g in self.groups],
            "initial_capital": self.initial_capital,
            "fee_bps": self.fee_bps,
            "sl_pct": self.sl_pct,
            "tp_pct": self.tp_pct,
            "sizing_method": self.sizing_method,
            "sizing_param": self.sizing_param,
            "parameters": self.strategy_parameters(),
        }


def _parse_expression(raw: Mapping[str, object]) -> dict[str, object] | None:
    """Estrae e valida il campo ``expression`` (albero di espressione con precedenza).

    Restituisce None se assente o non è un dict valido.
    """
    expr = raw.get("expression")
    if isinstance(expr, str):
        import json as _json
        try:
            expr = _json.loads(expr)
        except Exception:
            return None
    if not isinstance(expr, dict):
        return None
    return expr


def _parse_groups(raw: Mapping[str, object]) -> list[dict[str, object]]:
    """Valida e normalizza la lista dei gruppi dal payload.

    Restituisce lista vuota se non ci sono ≥2 gruppi validi (logica piatta).
    """
    raw_groups = raw.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) < 2:
        return []
    validated: list[dict[str, object]] = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        strategies = [str(s).strip() for s in (g.get("strategies") or []) if str(s).strip()]
        logic = str(g.get("logic") or "all").strip()
        if logic not in {"all", "any"}:
            logic = "all"
        op_before = str(g.get("op_before") or "all").strip()
        if op_before not in {"all", "any"}:
            op_before = "all"
        if strategies:
            entry: dict[str, object] = {"strategies": strategies, "logic": logic}
            if validated:  # op_before rilevante solo da gn=2 in poi
                entry["op_before"] = op_before
            validated.append(entry)
    return validated if len(validated) >= 2 else []


def _parse_rule_selections(
    *,
    raw: Mapping[str, object],
    active_strategy_ids: list[str],
) -> list[StrategyRuleSelection]:
    rules: list[StrategyRuleSelection] = []
    for index, strategy_id in enumerate(active_strategy_ids):
        rules.append(
            StrategyRuleSelection(
                slot=f"rule_{index + 1}",
                strategy_id=strategy_id,
                parameters=parse_strategy_parameters(strategy_id, raw),
            )
        )

    return rules


def _parse_active_strategy_ids(raw: Mapping[str, object]) -> list[str]:
    toggle_ids = _list_values(raw, "active_strategies")
    if toggle_ids:
        unique_toggle_ids: list[str] = []
        for strategy_id in toggle_ids:
            if strategy_id not in unique_toggle_ids:
                unique_toggle_ids.append(strategy_id)
        return unique_toggle_ids

    legacy_ids = [
        _text_value(raw, "strategy", "sma_cross"),
        _text_value(raw, "secondary_strategy"),
        _text_value(raw, "tertiary_strategy"),
    ]
    unique_legacy_ids: list[str] = []
    for strategy_id in legacy_ids:
        if strategy_id and strategy_id not in unique_legacy_ids:
            unique_legacy_ids.append(strategy_id)
    return unique_legacy_ids


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
class FloatRange:
    start: float
    end: float
    step: float

    def values(self) -> list[float]:
        if self.step <= 0:
            raise ValueError("Il passo deve essere maggiore di zero.")
        if self.end < self.start:
            raise ValueError("Il valore finale deve essere maggiore o uguale a quello iniziale.")
        # La tolleranza evita di perdere l'ultimo valore per errori di
        # rappresentazione floating point (es. (0.3-0.1)/0.1 → 1.9999...).
        conteggio = int((self.end - self.start) / self.step + 1e-9) + 1
        return [round(self.start + indice * self.step, 10) for indice in range(conteggio)]

    def as_dict(self) -> dict[str, float]:
        return {"start": self.start, "end": self.end, "step": self.step}


@dataclass(frozen=True)
class SweepRequest:
    """Sweep parametrico generico.

    Conserva un mapping ``parameter_ranges`` ``{nome_parametro → range}``
    (``IntegerRange`` o ``FloatRange`` in base al tipo del parametro) invece di
    hardcodare fast/slow: questo permette di estendere lo sweep a strategie con
    altri nomi parametro (entry_period/exit_period, ecc.) e a qualsiasi numero
    di dimensioni nel grid search.

    Per retro-compatibilità ``fast_range`` e ``slow_range`` restano accessibili
    come proprietà che attingono al mapping.
    """

    symbol: str
    data_symbol: str
    start: str
    end: str
    interval: str = "1d"
    strategy: str = "sma_cross"
    initial_capital: float = 10_000.0
    fee_bps: float = 5.0
    parameter_ranges: dict[str, IntegerRange | FloatRange] = field(
        default_factory=lambda: {
            "fast": IntegerRange(10, 40, 10),
            "slow": IntegerRange(80, 200, 20),
        }
    )
    sort_by: str = "total_return_pct"
    # Gestione del rischio (propagata dal BacktestRequest)
    sl_pct: float | None = None
    tp_pct: float | None = None
    sizing_method: str = "full"
    sizing_param: float = 100.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SweepRequest":
        base_request = BacktestRequest.from_mapping(raw)
        if base_request.is_composite:
            raise FormValidationError(
                "Lo sweep multiplo richiede una sola regola attiva.",
                fields=("active_strategies",),
                display_field="active_strategies",
            )
        strategy_spec = STRATEGY_SPECS[base_request.strategy]
        if not strategy_spec.supports_sweep:
            raise FormValidationError(
                "La strategia selezionata non supporta il test multiplo dei parametri.",
                fields=("active_strategies",),
                display_field="active_strategies",
            )

        parameter_ranges = _parse_parameter_ranges(raw=raw, spec=strategy_spec)

        return cls(
            symbol=base_request.symbol,
            data_symbol=base_request.data_symbol,
            start=base_request.start,
            end=base_request.end,
            interval=base_request.interval,
            strategy=base_request.strategy,
            initial_capital=base_request.initial_capital,
            fee_bps=base_request.fee_bps,
            parameter_ranges=parameter_ranges,
            sort_by=_text_value(raw, "sort_by", "total_return_pct"),
            sl_pct=base_request.sl_pct,
            tp_pct=base_request.tp_pct,
            sizing_method=base_request.sizing_method,
            sizing_param=base_request.sizing_param,
        )

    @property
    def strategy_label(self) -> str:
        return STRATEGY_OPTIONS[self.strategy]["label"]

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(self.parameter_ranges.keys())

    @property
    def fast_range(self) -> IntegerRange | FloatRange:
        """Retro-compat: prima dimensione dello sweep."""
        return next(iter(self.parameter_ranges.values()))

    @property
    def slow_range(self) -> IntegerRange | FloatRange:
        """Retro-compat: seconda dimensione dello sweep (se presente)."""
        values = list(self.parameter_ranges.values())
        return values[1] if len(values) > 1 else values[0]

    def metadata(self) -> dict[str, object]:
        param_map = STRATEGY_SPECS[self.strategy].parameter_map()
        return {
            "symbol": self.symbol,
            "data_symbol": self.data_symbol,
            "start": self.start,
            "end": self.end,
            "interval": self.interval,
            "artifact_type": "sweep",
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "initial_capital": self.initial_capital,
            "fee_bps": self.fee_bps,
            "sl_pct": self.sl_pct,
            "tp_pct": self.tp_pct,
            "sizing_method": self.sizing_method,
            "sizing_param": self.sizing_param,
            "parameter_space": {name: rng.as_dict() for name, rng in self.parameter_ranges.items()},
            "parameter_labels": {
                name: (param_map[name].label if name in param_map else name)
                for name in self.parameter_ranges
            },
            "sort_by": self.sort_by,
        }

    def iter_parameter_combinations(self) -> list[dict[str, int | float]]:
        """Produce dict di parametri (chiave→valore) per ogni combinazione del grid."""
        import itertools

        names = list(self.parameter_ranges.keys())
        value_lists = [self.parameter_ranges[name].values() for name in names]
        return [dict(zip(names, combo)) for combo in itertools.product(*value_lists)]


def _parse_parameter_ranges(
    *,
    raw: Mapping[str, object],
    spec,
) -> dict[str, IntegerRange | FloatRange]:
    """Costruisce i range per il sweep leggendoli dal form.

    Convenzione campi form: ``<strategia>__<parametro>_start/_end/_step``
    (es. ``sma_cross__fast_start``, ``donchian_breakout__entry_period_start``),
    con fallback sulla forma globale ``<parametro>_start`` per retro-compat con
    form e preset salvati prima del namespacing. Campi assenti o vuoti ricadono
    sui default dello spec. Il tipo di range (``IntegerRange``/``FloatRange``)
    segue il ``value_type`` del parametro.
    """
    parameter_map = spec.parameter_map()

    parameter_ranges: dict[str, IntegerRange | FloatRange] = {}
    for name in _sweep_param_names_for(spec):
        param_spec = parameter_map.get(name)
        raw_start = _sweep_field_value(raw, spec.key, name, "start")
        raw_end = _sweep_field_value(raw, spec.key, name, "end")
        raw_step = _sweep_field_value(raw, spec.key, name, "step")
        if param_spec is not None and param_spec.value_type == "float":
            default = float(param_spec.default)
            default_step = float(param_spec.step) if param_spec.step else 1.0
            step = float(raw_step or default_step)
            parameter_ranges[name] = FloatRange(
                start=float(raw_start or default),
                end=float(raw_end or default * 2),
                step=step if step > 0 else default_step,
            )
        else:
            default = int(param_spec.default) if param_spec else 1
            step = int(float(raw_step or 1))
            parameter_ranges[name] = IntegerRange(
                start=int(float(raw_start or default)),
                end=int(float(raw_end or default * 2)),
                step=max(1, step),
            )
    return parameter_ranges


def _sweep_field_value(raw: Mapping[str, object], strategy_id: str, name: str, suffisso: str) -> str:
    """Legge un campo range sweep dal form.

    Prova prima la forma con namespace strategia (``<strategia>__<parametro>_<suffisso>``,
    stessa convenzione dei campi parametro), poi la forma globale
    ``<parametro>_<suffisso>`` per retro-compatibilità con form e preset vecchi.
    """
    namespaced = _text_value(raw, f"{strategy_id}__{name}_{suffisso}", "")
    if namespaced:
        return namespaced
    return _text_value(raw, f"{name}_{suffisso}", "")


def _sweep_param_names_for(spec) -> list[str]:
    """Restituisce i nomi dei parametri da sweep per una strategia.

    Logica: prende i primi due parametri dello spec (l'ordine di dichiarazione
    conta), massimo 2 dimensioni per non far esplodere il numero di combinazioni
    e per il layout del form a due box range.
    """
    return [parameter.name for parameter in spec.parameters[:2]]


def sweep_parameter_names(strategy_id: str) -> list[str]:
    """Nomi dei parametri coinvolti nello sweep per la strategia indicata.

    È la stessa convenzione usata dai campi form ``<parametro>_start/_end/_step``:
    templates, form e preset devono passare da qui per restare allineati.
    """
    return _sweep_param_names_for(STRATEGY_SPECS[strategy_id])
