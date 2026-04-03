from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trading_bot.services import BacktestRequest
from trading_bot.web import create_app


def create_report_fixture(report_dir: Path, *, with_trades: bool = True) -> None:
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
                "primary_strategy": "sma_cross",
                "primary_strategy_label": "SMA Crossover",
                "active_strategy_ids": ["sma_cross"],
                "rule_logic": "all",
                "rule_logic_label": "Tutte le regole (AND)",
                "is_composite": False,
                "active_rules": [
                    {
                        "slot": "rule_1",
                        "strategy": "sma_cross",
                        "strategy_label": "SMA Crossover",
                        "parameters": {
                            "fast": 20,
                            "slow": 100,
                        },
                    }
                ],
                "start": "2020-01-01",
                "end": "2024-12-31",
                "interval": "1d",
                "fee_bps": 5.0,
                "initial_capital": 10000.0,
                "parameters": {
                    "fast": 20,
                    "slow": 100,
                },
                "created_at": "2026-04-03T09:00:00",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "open": [100.0, 100.4],
            "high": [101.2, 101.6],
            "low": [99.5, 100.1],
            "close": [100.8, 101.1],
            "volume": [1_250_000, 1_540_000],
            "equity": [10000.0, 10100.0],
            "benchmark_equity": [10000.0, 10080.0],
            "drawdown": [0.0, -0.5],
        }
    ).to_csv(report_dir / "equity_curve.csv", index=False)
    if with_trades:
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
    else:
        (report_dir / "trades.csv").write_text("", encoding="utf-8")


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
            "open": [100.0, 100.4],
            "high": [101.2, 101.6],
            "low": [99.5, 100.1],
            "close": [100.8, 101.1],
            "volume": [1_250_000, 1_540_000],
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
    assert 'name="active_strategies"' in body
    assert 'data-strategy-toggle="ema_cross"' in body
    assert 'data-strategy-edit="ema_cross"' in body
    assert 'data-strategy-sweep="ema_cross"' in body
    assert 'name="rule_logic"' in body
    assert 'id="strategy-modal-title"' in body
    assert 'id="strategy-modal-state"' in body
    assert 'data-modal-input="sma_cross__fast"' in body


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


def test_create_backtest_supports_combined_rules(monkeypatch, tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    def fake_run(backtest_request: BacktestRequest, output_dir: Path):
        report_dir = output_dir / "SPY-multi_rules_all-20260403-110000"
        create_report_fixture(report_dir)

        class Completed:
            def __init__(self) -> None:
                self.report_dir = report_dir

        assert backtest_request.is_composite is True
        assert len(backtest_request.active_rules()) == 2
        assert backtest_request.rule_logic == "all"
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
            "active_strategies": ["ema_cross", "rsi_mean_reversion"],
            "rule_logic": "all",
            "initial_capital": "10000",
            "fee_bps": "5",
            "ema_cross__fast": "12",
            "ema_cross__slow": "26",
            "rsi_mean_reversion__period": "14",
            "rsi_mean_reversion__lower": "30",
            "rsi_mean_reversion__upper": "55",
        },
    )

    assert response.status_code == 302
    assert "/reports/SPY-multi_rules_all-20260403-110000" in response.headers["Location"]


def test_create_backtest_shows_intraday_validation_near_form_fields(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    client = app.test_client()

    response = client.post(
        "/backtests",
        data={
            "symbol": "SPY",
            "start": "2020-01-01",
            "end": "2026-01-01",
            "run_mode": "single",
            "interval": "5m",
            "strategy": "sma_cross",
            "initial_capital": "10000",
            "fee_bps": "5",
            "sma_cross__fast": "20",
            "sma_cross__slow": "100",
        },
    )

    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "Yahoo Finance consente richieste solo negli ultimi 60 giorni." in body
    assert 'class="field-error"' in body
    assert 'name="interval" id="interval-select" class="input-error"' in body
    assert 'name="start"' in body
    assert 'class="flash flash-error"' not in body


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


def test_create_ema_sweep_redirects_to_sweep_detail(monkeypatch, tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    def fake_run(sweep_request, output_dir: Path):
        sweep_dir = output_dir / "SPY-ema_cross-sweep-20260403-100000"
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
            "strategy": "ema_cross",
            "initial_capital": "10000",
            "fee_bps": "5",
            "fast_start": "10",
            "fast_end": "30",
            "fast_step": "10",
            "slow_start": "80",
            "slow_end": "120",
            "slow_step": "20",
            "sort_by": "total_return_pct",
            "ema_cross__fast": "12",
            "ema_cross__slow": "26",
        },
    )

    assert response.status_code == 302
    assert "/sweeps/SPY-ema_cross-sweep-20260403-100000" in response.headers["Location"]


