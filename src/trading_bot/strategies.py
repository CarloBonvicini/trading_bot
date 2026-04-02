from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class StrategyParameter:
    name: str
    label: str
    value_type: str
    default: int | float
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None

    def parse(self, raw: object | None) -> int | float:
        value = self.default if raw in (None, "") else raw
        parsed = int(float(value)) if self.value_type == "int" else float(value)
        if self.minimum is not None and parsed < self.minimum:
            raise ValueError(f"{self.label}: valore minimo {self.minimum}.")
        if self.maximum is not None and parsed > self.maximum:
            raise ValueError(f"{self.label}: valore massimo {self.maximum}.")
        return parsed

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StrategySpec:
    key: str
    label: str
    description: str
    parameters: tuple[StrategyParameter, ...]
    supports_sweep: bool = False

    def defaults(self) -> dict[str, int | float]:
        return {parameter.name: parameter.default for parameter in self.parameters}

    def parameter_map(self) -> dict[str, StrategyParameter]:
        return {parameter.name: parameter for parameter in self.parameters}

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "supports_sweep": self.supports_sweep,
            "parameters": [
                {
                    **parameter.as_dict(),
                    "field_name": strategy_field_name(self.key, parameter.name),
                }
                for parameter in self.parameters
            ],
        }


def strategy_field_name(strategy_id: str, parameter_name: str) -> str:
    return f"{strategy_id}__{parameter_name}"


def sma_crossover(data: pd.DataFrame, fast: int = 20, slow: int = 100) -> pd.Series:
    if fast <= 0 or slow <= 0:
        raise ValueError("Le finestre delle medie mobili devono essere positive.")
    if fast >= slow:
        raise ValueError("La media mobile veloce deve essere piu' piccola di quella lenta.")

    close = data["close"].astype(float)
    fast_ma = close.rolling(window=fast, min_periods=fast).mean()
    slow_ma = close.rolling(window=slow, min_periods=slow).mean()
    return (fast_ma > slow_ma).astype(float).rename("position")


