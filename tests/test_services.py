from __future__ import annotations

from pathlib import Path

import pandas as pd

from trading_bot.services import IntegerRange, SweepRequest, run_sma_sweep_request


def test_run_sma_sweep_request_generates_all_valid_combinations(monkeypatch, tmp_path: Path) -> None:
    data = pd.DataFrame(
        {
            "close": [100, 102, 101, 103, 105, 104, 108, 110, 109, 113, 116, 118],
        },
        index=pd.date_range("2024-01-01", periods=12, freq="D"),
    )
    monkeypatch.setattr("trading_bot.services.download_price_data", lambda **_: data)

    sweep_request = SweepRequest(
        symbol="SPY",
        start="2024-01-01",
        end="2024-01-12",
        interval="1d",
        fast_range=IntegerRange(2, 4, 1),
        slow_range=IntegerRange(4, 6, 1),
        fee_bps=0.0,
    )

    completed = run_sma_sweep_request(sweep_request=sweep_request, output_dir=tmp_path)

    assert completed.summary["run_count"] == 8
    assert completed.summary["invalid_combinations"] == 1
    assert completed.results["rank"].tolist() == list(range(1, 9))
    assert (tmp_path / completed.sweep_dir.name / "results.csv").exists()
    assert (tmp_path / completed.sweep_dir.name / "best_summary.json").exists()
