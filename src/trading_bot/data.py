from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import yfinance as yf

from trading_bot.errors import FormValidationError

INTRADAY_LOOKBACK_DAYS = {
    "1m": 8,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "1h": 730,
    "90m": 60,
}

MARKET_SYMBOL_ALIASES = {
    "GOLD": "GC=F",
    "ORO": "GC=F",
    "XAU": "GC=F",
    "XAUUSD": "GC=F",
}


def latest_allowed_date_window(interval: str, now: datetime | None = None) -> tuple[str, str] | None:
    normalized_interval = interval.strip().lower()
    lookback_days = INTRADAY_LOOKBACK_DAYS.get(normalized_interval)
    if lookback_days is None:
        return None

    reference_now = now or datetime.now()
    oldest_allowed = reference_now - timedelta(days=lookback_days)
    start_date = oldest_allowed.date()
    if oldest_allowed.time() != time.min:
        start_date += timedelta(days=1)

    end_date = reference_now.date()
    if start_date >= end_date:
        start_date = end_date - timedelta(days=1)
    return start_date.isoformat(), end_date.isoformat()


def coerce_interval_date_window(
    *,
    start: str,
    end: str,
    interval: str,
    now: datetime | None = None,
) -> tuple[str, str, bool]:
    suggested_window = latest_allowed_date_window(interval=interval, now=now)
    if suggested_window is None:
        return start, end, False

    current_start = _parse_date_only(start)
    current_end = _parse_date_only(end)
    if current_start is None or current_end is None:
        return start, end, False

    suggested_start = date.fromisoformat(suggested_window[0])
    suggested_end = date.fromisoformat(suggested_window[1])
    needs_adjustment = current_start < suggested_start or current_end > suggested_end or current_end <= current_start
    if not needs_adjustment:
        return start, end, False

    return suggested_window[0], suggested_window[1], True


def download_price_data(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV data for a single symbol."""
    normalized_interval = interval.strip().lower()
    resolved_symbol = resolve_market_data_symbol(symbol)
    start_dt, end_dt = normalize_request_window(start=start, end=end)
    validate_interval_window(interval=normalized_interval, start=start_dt, end=end_dt)

    raw = yf.download(
        resolved_symbol,
        start=start_dt,
        end=end_dt,
        interval=normalized_interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise FormValidationError(
            build_no_data_message(symbol=symbol, interval=normalized_interval, start=start_dt, end=end_dt),
            fields=("symbol", "start", "end", "interval"),
            display_field="symbol",
        )

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


def resolve_market_data_symbol(symbol: str) -> str:
    normalized_symbol = str(symbol).strip().upper()
    return MARKET_SYMBOL_ALIASES.get(normalized_symbol, normalized_symbol)


def normalize_request_window(start: str, end: str) -> tuple[datetime, datetime]:
    start_dt = _parse_timestamp(start, is_end=False)
    end_dt = _parse_timestamp(end, is_end=True)
    if end_dt <= start_dt:
        raise FormValidationError(
            "La data finale deve essere successiva a quella iniziale.",
            fields=("start", "end"),
            display_field="end",
        )
    return start_dt, end_dt


def validate_interval_window(interval: str, start: datetime, end: datetime, now: datetime | None = None) -> None:
    lookback_days = INTRADAY_LOOKBACK_DAYS.get(interval)
    if lookback_days is None:
        return

    reference_now = now or datetime.now()
    oldest_allowed = reference_now - timedelta(days=lookback_days)
    if start < oldest_allowed:
        raise FormValidationError(
            (
                f"Per l'intervallo {interval} Yahoo Finance consente richieste solo negli ultimi {lookback_days} giorni. "
                f"Hai chiesto da {start.strftime('%Y-%m-%d %H:%M')} a {end.strftime('%Y-%m-%d %H:%M')}. "
                f"Usa una data iniziale dal {oldest_allowed.strftime('%Y-%m-%d %H:%M')} in poi."
            ),
            fields=("interval", "start", "end"),
            display_field="interval",
        )


def build_no_data_message(symbol: str, interval: str, start: datetime, end: datetime) -> str:
    lookback_days = INTRADAY_LOOKBACK_DAYS.get(interval)
    if lookback_days is None:
        return f"Nessun dato restituito per il simbolo '{symbol}'."

    return (
        f"Nessun dato restituito per il simbolo '{symbol}' su {interval}. "
        f"Su Yahoo Finance questo timeframe e' disponibile solo negli ultimi {lookback_days} giorni. "
        f"Intervallo richiesto: {start.strftime('%Y-%m-%d %H:%M')} -> {end.strftime('%Y-%m-%d %H:%M')}."
    )


def _parse_timestamp(raw: str, is_end: bool) -> datetime:
    value = str(raw).strip()
    if not value:
        raise ValueError("Inserisci data iniziale e finale.")

    parsed = datetime.fromisoformat(value)
    has_time = "T" in value or " " in value
    if not has_time and is_end:
        return parsed + timedelta(days=1)
    return parsed


def _parse_date_only(raw: str) -> date | None:
    value = str(raw).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