def ema_crossover(data: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    if fast <= 0 or slow <= 0:
        raise ValueError("Le finestre EMA devono essere positive.")
    if fast >= slow:
        raise ValueError("La EMA veloce deve essere piu' piccola di quella lenta.")

    close = data["close"].astype(float)
    fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return (fast_ema > slow_ema).astype(float).rename("position")


def relative_strength_index(close: pd.Series, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("RSI period deve essere positivo.")

    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0).rename("rsi")


def rsi_mean_reversion(
    data: pd.DataFrame,
    period: int = 14,
    lower: float = 30.0,
    upper: float = 55.0,
) -> pd.Series:
    if lower >= upper:
        raise ValueError("RSI lower deve essere piu' piccolo di RSI upper.")

    rsi = relative_strength_index(data["close"].astype(float), period=period)
    return _stateful_signal(entry_condition=rsi <= lower, exit_condition=rsi >= upper, index=data.index)


def macd_trend(data: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("I periodi MACD devono essere positivi.")
    if fast >= slow:
        raise ValueError("Nel MACD il periodo veloce deve essere minore di quello lento.")

    close = data["close"].astype(float)
    fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return (macd_line > signal_line).astype(float).rename("position")


def bollinger_reversion(data: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    if period <= 1:
        raise ValueError("Il periodo Bollinger deve essere maggiore di 1.")
    if std_dev <= 0:
        raise ValueError("La deviazione standard Bollinger deve essere positiva.")

    close = data["close"].astype(float)
    basis = close.rolling(window=period, min_periods=period).mean()
    deviation = close.rolling(window=period, min_periods=period).std(ddof=0)
    lower_band = basis - (deviation * std_dev)
    return _stateful_signal(entry_condition=close <= lower_band, exit_condition=close >= basis, index=data.index)


def stochastic_reversion(
    data: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3,
    lower: float = 20.0,
    upper: float = 80.0,
) -> pd.Series:
    if lower >= upper:
        raise ValueError("Stochastic lower deve essere piu' piccolo di upper.")
    if min(k_period, d_period, smooth) <= 0:
        raise ValueError("I periodi Stochastic devono essere positivi.")

    _require_columns(data, ("high", "low"))
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    denominator = (highest_high - lowest_low).replace(0.0, pd.NA)
    raw_k = ((close - lowest_low) / denominator) * 100
    slow_k = raw_k.rolling(window=smooth, min_periods=smooth).mean()
    slow_d = slow_k.rolling(window=d_period, min_periods=d_period).mean()
    entry = (slow_k <= lower) & (slow_k > slow_d)
    exit = (slow_k >= upper) & (slow_k < slow_d)
    return _stateful_signal(entry_condition=entry, exit_condition=exit, index=data.index)


def commodity_channel_index(data: pd.DataFrame, period: int = 20) -> pd.Series:
    if period <= 1:
        raise ValueError("CCI period deve essere maggiore di 1.")

    _require_columns(data, ("high", "low"))
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    typical_price = (high + low + close) / 3.0
    basis = typical_price.rolling(window=period, min_periods=period).mean()
    mean_deviation = (typical_price - basis).abs().rolling(window=period, min_periods=period).mean()
    cci = (typical_price - basis) / (0.015 * mean_deviation.replace(0.0, pd.NA))
    return cci.fillna(0.0).rename("cci")


def cci_reversion(data: pd.DataFrame, period: int = 20, lower: float = -100.0, upper: float = 100.0) -> pd.Series:
    if lower >= upper:
        raise ValueError("CCI lower deve essere piu' piccolo di upper.")

    cci = commodity_channel_index(data, period=period)
    return _stateful_signal(entry_condition=cci <= lower, exit_condition=cci >= upper, index=data.index)


def williams_r_indicator(data: pd.DataFrame, period: int = 14) -> pd.Series:
    if period <= 1:
        raise ValueError("Williams %R period deve essere maggiore di 1.")

    _require_columns(data, ("high", "low"))
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    highest_high = high.rolling(window=period, min_periods=period).max()
    lowest_low = low.rolling(window=period, min_periods=period).min()
    denominator = (highest_high - lowest_low).replace(0.0, pd.NA)
    williams_r = -100 * ((highest_high - close) / denominator)
    return williams_r.fillna(-50.0).rename("williams_r")


def williams_r_reversion(data: pd.DataFrame, period: int = 14, lower: float = -80.0, upper: float = -20.0) -> pd.Series:
    if lower >= upper:
        raise ValueError("Williams %R lower deve essere piu' piccolo di upper.")

    williams_r = williams_r_indicator(data, period=period)
    return _stateful_signal(entry_condition=williams_r <= lower, exit_condition=williams_r >= upper, index=data.index)


def adx_components(data: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    if period <= 1:
        raise ValueError("ADX period deve essere maggiore di 1.")

    _require_columns(data, ("high", "low"))
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0.0, pd.NA)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0.0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, pd.NA)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"adx": adx.fillna(0.0), "plus_di": plus_di.fillna(0.0), "minus_di": minus_di.fillna(0.0)})


def adx_trend(data: pd.DataFrame, period: int = 14, threshold: float = 25.0) -> pd.Series:
    components = adx_components(data, period=period)
    entry = (components["adx"] >= threshold) & (components["plus_di"] > components["minus_di"])
    exit = (components["adx"] < threshold) | (components["plus_di"] <= components["minus_di"])
    return _stateful_signal(entry_condition=entry, exit_condition=exit, index=data.index)


def on_balance_volume(data: pd.DataFrame) -> pd.Series:
    _require_columns(data, ("volume",))
    close = data["close"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)
    direction = close.diff().fillna(0.0).apply(lambda value: 1.0 if value > 0 else (-1.0 if value < 0 else 0.0))
    return (direction * volume).cumsum().rename("obv")


def obv_trend(data: pd.DataFrame, fast: int = 10, slow: int = 30) -> pd.Series:
    if fast <= 0 or slow <= 0:
        raise ValueError("Le finestre OBV devono essere positive.")
    if fast >= slow:
        raise ValueError("La finestra OBV veloce deve essere piu' piccola di quella lenta.")

    obv = on_balance_volume(data)
    fast_ma = obv.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ma = obv.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return (fast_ma > slow_ma).astype(float).rename("position")


