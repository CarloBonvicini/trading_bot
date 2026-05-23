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


def donchian_breakout(data: pd.DataFrame, entry_period: int = 20, exit_period: int = 10) -> pd.Series:
    """Breakout sul canale di Donchian.

    Entra long quando il close supera il massimo degli ultimi `entry_period` giorni
    (nuovo massimo storico recente). Esce quando il close scende sotto il minimo
    degli ultimi `exit_period` giorni.
    """
    if entry_period <= 1 or exit_period <= 1:
        raise ValueError("I periodi Donchian devono essere maggiori di 1.")
    if exit_period >= entry_period:
        raise ValueError("L'exit period deve essere minore dell'entry period.")

    _require_columns(data, ("high", "low"))
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)

    # Canale calcolato sulle barre precedenti (shift 1) per evitare che il massimo/minimo
    # della barra corrente impedisca sempre alla condizione di scattare (high[t] >= close[t]).
    upper_channel = high.rolling(window=entry_period, min_periods=entry_period).max().shift(1)
    lower_channel = low.rolling(window=exit_period, min_periods=exit_period).min().shift(1)

    entry_condition = close >= upper_channel
    exit_condition = close <= lower_channel
    return _stateful_signal(entry_condition=entry_condition, exit_condition=exit_condition, index=data.index)


def obv_trend(data: pd.DataFrame, fast: int = 10, slow: int = 30) -> pd.Series:
    if fast <= 0 or slow <= 0:
        raise ValueError("Le finestre OBV devono essere positive.")
    if fast >= slow:
        raise ValueError("La finestra OBV veloce deve essere piu' piccola di quella lenta.")

    obv = on_balance_volume(data)
    fast_ma = obv.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ma = obv.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return (fast_ma > slow_ma).astype(float).rename("position")


def roc_momentum(data: pd.DataFrame, period: int = 10, threshold: float = 5.0) -> pd.Series:
    """Rate of Change (ROC): momentum puro.

    Entra long quando il ROC supera la soglia positiva (slancio al rialzo)
    ed esce quando il ROC torna sotto zero (momentum esaurito).
    """
    if period <= 0:
        raise ValueError("ROC period deve essere positivo.")
    if threshold <= 0:
        raise ValueError("La soglia ROC deve essere positiva.")

    close = data["close"].astype(float)
    prev_close = close.shift(period).replace(0.0, pd.NA)
    roc = ((close - prev_close) / prev_close) * 100.0
    roc = roc.fillna(0.0)
    return _stateful_signal(entry_condition=roc >= threshold, exit_condition=roc <= 0.0, index=data.index)


def keltner_reversion(data: pd.DataFrame, period: int = 20, multiplier: float = 2.0) -> pd.Series:
    """Keltner Channel Reversion: canale basato su EMA + ATR.

    Compra quando il prezzo scende sotto la banda inferiore (EMA - multiplier × ATR)
    e chiude quando risale alla media (EMA).
    """
    if period <= 1:
        raise ValueError("Il periodo Keltner deve essere maggiore di 1.")
    if multiplier <= 0:
        raise ValueError("Il moltiplicatore ATR deve essere positivo.")

    _require_columns(data, ("high", "low"))
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)

    middle = close.ewm(span=period, adjust=False, min_periods=period).mean()
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(span=period, adjust=False, min_periods=period).mean()
    lower_band = middle - multiplier * atr
    return _stateful_signal(entry_condition=close <= lower_band, exit_condition=close >= middle, index=data.index)


