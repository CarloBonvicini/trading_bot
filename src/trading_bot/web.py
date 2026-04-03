from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from trading_bot.errors import FormValidationError
from trading_bot.reporting import (
    SUMMARY_LABELS,
    list_saved_items,
    load_report,
    load_report_chart_window,
    load_sweep,
    load_sweep_chart_window,
)
from trading_bot.services import (
    DEFAULT_REPORTS_DIR,
    INTERVAL_OPTIONS,
    RULE_LOGIC_OPTIONS,
    RUN_MODE_OPTIONS,
    STRATEGY_OPTIONS,
    SWEEP_SORT_OPTIONS,
    BacktestRequest,
    SweepRequest,
    as_form_values,
    interval_helper_texts,
    list_strategy_presets,
    run_backtest_request,
    run_sma_sweep_request,
    save_strategy_preset,
)

ALLOWED_REPORT_FILES = {"summary.json", "equity_curve.csv", "trades.csv", "metadata.json"}
ALLOWED_SWEEP_FILES = {
    "summary.json",
    "results.csv",
    "metadata.json",
    "best_summary.json",
    "best_equity_curve.csv",
    "best_trades.csv",
}


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
        run_mode = str(request.form.get("run_mode", "single")).strip().lower()
        try:
            if run_mode == "sweep":
                sweep_request = SweepRequest.from_mapping(request.form)
                completed_sweep = run_sma_sweep_request(
                    sweep_request=sweep_request,
                    output_dir=current_app.config["REPORTS_DIR"],
                )
                flash(
                    (
                        f"Sweep completato: {completed_sweep.sweep_dir.name} "
                        f"({completed_sweep.summary['run_count']} combinazioni valide)"
                    ),
                    "success",
                )
                return redirect(url_for("sweep_detail", sweep_name=completed_sweep.sweep_dir.name))

            backtest_request = BacktestRequest.from_mapping(request.form)
            completed = run_backtest_request(
                backtest_request=backtest_request,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except FormValidationError as exc:
            return _render_home(
                form_values=dict(request.form),
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=dict(request.form), status=400)

        flash(f"Backtest completato: {completed.report_dir.name}", "success")
        return redirect(url_for("report_detail", report_name=completed.report_dir.name))

    @app.post("/presets")
    def create_preset():
        try:
            preset = save_strategy_preset(
                raw=request.form,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except FormValidationError as exc:
            return _render_home(
                form_values=dict(request.form),
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=dict(request.form), status=400)

        flash(f"Preset salvato: {preset['name']}", "success")
        return _render_home(form_values=dict(request.form), status=201)

    @app.get("/reports/<report_name>")
    def report_detail(report_name: str) -> str:
        try:
            report = load_report(output_dir=current_app.config["REPORTS_DIR"], report_name=report_name)
        except FileNotFoundError:
            abort(404)

        return render_template(
            "report.html",
            report=report,
            saved_items=list_saved_items(current_app.config["REPORTS_DIR"]),
            summary_labels=SUMMARY_LABELS,
        )

    @app.get("/reports/<report_name>/chart")
    def report_chart_window(report_name: str) -> str:
        focus = str(request.args.get("focus", "equity")).strip().lower()
        try:
            chart = load_report_chart_window(
                output_dir=current_app.config["REPORTS_DIR"],
                report_name=report_name,
                focus=focus,
            )
        except FileNotFoundError:
            abort(404)

        return render_template("chart_window.html", chart=chart)

    @app.get("/sweeps/<sweep_name>")
    def sweep_detail(sweep_name: str) -> str:
        try:
            sweep = load_sweep(output_dir=current_app.config["REPORTS_DIR"], sweep_name=sweep_name)
        except FileNotFoundError:
            abort(404)

        return render_template(
            "sweep.html",
            sweep=sweep,
            saved_items=list_saved_items(current_app.config["REPORTS_DIR"]),
            summary_labels=SUMMARY_LABELS,
        )

    @app.get("/sweeps/<sweep_name>/chart")
    def sweep_chart_window(sweep_name: str) -> str:
        focus = str(request.args.get("focus", "equity")).strip().lower()
        try:
            chart = load_sweep_chart_window(
                output_dir=current_app.config["REPORTS_DIR"],
                sweep_name=sweep_name,
                focus=focus,
            )
        except FileNotFoundError:
            abort(404)

        return render_template("chart_window.html", chart=chart)

    @app.get("/reports/<report_name>/files/<filename>")
    def download_report_file(report_name: str, filename: str):
        if filename not in ALLOWED_REPORT_FILES:
            abort(404)

        report_dir = Path(current_app.config["REPORTS_DIR"]) / report_name
        file_path = report_dir / filename
        if not file_path.exists():
            abort(404)
        return send_file(file_path, as_attachment=True)

    @app.get("/sweeps/<sweep_name>/files/<filename>")
    def download_sweep_file(sweep_name: str, filename: str):
        if filename not in ALLOWED_SWEEP_FILES:
            abort(404)

        sweep_dir = Path(current_app.config["REPORTS_DIR"]) / sweep_name
        file_path = sweep_dir / filename
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


def _render_home(
    form_values: dict[str, object] | None = None,
    *,
    field_errors: dict[str, str] | None = None,
    invalid_fields: tuple[str, ...] | list[str] | set[str] | None = None,
    status: int = 200,
) -> str:
    values = as_form_values()
    if form_values:
        values.update(form_values)

    return render_template(
        "index.html",
        form_values=values,
        field_errors=field_errors or {},
        invalid_fields=set(invalid_fields or ()),
        saved_items=list_saved_items(current_app.config["REPORTS_DIR"]),
        strategy_presets=list_strategy_presets(current_app.config["REPORTS_DIR"]),
        strategies=STRATEGY_OPTIONS,
        rule_logic_options=RULE_LOGIC_OPTIONS,
        intervals=INTERVAL_OPTIONS,
        interval_hints=interval_helper_texts(),
        run_modes=RUN_MODE_OPTIONS,
        sweep_sort_options=SWEEP_SORT_OPTIONS,
    ), status


def _field_errors(exc: FormValidationError) -> dict[str, str]:
    if not exc.display_field:
        return {}
    return {exc.display_field: str(exc)}


if __name__ == "__main__":
    main()