STRATEGY_SPECS: dict[str, StrategySpec] = {
    "sma_cross": StrategySpec(
        key="sma_cross",
        label="SMA Crossover",
        description="Trend following classico su due medie mobili semplici.",
        parameters=(
            StrategyParameter("fast", "Fast SMA", "int", 20, minimum=1, step=1),
            StrategyParameter("slow", "Slow SMA", "int", 100, minimum=2, step=1),
        ),
        supports_sweep=True,
    ),
    "ema_cross": StrategySpec(
        key="ema_cross",
        label="EMA Crossover",
        description="Versione piu' reattiva del crossover usando medie esponenziali.",
        parameters=(
            StrategyParameter("fast", "Fast EMA", "int", 12, minimum=1, step=1),
            StrategyParameter("slow", "Slow EMA", "int", 26, minimum=2, step=1),
        ),
    ),
    "rsi_mean_reversion": StrategySpec(
        key="rsi_mean_reversion",
        label="RSI Mean Reversion",
        description="Entra su ipervenduto RSI ed esce quando il momentum rientra.",
        parameters=(
            StrategyParameter("period", "RSI period", "int", 14, minimum=2, step=1),
            StrategyParameter("lower", "RSI lower", "float", 30.0, minimum=1.0, maximum=99.0, step=0.1),
            StrategyParameter("upper", "RSI upper", "float", 55.0, minimum=1.0, maximum=99.0, step=0.1),
        ),
    ),
    "macd_trend": StrategySpec(
        key="macd_trend",
        label="MACD Trend",
        description="Segue il trend quando la linea MACD supera la signal line.",
        parameters=(
            StrategyParameter("fast", "MACD fast", "int", 12, minimum=1, step=1),
            StrategyParameter("slow", "MACD slow", "int", 26, minimum=2, step=1),
            StrategyParameter("signal", "MACD signal", "int", 9, minimum=1, step=1),
        ),
    ),
    "bollinger_reversion": StrategySpec(
        key="bollinger_reversion",
        label="Bollinger Reversion",
        description="Compra sotto la banda inferiore e chiude sul ritorno verso la media.",
        parameters=(
            StrategyParameter("period", "Bollinger period", "int", 20, minimum=2, step=1),
            StrategyParameter("std_dev", "Std dev", "float", 2.0, minimum=0.5, step=0.1),
        ),
    ),
    "stochastic_reversion": StrategySpec(
        key="stochastic_reversion",
        label="Stochastic Reversion",
        description="Entra su ipervenduto Stochastic con conferma K/D.",
        parameters=(
            StrategyParameter("k_period", "K period", "int", 14, minimum=2, step=1),
            StrategyParameter("d_period", "D period", "int", 3, minimum=1, step=1),
            StrategyParameter("smooth", "Smooth", "int", 3, minimum=1, step=1),
            StrategyParameter("lower", "Stoch lower", "float", 20.0, minimum=1.0, maximum=99.0, step=0.1),
            StrategyParameter("upper", "Stoch upper", "float", 80.0, minimum=1.0, maximum=99.0, step=0.1),
        ),
    ),
    "cci_reversion": StrategySpec(
        key="cci_reversion",
        label="CCI Reversion",
        description="Compra quando il CCI entra in zona estrema negativa e chiude sul rientro.",
        parameters=(
            StrategyParameter("period", "CCI period", "int", 20, minimum=2, step=1),
            StrategyParameter("lower", "CCI lower", "float", -100.0, step=1.0),
            StrategyParameter("upper", "CCI upper", "float", 100.0, step=1.0),
        ),
    ),
    "williams_r_reversion": StrategySpec(
        key="williams_r_reversion",
        label="Williams %R Reversion",
        description="Compra su eccesso di debolezza Williams %R e chiude sul recupero.",
        parameters=(
            StrategyParameter("period", "Williams %R period", "int", 14, minimum=2, step=1),
            StrategyParameter("lower", "Williams %R lower", "float", -80.0, minimum=-100.0, maximum=0.0, step=1.0),
            StrategyParameter("upper", "Williams %R upper", "float", -20.0, minimum=-100.0, maximum=0.0, step=1.0),
        ),
    ),
    "adx_trend": StrategySpec(
        key="adx_trend",
        label="ADX Trend Filter",
        description="Va long solo quando il trend e' forte e +DI domina -DI.",
        parameters=(
            StrategyParameter("period", "ADX period", "int", 14, minimum=2, step=1),
            StrategyParameter("threshold", "ADX threshold", "float", 25.0, minimum=1.0, maximum=100.0, step=0.5),
        ),
    ),
    "obv_trend": StrategySpec(
        key="obv_trend",
        label="OBV Trend",
        description="Segue il flusso volume-prezzo con crossover tra due medie di OBV.",
        parameters=(
            StrategyParameter("fast", "Fast OBV", "int", 10, minimum=1, step=1),
            StrategyParameter("slow", "Slow OBV", "int", 30, minimum=2, step=1),
        ),
    ),
}


