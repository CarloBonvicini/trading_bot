from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from trading_bot.data import resolve_market_data_symbol
from trading_bot.reporting import build_chart_payload, build_trade_preview, load_sweep_chart_window
from trading_bot.services import BacktestRequest
from trading_bot.application.requests import SweepRequest
from trading_bot.web import HOME_DRAFT_SESSION_KEY, create_app


LINK_PATTERN = re.compile(r'href="([^"]+)"')
DETACHED_URL_PATTERN = re.compile(r'data-detached-url="([^"]+)"')
HOME_ROUTE_PATTERN = re.compile(r'data-home-tab-route="([^"]+)"')


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


def extract_navigation_targets(body: str) -> list[str]:
    targets: list[str] = []
    for pattern in (LINK_PATTERN, DETACHED_URL_PATTERN, HOME_ROUTE_PATTERN):
        for match in pattern.findall(body):
            if not match or match.startswith("http") or match.startswith("#"):
                continue
            if match not in targets:
                targets.append(match)
    return targets


def test_market_symbol_alias_maps_gold_to_gold_futures_feed() -> None:
    assert resolve_market_data_symbol("GOLD") == "GC=F"
    assert resolve_market_data_symbol("oro") == "GC=F"
    assert resolve_market_data_symbol("SPY") == "SPY"


def test_backtest_request_keeps_display_symbol_and_resolves_data_symbol() -> None:
    request = BacktestRequest.from_mapping(
        {
            "symbol": "GOLD",
            "start": "2026-04-01",
            "end": "2026-04-05",
            "interval": "1m",
            "active_strategies": ["sma_cross"],
            "rule_logic": "all",
            "initial_capital": "10000",
            "fee_bps": "5",
            "sma_cross__fast": "20",
            "sma_cross__slow": "100",
        }
    )

    assert request.symbol == "GOLD"
    assert request.data_symbol == "GC=F"
    assert request.metadata()["data_symbol"] == "GC=F"


def test_sweep_request_keeps_display_symbol_and_resolves_data_symbol() -> None:
    request = SweepRequest.from_mapping(
        {
            "symbol": "GOLD",
            "start": "2026-04-01",
            "end": "2026-04-05",
            "interval": "1m",
            "run_mode": "sweep",
            "active_strategies": ["sma_cross"],
            "rule_logic": "all",
            "initial_capital": "10000",
            "fee_bps": "5",
            "fast_start": "10",
            "fast_end": "20",
            "fast_step": "10",
            "slow_start": "80",
            "slow_end": "100",
            "slow_step": "20",
        }
    )

    assert request.symbol == "GOLD"
    assert request.data_symbol == "GC=F"
    assert request.metadata()["data_symbol"] == "GC=F"


