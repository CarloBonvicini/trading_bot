from __future__ import annotations

import pandas as pd


def sma_crossover(data: pd.DataFrame, fast: int = 20, slow: int = 100) -> pd.Series:
    """Long when the fast moving average is above the slow one."""
    if fast <= 0 or slow <= 0:
        raise ValueError("Moving average windows must be positive.")
    if fast >= slow:
        raise ValueError("The fast window must be smaller than the slow window.")

    close = data["close"].astype(float)
    fast_ma = close.rolling(window=fast, min_periods=fast).mean()
    slow_ma = close.rolling(window=slow, min_periods=slow).mean()
    return (fast_ma > slow_ma).astype(float).rename("position")


def relative_strength_index(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using exponential moving averages."""
    if period <= 0:
        raise ValueError("RSI period must be positive.")

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
    """Enter when RSI is oversold and exit when it normalizes."""
    if lower >= upper:
        raise ValueError("The lower RSI threshold must be smaller than the upper threshold.")

    rsi = relative_strength_index(data["close"].astype(float), period=period)
    state = 0.0
    positions: list[float] = []

    for value in rsi:
        if state == 0.0 and value <= lower:
            state = 1.0
        elif state == 1.0 and value >= upper:
            state = 0.0
        positions.append(state)

    return pd.Series(positions, index=data.index, name="position", dtype=float)