def test_create_sweep_rejects_combined_rules(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    client = app.test_client()

    response = client.post(
        "/backtests",
        data={
          "symbol": "SPY",
          "start": "2020-01-01",
          "end": "2024-12-31",
          "run_mode": "sweep",
          "interval": "1d",
          "active_strategies": ["ema_cross", "rsi_mean_reversion"],
          "rule_logic": "all",
          "initial_capital": "10000",
          "fee_bps": "5",
          "ema_cross__fast": "12",
          "ema_cross__slow": "26",
          "rsi_mean_reversion__period": "14",
          "rsi_mean_reversion__lower": "30",
          "rsi_mean_reversion__upper": "55",
          "fast_start": "10",
          "fast_end": "30",
          "fast_step": "10",
          "slow_start": "80",
          "slow_end": "120",
          "slow_step": "20",
        },
    )

    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "Lo sweep multiplo richiede una sola regola attiva." in body


def test_report_detail_redirects_to_chart_terminal(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/reports/{report_name}/chart?focus=equity")


def test_report_overview_renders_dashboard(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/overview")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "report-dashboard-body" in body
    assert "Cosa dicono i numeri" in body
    assert "Rendimento e benchmark" in body
    assert "Costi e attrito" in body
    assert "Prime 20 operazioni" in body
    assert "Esito" in body
    assert "Durata" in body
    assert "WIN" in body


def test_report_chart_handles_empty_trades_file(tmp_path: Path) -> None:
    report_name = "SPY-multi_rules_all-20260403-164850"
    create_report_fixture(tmp_path / report_name, with_trades=False)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/chart?focus=equity")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nessun trade disponibile per questo chart." in body


def test_report_overview_infers_period_from_equity_curve_when_metadata_missing(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    report_dir = tmp_path / report_name
    create_report_fixture(report_dir)
    (report_dir / "metadata.json").unlink()
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/overview")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "2024-01-01" in body
    assert "2024-01-02" in body
    assert "timeframe 1d" in body


def test_sweep_detail_renders_ranking_and_best_run(tmp_path: Path) -> None:
    sweep_name = "SPY-sma_cross-sweep-20260403-100000"
    create_sweep_fixture(tmp_path / sweep_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/sweeps/{sweep_name}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Best SMA Crossover vs semplice buy &amp; hold" in body
    assert "Migliori combinazioni" in body
    assert "Prime 20 operazioni del best run" in body
    assert "20 / 100" in body


def test_report_chart_window_renders_interactive_chart(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/chart?focus=equity")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "interactive-chart-root" in body
    assert 'id="chart-window-data"' in body
    assert "FXReplay-inspired terminal" in body
    assert "Overview dati" in body
    assert 'data-focus-view="price"' in body
    assert 'data-trace-toggle="benchmark"' in body
    assert "Ultima barra" in body
    assert 'data-playback-mode="replay"' in body
    assert 'data-series-start' in body
    assert 'data-visible-window' in body
    assert 'data-playback-speed' in body
    assert 'data-chart-strategy-toggle' in body
    assert 'data-live-comparison-grid' in body
    assert f"/reports/{report_name}/chart-preview" in body


def test_report_chart_preview_returns_live_payload(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.post(
        f"/reports/{report_name}/chart-preview",
        json={
            "active_strategies": ["sma_cross"],
            "rule_logic": "all",
            "sma_cross__fast": 1,
            "sma_cross__slow": 2,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["preview_label"] == "SMA Crossover"
    assert "chart_payload" in payload
    assert "comparison_cards" in payload
    assert "trade_preview" in payload


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
