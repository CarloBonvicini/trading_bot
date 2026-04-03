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
                "gross_final_equity": 12040.0,
                "benchmark_final_equity": 11700.0,
                "total_return_pct": 20.0,
                "excess_return_pct": 3.0,
                "annual_return_pct": 9.5,
                "annual_volatility_pct": 12.0,
                "sharpe_ratio": 0.91,
                "max_drawdown_pct": -8.5,
                "trade_count": 4,
                "exposure_pct": 45.0,
                "benchmark_return_pct": 17.0,
                "fees_paid": 32.5,
                "fees_paid_pct_initial_capital": 0.33,
                "fee_drag_equity": 40.0,
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


def create_sweep_fixture(sweep_dir: Path) -> None:
    sweep_dir.mkdir(parents=True)
    (sweep_dir / "summary.json").write_text(
        json.dumps(
            {
                "artifact_type": "sweep",
                "run_count": 6,
                "invalid_combinations": 2,
                "sort_by": "total_return_pct",
                "best_fast": 20,
                "best_slow": 100,
                "best_total_return_pct": 24.4,
                "best_sharpe_ratio": 1.12,
                "best_max_drawdown_pct": -9.2,
                "best_final_equity": 12440.0,
                "best_benchmark_return_pct": 17.0,
                "best_excess_return_pct": 7.4,
                "best_fees_paid": 41.8,
            }
        ),
        encoding="utf-8",
    )
    (sweep_dir / "best_summary.json").write_text(
        json.dumps(
            {
                "initial_capital": 10000.0,
                "final_equity": 12440.0,
                "gross_final_equity": 12490.0,
                "benchmark_final_equity": 11700.0,
                "total_return_pct": 24.4,
                "excess_return_pct": 7.4,
                "annual_return_pct": 11.0,
                "annual_volatility_pct": 10.2,
                "sharpe_ratio": 1.12,
                "max_drawdown_pct": -9.2,
                "trade_count": 5,
                "exposure_pct": 48.0,
                "benchmark_return_pct": 17.0,
                "fees_paid": 41.8,
                "fees_paid_pct_initial_capital": 0.42,
                "fee_drag_equity": 50.0,
            }
        ),
        encoding="utf-8",
    )
    (sweep_dir / "metadata.json").write_text(
        json.dumps(
            {
                "artifact_type": "sweep",
                "symbol": "SPY",
                "strategy": "sma_cross",
                "strategy_label": "SMA Crossover",
                "start": "2020-01-01",
                "end": "2024-12-31",
                "interval": "1d",
                "fee_bps": 5.0,
                "parameter_space": {
                    "fast": {"start": 10, "end": 30, "step": 10},
                    "slow": {"start": 80, "end": 120, "step": 20},
                },
                "created_at": "2026-04-03T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "rank": [1, 2],
            "fast": [20, 10],
            "slow": [100, 80],
            "total_return_pct": [24.4, 19.1],
            "benchmark_return_pct": [17.0, 17.0],
            "excess_return_pct": [7.4, 2.1],
            "sharpe_ratio": [1.12, 0.95],
            "max_drawdown_pct": [-9.2, -12.8],
            "fees_paid": [41.8, 38.5],
        }
    ).to_csv(sweep_dir / "results.csv", index=False)
    pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "equity": [10000.0, 10120.0],
            "benchmark_equity": [10000.0, 10080.0],
            "drawdown": [0.0, -0.3],
        }
    ).to_csv(sweep_dir / "best_equity_curve.csv", index=False)
    pd.DataFrame(
        {
            "entry_date": ["2024-01-01"],
            "entry_price": [100.0],
            "exit_date": ["2024-01-05"],
            "exit_price": [104.0],
            "pnl_pct": [4.0],
            "holding_days": [4],
        }
    ).to_csv(sweep_dir / "best_trades.csv", index=False)


def test_index_lists_existing_reports(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preset strategia" in body
    assert "SPY" in body
    assert "Buy &amp; hold" in body
    assert "Sweep parametri" in body
    assert "Run valide" in body
    assert "MACD Trend" in body
    assert 'value="1m"' in body
    assert 'value="15m"' in body
    assert "ultimi 730 giorni" in body
    assert "data-expandable-panel" in body


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
            "run_mode": "single",
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


def test_create_sweep_redirects_to_sweep_detail(monkeypatch, tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    def fake_run(sweep_request, output_dir: Path):
        sweep_dir = output_dir / "SPY-sma_cross-sweep-20260403-100000"
        create_sweep_fixture(sweep_dir)

        class Completed:
            def __init__(self) -> None:
                self.sweep_dir = sweep_dir
                self.summary = {"run_count": 6}

        return Completed()

    monkeypatch.setattr("trading_bot.web.run_sma_sweep_request", fake_run)
    client = app.test_client()
    response = client.post(
        "/backtests",
        data={
            "symbol": "SPY",
            "start": "2020-01-01",
            "end": "2024-12-31",
            "run_mode": "sweep",
            "interval": "1d",
            "strategy": "sma_cross",
            "initial_capital": "10000",
            "fee_bps": "5",
            "fast_start": "10",
            "fast_end": "30",
            "fast_step": "10",
            "slow_start": "80",
            "slow_end": "120",
            "slow_step": "20",
            "sort_by": "total_return_pct",
            "fast": "20",
            "slow": "100",
            "rsi_period": "14",
            "rsi_lower": "30",
            "rsi_upper": "55",
        },
    )

    assert response.status_code == 302
    assert "/sweeps/SPY-sma_cross-sweep-20260403-100000" in response.headers["Location"]


def test_report_detail_renders_chart_and_trade_table(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Strategia vs buy &amp; hold" in body
    assert "Delta vs hold" in body
    assert "Spese totali" in body
    assert "Prime 20 operazioni" in body
    assert 'id="panel-backdrop"' in body


def test_sweep_detail_renders_ranking_and_best_run(tmp_path: Path) -> None:
    sweep_name = "SPY-sma_cross-sweep-20260403-100000"
    create_sweep_fixture(tmp_path / sweep_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/sweeps/{sweep_name}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Best SMA vs semplice buy &amp; hold" in body
    assert "Migliori combinazioni SMA" in body
    assert "Prime 20 operazioni del best run" in body
    assert "20 / 100" in body


def test_create_preset_saves_named_strategy_setup(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    client = app.test_client()

    response = client.post(
        "/presets",
        data={
            "preset_name": "RSI daily base",
            "symbol": "SPY",
            "start": "2020-01-01",
            "end": "2024-12-31",
            "run_mode": "single",
            "interval": "1d",
            "strategy": "rsi_mean_reversion",
            "initial_capital": "10000",
            "fee_bps": "5",
            "rsi_mean_reversion__period": "14",
            "rsi_mean_reversion__lower": "30",
            "rsi_mean_reversion__upper": "55",
        },
    )

    assert response.status_code == 201
    assert (tmp_path / "strategy_presets.json").exists()
    body = response.get_data(as_text=True)
    assert "Preset salvato: RSI daily base" in body