STRATEGY_FUNCTIONS = {
    "sma_cross": sma_crossover,
    "ema_cross": ema_crossover,
    "rsi_mean_reversion": rsi_mean_reversion,
    "macd_trend": macd_trend,
    "bollinger_reversion": bollinger_reversion,
    "stochastic_reversion": stochastic_reversion,
    "cci_reversion": cci_reversion,
    "williams_r_reversion": williams_r_reversion,
    "adx_trend": adx_trend,
    "obv_trend": obv_trend,
}


def strategy_options() -> dict[str, dict[str, object]]:
    return {key: spec.as_dict() for key, spec in STRATEGY_SPECS.items()}


def default_parameter_values() -> dict[str, int | float]:
    defaults: dict[str, int | float] = {}
    for spec in STRATEGY_SPECS.values():
        defaults.update(
            {
                strategy_field_name(spec.key, parameter.name): parameter.default
                for parameter in spec.parameters
            }
        )
    return defaults


def parse_strategy_parameters(strategy_id: str, raw: Mapping[str, object]) -> dict[str, int | float]:
    spec = STRATEGY_SPECS[strategy_id]
    parameters: dict[str, int | float] = {}
    for parameter in spec.parameters:
        parameters[parameter.name] = parameter.parse(
            raw.get(strategy_field_name(strategy_id, parameter.name), raw.get(parameter.name))
        )
    validate_strategy_parameters(strategy_id, parameters)
    return parameters


def validate_strategy_parameters(strategy_id: str, parameters: Mapping[str, int | float]) -> None:
    numeric = {key: float(value) for key, value in parameters.items()}
    if strategy_id in {"sma_cross", "ema_cross", "obv_trend"} and numeric["fast"] >= numeric["slow"]:
        raise ValueError("Il parametro fast deve essere minore del parametro slow.")
    if strategy_id == "macd_trend" and numeric["fast"] >= numeric["slow"]:
        raise ValueError("MACD fast deve essere minore di MACD slow.")
    if strategy_id in {"rsi_mean_reversion", "stochastic_reversion", "cci_reversion", "williams_r_reversion"} and numeric["lower"] >= numeric["upper"]:
        raise ValueError("Il parametro lower deve essere minore del parametro upper.")


def build_strategy_signal(strategy_id: str, data: pd.DataFrame, parameters: Mapping[str, int | float]) -> pd.Series:
    if strategy_id not in STRATEGY_FUNCTIONS:
        raise ValueError(f"Strategia non supportata: {strategy_id}.")
    validate_strategy_parameters(strategy_id, parameters)
    return STRATEGY_FUNCTIONS[strategy_id](data, **parameters)


def _require_columns(data: pd.DataFrame, required_columns: tuple[str, ...]) -> None:
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(f"Dati mancanti per la strategia: servono le colonne {', '.join(missing)}.")


def _stateful_signal(entry_condition: pd.Series, exit_condition: pd.Series, index: pd.Index) -> pd.Series:
    state = 0.0
    positions: list[float] = []

    for entry, exit_ in zip(entry_condition.fillna(False), exit_condition.fillna(False), strict=False):
        if state == 0.0 and bool(entry):
            state = 1.0
        elif state == 1.0 and bool(exit_):
            state = 0.0
        positions.append(state)

    return pd.Series(positions, index=index, name="position", dtype=float)