def test_index_lists_existing_reports(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'role="tablist"' in body
    assert 'data-home-tab-button="dashboard"' in body
    assert 'data-home-tab-button="strategies"' not in body
    assert 'data-home-tab-route="/backtests/new"' in body
    assert "Panoramica workspace" in body
    assert "ultima sessione" in body
    assert "Miglior win ratio" in body
    assert "Best Sharpe" in body
    assert "Metriche da tenere d'occhio" in body
    assert "100.00%" in body
    assert "1.12" in body
    assert 'id="home-panel-setup"' in body
    assert 'id="home-panel-strategies"' in body
    assert "/drafts/resume/SPY-sma_cross-20260403-090000" in body
    assert ">Backtest<" in body


def test_new_backtest_page_renders_setup_form(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/backtests/new")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preset strategia" in body
    assert 'id="setup-preset-select"' in body
    assert 'name="symbol"' in body
    assert 'name="interval" id="setup-interval-select"' in body
    assert 'id="interval-auto-adjust-note"' in body
    assert 'name="run_mode" id="setup-run-mode-select"' in body
    assert "Continua alle strategie" in body
    assert 'data-backtest-continue="true"' in body
    assert 'id="home-panel-strategies"' in body
    assert 'data-strategy-toggle="ema_cross"' in body
    assert '"intervalLookbackDays"' in body


def test_strategies_page_renders_strategy_workspace(tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/strategies")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-strategy-toggle="ema_cross"' in body
    assert 'data-strategy-edit="ema_cross"' in body
    assert 'data-strategy-sweep="ema_cross"' in body
    assert 'data-home-tab-button="strategies"' not in body
    assert 'name="rule_logic"' in body
    assert 'id="strategy-modal-title"' in body
    assert 'id="strategy-modal-state"' in body
    assert 'data-modal-input="sma_cross__fast"' in body
    assert 'id="submit-button"' in body
    assert 'id="home-panel-setup"' in body
    assert 'data-home-panel="results"' in body


def test_history_page_lists_saved_results(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/history")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Tutte le sessioni avviate" in body
    assert "select session" in body
    assert "Clicca una sessione per aprire direttamente il suo chart dedicato." in body
    assert "Go to chart" in body
    assert 'data-session-selector="SPY-sma_cross-sweep-20260403-100000"' in body
    assert 'data-session-open-url="/sweeps/SPY-sma_cross-sweep-20260403-100000/chart?focus=price"' in body
    assert f"/sweeps/SPY-sma_cross-sweep-20260403-100000/chart?focus=price" in body


def test_history_page_can_focus_specific_session(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/history?session=SPY-sma_cross-sweep-20260403-100000")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Sweep - SMA Crossover" in body
    assert "Go to chart" in body
    assert "Best params" in body
    assert f"/sweeps/SPY-sma_cross-sweep-20260403-100000/chart?focus=price" in body


def test_history_page_can_focus_specific_report_session(tmp_path: Path) -> None:
    create_report_fixture(tmp_path / "SPY-sma_cross-20260403-090000")
    create_sweep_fixture(tmp_path / "SPY-sma_cross-sweep-20260403-100000")
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get("/history?session=SPY-sma_cross-20260403-090000")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Go to chart" in body
    assert "Riprendi strategie" in body
    assert "Backtest" in body
    assert "mini-chart-legend" in body
    assert "Strategy" in body
    assert "Buy &amp; hold" in body
    assert f"/reports/SPY-sma_cross-20260403-090000/chart?focus=price" in body


def test_chart_window_uses_clear_labels_and_simplified_default_view(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/chart")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Confronto con il buy &amp; hold" in body
    assert "Prime 10 operazioni della preview" not in body
    assert "Operazioni del report" in body
    assert "massimo 50 righe per pagina" in body
    assert ">Pan<" in body
    assert ">Zoom<" in body
    assert ">Reset<" in body
    assert ">Esporta<" in body
    assert ">Schermo<" in body
    assert "Pronto" in body
    assert "Layout standard del chart." in body
    assert 'data-chart-indicator-open' in body
    assert 'data-chart-indicator-modal' in body
    assert "Indicatori e linee del grafico" in body
    assert "Linee disponibili" in body
    assert "Prezzo del mercato mostrato come candele." in body
    assert "Curva equity della strategia." in body
    assert "Confronto buy and hold sullo stesso periodo." in body


def test_live_comparison_cards_use_clearer_copy(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/reports/{report_name}/chart")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Rendimento attuale" in body
    assert "Rendimento buy &amp; hold" in body
    assert "Delta rendimento" in body
    assert "Delta drawdown" in body
    assert "Delta equity finale" in body
    assert "Fee" in body
    assert "buy &amp; hold" in body


def test_internal_navigation_targets_resolve(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    sweep_name = "SPY-sma_cross-sweep-20260403-100000"
    create_report_fixture(tmp_path / report_name)
    create_sweep_fixture(tmp_path / sweep_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    pages = [
        "/",
        "/backtests/new",
        "/strategies",
        f"/history?session={report_name}",
        f"/history?session={sweep_name}",
        f"/reports/{report_name}/overview",
        f"/reports/{report_name}/chart?focus=equity",
        f"/sweeps/{sweep_name}",
        f"/sweeps/{sweep_name}/chart?focus=equity",
    ]

    checked_targets: set[str] = set()
    for page in pages:
        response = client.get(page)
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        for target in extract_navigation_targets(body):
            if target in checked_targets:
                continue
            checked_targets.add(target)
            target_response = client.get(target)
            assert target_response.status_code in {200, 302}, target


def test_resume_backtest_redirects_to_strategies_and_stores_draft(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.get(f"/drafts/resume/{report_name}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/strategies")
    with client.session_transaction() as flask_session:
        assert flask_session[HOME_DRAFT_SESSION_KEY]["symbol"] == "SPY"
        assert flask_session[HOME_DRAFT_SESSION_KEY]["active_strategies"] == ["sma_cross"]


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


def test_create_backtest_auto_adjusts_intraday_window(monkeypatch, tmp_path: Path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    client = app.test_client()
    captured: dict[str, str] = {}

    def fake_adjust(*, start: str, end: str, interval: str, now=None):
        assert start == "2020-01-01"
        assert end == "2026-01-01"
        assert interval == "5m"
        return "2026-02-04", "2026-04-04", True

    def fake_run(backtest_request: BacktestRequest, output_dir: Path):
        captured["start"] = backtest_request.start
        captured["end"] = backtest_request.end
        report_dir = output_dir / "SPY-sma_cross-20260403-100000"
        create_report_fixture(report_dir)

        class Completed:
            def __init__(self) -> None:
                self.report_dir = report_dir

        return Completed()

    monkeypatch.setattr("trading_bot.web.coerce_interval_date_window", fake_adjust)
    monkeypatch.setattr("trading_bot.web.run_backtest_request", fake_run)

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

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/reports/SPY-sma_cross-20260403-100000")
    assert captured == {"start": "2026-02-04", "end": "2026-04-04"}


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
    assert response.headers["Location"].endswith(f"/reports/{report_name}/chart?focus=price")


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
    assert 'id="chart-trade-table-data"' in body
    assert 'data-chart-trade-table' in body


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
    assert 'data-signal-popup-host' in body
    assert 'data-signal-popup' in body
    assert 'data-signal-popup-copy' in body
    assert "Chart sessione" in body
    assert "Overview" in body
    assert 'data-focus-view="price"' in body
    assert "Candela" in body
    assert 'data-candle-controls' in body
    assert 'data-trace-toggle="benchmark"' in body
    assert 'data-chart-indicator-search' in body
    assert "Layer attivi" not in body
    assert "Ultima candela" in body
    assert "Panoramica sessione" in body
    assert 'data-preview-indicator-panels' not in body
    assert "Gli indicatori live vengono disegnati direttamente dentro il grafico come pannelli dedicati." in body
    assert "Entry preview" in body
    assert "Ingresso simulato della configurazione attuale." in body
    assert "Lettura e coerenza del risultato" in body
    assert "Metriche operative" in body
    assert "Controlli di coerenza" in body
    assert "Operazioni chiuse" in body
    assert "Win rate" in body
    assert "Trade chiusi" in body
    assert "Equity finale" in body
    assert "Buy &amp; hold finale" in body
    assert 'data-playback-mode="replay"' not in body
    assert 'data-series-start' not in body
    assert 'data-visible-window' not in body
    assert 'data-playback-speed' not in body
    assert 'data-chart-strategy-toggle' in body
    assert 'data-live-comparison-grid' in body
    assert 'data-live-validation-grid' in body
    assert 'data-live-validation-checks' in body
    assert "Prime 10 operazioni della preview" not in body
    assert 'id="chart-trade-table-data"' in body
    assert 'data-chart-trade-table' in body
    assert 'data-chart-trade-prev' in body
    assert 'data-chart-trade-next' in body
    assert 'data-chart-trade-detail-modal' in body
    assert 'data-chart-trade-detail-title' in body
    assert 'data-chart-trade-detail-entry' in body
    assert 'data-chart-trade-detail-exit' in body
    assert "Operazioni del report" in body
    assert "massimo 50 righe per pagina" in body
    assert re.search(r'"interval"\s*:\s*"1d"', body)
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
    assert payload["chart_payload"]["interval"] == "1d"
    assert "indicators" in payload["chart_payload"]
    assert payload["chart_payload"]["indicators"][0]["placement"] == "overlay"
    assert len(payload["chart_payload"]["indicators"][0]["series"]) == 2
    assert "comparison_cards" in payload
    assert "validation_cards" in payload
    assert "validation_checks" in payload
    assert "trade_preview" in payload


def test_build_chart_payload_enriches_marker_popup_text_with_signal_snapshot() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
            ],
            "open": [10.0, 10.2, 11.9, 8.1],
            "high": [10.4, 12.4, 12.1, 8.2],
            "low": [9.8, 10.1, 7.8, 6.8],
            "close": [10.0, 12.0, 8.0, 7.0],
            "volume": [1000, 1200, 1400, 1600],
            "equity": [10000.0, 10100.0, 9900.0, 9800.0],
            "gross_equity": [10000.0, 10105.0, 9910.0, 9810.0],
            "benchmark_equity": [10000.0, 10050.0, 9950.0, 9900.0],
            "drawdown": [0.0, 0.0, -0.02, -0.03],
        }
    )
    trades = pd.DataFrame(
        {
            "entry_date": ["2024-01-03"],
            "entry_price": [8.0],
            "exit_date": ["2024-01-04"],
            "exit_price": [7.0],
            "pnl_pct": [-12.5],
            "holding_days": [1],
        }
    )

    payload = build_chart_payload(
        equity_curve=equity_curve,
        trades=trades,
        focus="price",
        interval="1d",
        signal_context={
            "strategy_label": "SMA Crossover",
            "rule_logic": "all",
            "active_rules": [
                {
                    "strategy": "sma_cross",
                    "strategy_label": "SMA Crossover",
                    "parameters": {"fast": 1, "slow": 2},
                }
            ],
        },
    )

    entry_text = payload["entry_markers"]["text"][0]
    exit_text = payload["exit_markers"]["text"][0]
    assert "ENTRY | 2024-01-03" in entry_text
    assert "Prezzo esecuzione: 8" in entry_text
    assert "Trigger strategia letto sulla candela precedente: 2024-01-02" in entry_text
    assert "Candela trigger: O 10.2 | H 12.4 | L 10.1 | C 12" in entry_text
    assert "Segnale strategia: FLAT -> LONG" in entry_text
    assert "SMA Crossover: SMA 1 12 > SMA 2 11" in entry_text
    assert "EXIT | 2024-01-04" in exit_text
    assert "Trigger strategia letto sulla candela precedente: 2024-01-03" in exit_text
    assert "PnL trade: -12.50%" in exit_text
    assert "Durata trade: 1 g" in exit_text


def test_build_trade_preview_orders_rows_chronologically_and_numbers_them() -> None:
    trades = pd.DataFrame(
        {
            "entry_date": ["2024-01-03", "2024-01-01"],
            "entry_price": [8.0, 10.0],
            "exit_date": ["2024-01-04", "2024-01-02"],
            "exit_price": [7.0, 11.0],
            "pnl_pct": [-12.5, 10.0],
            "holding_days": [1, 1],
        }
    )

    rows = build_trade_preview(trades, limit=None)

    assert [row["sequence"] for row in rows] == [1, 2]
    assert [row["entry_date_display"] for row in rows] == ["01/01/2024", "03/01/2024"]
    assert [row["entry_price_display"] for row in rows] == ["10", "8"]


def test_sweep_chart_uses_best_run_parameters_for_marker_explanation(tmp_path: Path) -> None:
    sweep_name = "SPY-sma_cross-sweep-20260403-100000"
    create_sweep_fixture(tmp_path / sweep_name)
    sweep_dir = tmp_path / sweep_name
    (sweep_dir / "summary.json").write_text(
        json.dumps(
            {
                "artifact_type": "sweep",
                "run_count": 6,
                "invalid_combinations": 0,
                "sort_by": "total_return_pct",
                "best_fast": 1,
                "best_slow": 2,
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
    pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 10.2, 11.9, 8.1],
            "high": [10.4, 12.4, 12.1, 8.2],
            "low": [9.8, 10.1, 7.8, 6.8],
            "close": [10.0, 12.0, 8.0, 7.0],
            "volume": [1000, 1200, 1400, 1600],
            "equity": [10000.0, 10120.0, 9950.0, 9900.0],
            "benchmark_equity": [10000.0, 10080.0, 10020.0, 9990.0],
            "drawdown": [0.0, 0.0, -0.02, -0.03],
        }
    ).to_csv(sweep_dir / "best_equity_curve.csv", index=False)
    pd.DataFrame(
        {
            "entry_date": ["2024-01-03"],
            "entry_price": [8.0],
            "exit_date": ["2024-01-04"],
            "exit_price": [7.0],
            "pnl_pct": [-12.5],
            "holding_days": [1],
        }
    ).to_csv(sweep_dir / "best_trades.csv", index=False)

    chart = load_sweep_chart_window(output_dir=tmp_path, sweep_name=sweep_name, focus="price")

    entry_text = chart["chart_payload"]["entry_markers"]["text"][0]
    assert "SMA Crossover: SMA 1 12 > SMA 2 11" in entry_text


def test_report_chart_preview_returns_overlay_and_panel_indicators(tmp_path: Path) -> None:
    report_name = "SPY-sma_cross-20260403-090000"
    create_report_fixture(tmp_path / report_name)
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})

    client = app.test_client()
    response = client.post(
        f"/reports/{report_name}/chart-preview",
        json={
            "active_strategies": ["sma_cross", "rsi_mean_reversion"],
            "rule_logic": "all",
            "sma_cross__fast": 5,
            "sma_cross__slow": 20,
            "rsi_mean_reversion__period": 14,
            "rsi_mean_reversion__lower": 30,
            "rsi_mean_reversion__upper": 55,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    indicators = payload["chart_payload"]["indicators"]
    placements = {indicator["placement"] for indicator in indicators}
    labels = {indicator["label"] for indicator in indicators}
    assert placements == {"overlay", "panel"}
    assert "SMA Crossover" in labels
    assert "RSI Mean Reversion" in labels


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
