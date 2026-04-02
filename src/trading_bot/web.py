from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from trading_bot.reporting import SUMMARY_LABELS, list_reports, load_report
from trading_bot.services import (
    DEFAULT_REPORTS_DIR,
    INTERVAL_OPTIONS,
    STRATEGY_OPTIONS,
    BacktestRequest,
    as_form_values,
    run_backtest_request,
)

ALLOWED_REPORT_FILES = {"summary.json", "equity_curve.csv", "trades.csv", "metadata.json"}


def create_app(config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY="trading-bot-local-dev",
        REPORTS_DIR=Path(DEFAULT_REPORTS_DIR).resolve(),
    )
    if config:
        app.config.update(config)
    app.config["REPORTS_DIR"] = Path(app.config["REPORTS_DIR"]).resolve()

    @app.get("/")
    def index() -> str:
        return _render_home()

    @app.post("/backtests")
    def create_backtest():
        try:
            backtest_request = BacktestRequest.from_mapping(request.form)
            completed = run_backtest_request(
                backtest_request=backtest_request,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=dict(request.form), status=400)

        flash(f"Backtest completato: {completed.report_dir.name}", "success")
        return redirect(url_for("report_detail", report_name=completed.report_dir.name))

    @app.get("/reports/<report_name>")
    def report_detail(report_name: str) -> str:
        try:
            report = load_report(output_dir=current_app.config["REPORTS_DIR"], report_name=report_name)
        except FileNotFoundError:
            abort(404)

        return render_template(
            "report.html",
            report=report,
            reports=list_reports(current_app.config["REPORTS_DIR"]),
            summary_labels=SUMMARY_LABELS,
        )

    @app.get("/reports/<report_name>/files/<filename>")
    def download_report_file(report_name: str, filename: str):
        if filename not in ALLOWED_REPORT_FILES:
            abort(404)

        report_dir = Path(current_app.config["REPORTS_DIR"]) / report_name
        file_path = report_dir / filename
        if not file_path.exists():
            abort(404)
        return send_file(file_path, as_attachment=True)

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Trading Bot web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the local server.")
    parser.add_argument("--port", type=int, default=8000, help="Port for the local server.")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing generated reports.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    app = create_app({"REPORTS_DIR": Path(args.reports_dir).resolve()})
    app.run(host=args.host, port=args.port, debug=args.debug)


def _render_home(form_values: dict[str, object] | None = None, status: int = 200) -> str:
    values = as_form_values()
    if form_values:
        values.update(form_values)

    return render_template(
        "index.html",
        form_values=values,
        reports=list_reports(current_app.config["REPORTS_DIR"]),
        strategies=STRATEGY_OPTIONS,
        intervals=INTERVAL_OPTIONS,
    ), status


if __name__ == "__main__":
    main()
