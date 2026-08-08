from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from trading_bot.data import (
    CACHE_TTL_CHIUSA,
    clear_data_cache,
    download_price_data,
    normalize_request_window,
    validate_interval_window,
)
from trading_bot.errors import FormValidationError


def test_normalize_request_window_makes_date_end_inclusive() -> None:
    start, end = normalize_request_window("2026-04-01", "2026-04-03")

    assert start == datetime(2026, 4, 1, 0, 0)
    assert end == datetime(2026, 4, 4, 0, 0)


def test_validate_interval_window_rejects_old_intraday_requests() -> None:
    with pytest.raises(FormValidationError) as exc_info:
        validate_interval_window(
            interval="1h",
            start=datetime(2023, 1, 1, 0, 0),
            end=datetime(2023, 1, 10, 0, 0),
            now=datetime(2026, 4, 3, 12, 0),
        )

    message = str(exc_info.value)
    assert "ultimi 730 giorni" in message
    assert "2023-01-01 00:00" in message
    assert exc_info.value.field_names == ("interval", "start", "end")
    assert exc_info.value.display_field == "interval"


# ── Cache su disco degli scaricamenti ────────────────────────────────────────

def _finto_yfinance(monkeypatch, chiamate: list) -> pd.DataFrame:
    """Sostituisce yfinance con una sorgente finta che registra le chiamate."""
    grezzo = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.2, 11.2, 12.2],
            "Volume": [1000, 1100, 1200],
        },
        index=pd.date_range("2024-01-02", periods=3, freq="D"),
    )

    def _download(*args, **kwargs):
        chiamate.append(kwargs.get("interval"))
        return grezzo.copy()

    monkeypatch.setattr("trading_bot.data.yf.download", _download)
    return grezzo


def test_download_usa_la_cache_alla_seconda_chiamata(monkeypatch, tmp_path) -> None:
    chiamate: list = []
    _finto_yfinance(monkeypatch, chiamate)
    argomenti = dict(
        symbol="AAA", start="2024-01-01", end="2024-01-05", interval="1d", cache_dir=tmp_path
    )

    primo = download_price_data(**argomenti)
    secondo = download_price_data(**argomenti)

    assert len(chiamate) == 1  # la seconda volta non si scarica niente
    pd.testing.assert_frame_equal(primo, secondo, check_freq=False)
    assert list(tmp_path.glob("*.csv"))


def test_cache_distingue_finestre_e_timeframe_diversi(monkeypatch, tmp_path) -> None:
    chiamate: list = []
    _finto_yfinance(monkeypatch, chiamate)

    download_price_data(symbol="AAA", start="2024-01-01", end="2024-01-05",
                        interval="1d", cache_dir=tmp_path)
    download_price_data(symbol="AAA", start="2024-01-01", end="2024-02-05",
                        interval="1d", cache_dir=tmp_path)
    download_price_data(symbol="BBB", start="2024-01-01", end="2024-01-05",
                        interval="1d", cache_dir=tmp_path)

    assert len(chiamate) == 3


def test_cache_scaduta_viene_riscaricata(monkeypatch, tmp_path) -> None:
    import os
    import time

    chiamate: list = []
    _finto_yfinance(monkeypatch, chiamate)
    argomenti = dict(
        symbol="AAA", start="2024-01-01", end="2024-01-05", interval="1d", cache_dir=tmp_path
    )

    download_price_data(**argomenti)
    # Invecchia il file oltre la scadenza dei dati storici.
    file_cache = next(iter(tmp_path.glob("*.csv")))
    vecchio = time.time() - (CACHE_TTL_CHIUSA.total_seconds() + 3600)
    os.utime(file_cache, (vecchio, vecchio))

    download_price_data(**argomenti)

    assert len(chiamate) == 2


def test_cache_disattivabile(monkeypatch, tmp_path) -> None:
    chiamate: list = []
    _finto_yfinance(monkeypatch, chiamate)

    for _ in range(2):
        download_price_data(symbol="AAA", start="2024-01-01", end="2024-01-05",
                            interval="1d", use_cache=False, cache_dir=tmp_path)

    assert len(chiamate) == 2
    assert not list(tmp_path.glob("*.csv"))


def test_clear_data_cache_svuota_la_cartella(monkeypatch, tmp_path) -> None:
    chiamate: list = []
    _finto_yfinance(monkeypatch, chiamate)
    download_price_data(symbol="AAA", start="2024-01-01", end="2024-01-05",
                        interval="1d", cache_dir=tmp_path)

    assert clear_data_cache(tmp_path) == 1
    assert not list(tmp_path.glob("*.csv"))
