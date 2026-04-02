from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trading_bot.services import BacktestRequest
from trading_bot.web import create_app


def create_report_fixture(report_dir: Path) -> None:
    report_dir.mkdir(parents=True)
    (report_dir / "summary.json").write_text(
        json.dumps(
            {
                "initial_capital": 10000.0,
                "final_equity": 12000.0,
                "total_return_pct": 20.0,
                "annual_return_pct": 9.5,
                "annual_volatility_pct": 12.0,
                "sharpe_ratio": 0.91,
                "max_drawdown_pct": -8.5,
                "trade_count": 4,
                "exposure_pct": 45.0,
                "benchmark_return_pct": 17.0,
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "metadata.json").write_text(
        json.dumps(
            {
                "symbol": "SPY",
                "strategy": "sma_cross",
                "strategy_label": "SMA Crossover",
                "start": "2020-01-01",
                "end": "2024-12-31",
                "interval": "1d",
                "fee_bps": 5.0,
                "created_at": "2026-04-03T09:00:00",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "equity": [10000.0, 10100.0],
            "benchmark_equity": [10000.0, 10080.0],
            "drawdown": [0.0, -0.5],
        }
    ).to_csv(report_dir / "equity_curve.csv", index=False)
    pd.DataFrame(
        {
            "entry_date": ["2024-01-01"],
            "entry_price": [100.0],
            "exit_date": ["2024-01-05"],
            "exit_price": [104.0],
            "pnl_pct": [4.0],
            "holding_days": [4],
        }
    ).to_csv(report_dir / "trades.csv", index=False)


def test_index_lists_existing_reports(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nuovo backtest" in body
    assert "SPY" in body


def test_create_backtest_redirects_to_report(monkeypatch, tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    def fake_run(backtest_request: BacktestRequest, output_dir: Path):
        report_dir = output_dir / "SPY-sma_cross-20260403-100000"
        create_report_fixture(report_dir)

        class Completed:
            def __init__(self) -> None:
                self.report_dir = report_dir

        return Completed()

    monkeypatch.setattr("trading_bot.web.run_backtest_request", fake_run)
    client = app.test_client()
    response = client.post(
        "/backtests",
        data={
            "symbol": "SPY",
            "start": "2020-01-01",
            "end": "2024-12-31",
            "interval": "1d",
            "strategy": "sma_cross",
            "initial_capital": "10000",
            "fee_bps": "5",
            "fast": "20",
            "slow": "100",
            "rsi_period": "14",
            "rsi_lower": "30",
            "rsi_upper": "55",
        },
    )

    assert response.status_code == 302
    assert "/reports/SPY-sma_cross-20260403-100000" in response.headers["Location"]


def test_report_detail_renders_chart_and_trade_table(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Strategia vs benchmark" in body
    assert "Prime 20 operazioni" in body