def money_flow_index(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index: RSI pesato per il volume."""
    if period <= 1:
        raise ValueError("MFI period deve essere maggiore di 1.")

    _require_columns(data, ("high", "low", "volume"))
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    volume = data["volume"].fillna(0.0).astype(float)

    typical_price = (high + low + close) / 3.0
    money_flow = typical_price * volume
    price_diff = typical_price.diff()

    positive_flow = money_flow.where(price_diff > 0, 0.0).rolling(window=period, min_periods=period).sum()
    negative_flow = money_flow.where(price_diff < 0, 0.0).rolling(window=period, min_periods=period).sum()
    money_ratio = positive_flow / negative_flow.replace(0.0, pd.NA)
    mfi = 100.0 - (100.0 / (1.0 + money_ratio))
    return mfi.fillna(50.0).rename("mfi")


def mfi_reversion(data: pd.DataFrame, period: int = 14, lower: float = 20.0, upper: float = 80.0) -> pd.Series:
    """MFI Mean Reversion: entra su ipervenduto MFI ed esce su ipercomprato."""
    if lower >= upper:
        raise ValueError("MFI lower deve essere piu' piccolo di upper.")

    mfi = money_flow_index(data, period=period)
    return _stateful_signal(entry_condition=mfi <= lower, exit_condition=mfi >= upper, index=data.index)


def parabolic_sar(data: pd.DataFrame, step: float = 0.02, max_step: float = 0.20) -> pd.Series:
    """Parabolic SAR: trend following con stop parabolico accelerato.

    Posizione long quando il prezzo e' sopra il SAR, flat quando e' sotto.
    L'acceleration factor parte da `step` e si incrementa di `step` ogni volta
    che si registra un nuovo estremo, fino a `max_step`.
    """
    if step <= 0:
        raise ValueError("Il parametro step deve essere positivo.")
    if max_step <= step:
        raise ValueError("Il parametro max_step deve essere maggiore di step.")

    _require_columns(data, ("high", "low"))
    high_vals = data["high"].astype(float).values
    low_vals = data["low"].astype(float).values
    n = len(high_vals)

    bullish = True
    af = step
    ep = float(high_vals[0])
    sar = float(low_vals[0])
    positions: list[float] = []

    for i in range(n):
        if i == 0:
            positions.append(1.0)
            continue

        if bullish:
            new_sar = sar + af * (ep - sar)
            # SAR non puo' essere sopra i minimi delle ultime due barre
            new_sar = min(new_sar, float(low_vals[i - 1]))
            if i >= 2:
                new_sar = min(new_sar, float(low_vals[i - 2]))
            sar = new_sar

            if float(low_vals[i]) < sar:
                # Inversione a ribassista
                bullish = False
                sar = ep
                ep = float(low_vals[i])
                af = step
                positions.append(0.0)
            else:
                if float(high_vals[i]) > ep:
                    ep = float(high_vals[i])
                    af = min(af + step, max_step)
                positions.append(1.0)
        else:
            new_sar = sar + af * (ep - sar)
            # SAR non puo' essere sotto i massimi delle ultime due barre
            new_sar = max(new_sar, float(high_vals[i - 1]))
            if i >= 2:
                new_sar = max(new_sar, float(high_vals[i - 2]))
            sar = new_sar

            if float(high_vals[i]) > sar:
                # Inversione a rialzista
                bullish = True
                sar = ep
                ep = float(high_vals[i])
                af = step
                positions.append(1.0)
            else:
                if float(low_vals[i]) < ep:
                    ep = float(low_vals[i])
                    af = min(af + step, max_step)
                positions.append(0.0)

    return pd.Series(positions, index=data.index, name="position", dtype=float)


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
        supports_sweep=True,
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
        supports_sweep=True,
    ),
    "donchian_breakout": StrategySpec(
        key="donchian_breakout",
        label="Donchian Breakout",
        description="Breakout sul canale di Donchian: compra su nuovo massimo, vende su nuovo minimo.",
        parameters=(
            StrategyParameter("entry_period", "Entry period", "int", 20, minimum=2, step=1),
            StrategyParameter("exit_period", "Exit period", "int", 10, minimum=2, step=1),
        ),
        supports_sweep=True,
    ),
    "roc_momentum": StrategySpec(
        key="roc_momentum",
        label="ROC Momentum",
        description="Momentum puro: entra quando il Rate of Change supera la soglia, esce quando si azzera.",
        parameters=(
            StrategyParameter("period", "ROC period", "int", 10, minimum=2, step=1),
            StrategyParameter("threshold", "Soglia (%)", "float", 5.0, minimum=0.1, step=0.5),
        ),
        supports_sweep=True,
    ),
    "keltner_reversion": StrategySpec(
        key="keltner_reversion",
        label="Keltner Reversion",
        description="Canale ATR-based: compra sotto la banda inferiore e chiude sul ritorno alla EMA.",
        parameters=(
            StrategyParameter("period", "Periodo", "int", 20, minimum=2, step=1),
            StrategyParameter("multiplier", "Moltiplicatore ATR", "float", 2.0, minimum=0.5, step=0.1),
        ),
    ),
    "mfi_reversion": StrategySpec(
        key="mfi_reversion",
        label="MFI Reversion",
        description="Money Flow Index (RSI pesato volume): entra su ipervenduto, esce su ipercomprato.",
        parameters=(
            StrategyParameter("period", "MFI period", "int", 14, minimum=2, step=1),
            StrategyParameter("lower", "MFI lower", "float", 20.0, minimum=1.0, maximum=99.0, step=0.5),
            StrategyParameter("upper", "MFI upper", "float", 80.0, minimum=1.0, maximum=99.0, step=0.5),
        ),
    ),
    "parabolic_sar": StrategySpec(
        key="parabolic_sar",
        label="Parabolic SAR",
        description="Stop parabolico accelerato: long sopra il SAR, flat quando il prezzo lo buca al ribasso.",
        parameters=(
            StrategyParameter("step", "Acceleration step", "float", 0.02, minimum=0.001, maximum=0.5, step=0.005),
            StrategyParameter("max_step", "Max acceleration", "float", 0.20, minimum=0.01, maximum=1.0, step=0.01),
        ),
        supports_sweep=True,
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
    "donchian_breakout": donchian_breakout,
    "roc_momentum": roc_momentum,
    "keltner_reversion": keltner_reversion,
    "mfi_reversion": mfi_reversion,
    "parabolic_sar": parabolic_sar,
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


# ── Registry vincoli ────────────────────────────────────────────────────────
# Ogni voce è un dict {strategy_id → list di (left, right, errore)} dove la
# regola impone ``parameters[left] < parameters[right]``. Aggiungere un vincolo
# nuovo significa estendere questo dict, senza toccare la funzione di
# validazione (open/closed principle, più scalabile).
_LESS_THAN_CONSTRAINTS: dict[str, list[tuple[str, str, str]]] = {
    "sma_cross":            [("fast", "slow", "Il parametro fast deve essere minore del parametro slow.")],
    "ema_cross":            [("fast", "slow", "Il parametro fast deve essere minore del parametro slow.")],
    "obv_trend":            [("fast", "slow", "Il parametro fast deve essere minore del parametro slow.")],
    "macd_trend":           [("fast", "slow", "MACD fast deve essere minore di MACD slow.")],
    "rsi_mean_reversion":   [("lower", "upper", "Il parametro lower deve essere minore del parametro upper.")],
    "stochastic_reversion": [("lower", "upper", "Il parametro lower deve essere minore del parametro upper.")],
    "cci_reversion":        [("lower", "upper", "Il parametro lower deve essere minore del parametro upper.")],
    "williams_r_reversion": [("lower", "upper", "Il parametro lower deve essere minore del parametro upper.")],
    "mfi_reversion":        [("lower", "upper", "Il parametro lower deve essere minore del parametro upper.")],
    "donchian_breakout":    [("exit_period", "entry_period", "Donchian exit period deve essere minore di entry period.")],
    "parabolic_sar":        [("step", "max_step", "Parabolic SAR max_step deve essere maggiore di step.")],
}


def validate_strategy_parameters(strategy_id: str, parameters: Mapping[str, int | float]) -> None:
    """Applica i vincoli relazionali dichiarati nel registry."""
    numeric = {key: float(value) for key, value in parameters.items()}
    for left, right, message in _LESS_THAN_CONSTRAINTS.get(strategy_id, ()):
        if left in numeric and right in numeric and numeric[left] >= numeric[right]:
            raise ValueError(message)


def build_strategy_signal(strategy_id: str, data: pd.DataFrame, parameters: Mapping[str, int | float]) -> pd.Series:
    if strategy_id not in STRATEGY_FUNCTIONS:
        raise ValueError(f"Strategia non supportata: {strategy_id}.")
    validate_strategy_parameters(strategy_id, parameters)
    return STRATEGY_FUNCTIONS[strategy_id](data, **parameters)


def _eval_expression(node: dict, signals_by_id: dict[str, "pd.Series"]) -> "pd.Series":
    """Valuta ricorsivamente un nodo dell'albero di espressione.

    Foglia: { strategies: [...], logic: "all"|"any" }
    Nodo composito: { op: "all"|"any", children: [...] }
    """
    import pandas as _pd  # import locale per evitare circolarità

    if not node or not isinstance(node, dict):
        if signals_by_id:
            idx = next(iter(signals_by_id.values())).index
        else:
            idx = _pd.RangeIndex(1)
        return _pd.Series(0.0, index=idx)

    if "strategies" in node:
        # Foglia: gruppo di strategie
        member_ids = [str(s) for s in (node.get("strategies") or []) if str(s) in signals_by_id]
        if not member_ids:
            idx = next(iter(signals_by_id.values())).index if signals_by_id else _pd.RangeIndex(1)
            return _pd.Series(0.0, index=idx)
        series = [signals_by_id[s] for s in member_ids]
        if len(series) == 1:
            return series[0]
        frame = _pd.concat(series, axis=1).fillna(0.0)
        if str(node.get("logic", "all")) == "any":
            return (frame.max(axis=1) > 0.0).astype(float)
        return (frame.min(axis=1) > 0.0).astype(float)

    if "children" in node:
        # Nodo composito: combina i figli
        children = [_eval_expression(c, signals_by_id) for c in (node["children"] or [])]
        if not children:
            return _pd.Series(0.0)
        if len(children) == 1:
            return children[0]
        frame = _pd.concat(children, axis=1).fillna(0.0)
        if str(node.get("op", "all")) == "any":
            return (frame.max(axis=1) > 0.0).astype(float)
        return (frame.min(axis=1) > 0.0).astype(float)

    return _pd.Series(0.0)


def build_combined_signal(
    data: pd.DataFrame,
    rules: list[tuple[str, Mapping[str, int | float]]],
    *,
    combination_mode: str = "all",
    groups: list[dict[str, object]] | None = None,
    expression: dict[str, object] | None = None,
) -> pd.Series:
    """Costruisce il segnale combinato da più regole.

    Se ``groups`` è fornito (lista di ≥2 gruppi), il segnale è calcolato in due livelli:
    1. Ogni gruppo combina le sue strategie con la logica interna del gruppo.
    2. I segnali dei gruppi vengono combinati con ``combination_mode`` (AND/OR top-level).

    Se ``groups`` è assente o ha un solo gruppo, si usa la logica piatta ``combination_mode``.
    """
    if not rules:
        raise ValueError("Serve almeno una regola per costruire il segnale.")

    # Costruisce i segnali per ogni strategia
    signals_by_id: dict[str, pd.Series] = {}
    for strategy_id, parameters in rules:
        signals_by_id[strategy_id] = (
            build_strategy_signal(strategy_id=strategy_id, data=data, parameters=parameters)
            .fillna(0.0)
            .clip(lower=0.0, upper=1.0)
        )

    # Albero di espressione con precedenza esplicita (parentesi)
    if expression and isinstance(expression, dict):
        return _eval_expression(expression, signals_by_id).rename("position")

    # Logica a gruppi (≥2 gruppi con strategie diverse)
    if groups and len(groups) > 1:
        group_signals: list[tuple[pd.Series, str]] = []  # (segnale, op_before)
        for group in groups:
            member_ids = [str(s) for s in (group.get("strategies") or []) if str(s) in signals_by_id]
            if not member_ids:
                continue
            member_series = [signals_by_id[s] for s in member_ids]
            if len(member_series) == 1:
                gsig = member_series[0]
            else:
                frame = pd.concat(member_series, axis=1).fillna(0.0)
                if str(group.get("logic", "all")) == "any":
                    gsig = (frame.max(axis=1) > 0.0).astype(float)
                else:
                    gsig = (frame.min(axis=1) > 0.0).astype(float)
            # op_before: operatore con cui questo gruppo si combina al precedente
            op_before = str(group.get("op_before", combination_mode))
            group_signals.append((gsig, op_before))

        if not group_signals:
            return pd.Series(0.0, index=data.index, name="position")
        if len(group_signals) == 1:
            return group_signals[0][0].rename("position")

        # Valutazione sinistra→destra con operatori per-coppia
        result = group_signals[0][0].fillna(0.0)
        for gsig, op in group_signals[1:]:
            right = gsig.fillna(0.0)
            if op == "any":
                result = (result + right).clip(upper=1.0)
            else:
                result = (result * right)
        return (result > 0.0).astype(float).rename("position")

    # Logica piatta (comportamento originale)
    signals = list(signals_by_id.values())
    if len(signals) == 1:
        return signals[0].rename("position")

    signal_frame = pd.concat(signals, axis=1).fillna(0.0)
    if combination_mode == "all":
        combined = (signal_frame.min(axis=1) > 0.0).astype(float)
    elif combination_mode == "any":
        combined = (signal_frame.max(axis=1) > 0.0).astype(float)
    else:
        raise ValueError(f"Modalita' combinazione non supportata: {combination_mode}.")

    return combined.rename("position")


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
