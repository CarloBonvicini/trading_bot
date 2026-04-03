from __future__ import annotations

from datetime import datetime

import pytest

from trading_bot.data import normalize_request_window, validate_interval_window


def test_normalize_request_window_makes_date_end_inclusive() -> None:
    start, end = normalize_request_window("2026-04-01", "2026-04-03")

    assert start == datetime(2026, 4, 1, 0, 0)
    assert end == datetime(2026, 4, 4, 0, 0)


def test_validate_interval_window_rejects_old_intraday_requests() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_interval_window(
            interval="1h",
            start=datetime(2023, 1, 1, 0, 0),
            end=datetime(2023, 1, 10, 0, 0),
            now=datetime(2026, 4, 3, 12, 0),
        )

    message = str(exc_info.value)
    assert "ultimi 730 giorni" in message
    assert "2023-01-01 00:00" in message
