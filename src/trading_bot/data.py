from __future__ import annotations

import pandas as pd
import yfinance as yf


def download_price_data(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV data for a single symbol."""
    raw = yf.download(
        symbol,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise ValueError(f"No data returned for symbol '{symbol}'.")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    data = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    keep = [column for column in ["open", "high", "low", "close", "volume"] if column in data.columns]
    data = data[keep].dropna(subset=["close"]).copy()
    data.index = pd.to_datetime(data.index).tz_localize(None)
    data.sort_index(inplace=True)
    return data

