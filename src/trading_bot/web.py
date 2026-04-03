from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for

from trading_bot.application.chart_lab import build_chart_lab_state, build_preview_request, load_market_data_from_saved_equity
from trading_bot.application.dashboard import build_dashboard_context
from trading_bot.application.execution import build_backtest_result
from trading_bot.errors import FormValidationError
from trading_bot.reporting import (
    SUMMARY_LABELS,
    build_chart_payload,
    build_live_comparison_cards,
    build_summary_cards,
    build_trade_preview,
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
                form_values=request.form,
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=request.form, status=400)

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
                form_values=request.form,
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=request.form, status=400)

        flash(f"Preset salvato: {preset['name']}", "success")
        return _render_home(form_values=request.form, status=201)

    @app.get("/reports/<report_name>")
    def report_detail(report_name: str) -> str:
        return redirect(url_for("report_chart_window", report_name=report_name, focus="equity"))

    @app.get("/reports/<report_name>/overview")
    def report_overview(report_name: str) -> str:
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

        chart = _attach_chart_lab(
            chart=chart,
            preview_endpoint=url_for("report_chart_preview", report_name=report_name),
        )
        return render_template("chart_window.html", chart=chart)

    @app.post("/reports/<report_name>/chart-preview")
    def report_chart_preview(report_name: str):
        return _build_chart_preview_response(
            artifact_type="report",
            artifact_name=report_name,
        )

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

        chart = _attach_chart_lab(
            chart=chart,
            preview_endpoint=url_for("sweep_chart_preview", sweep_name=sweep_name),
        )
        return render_template("chart_window.html", chart=chart)

    @app.post("/sweeps/<sweep_name>/chart-preview")
    def sweep_chart_preview(sweep_name: str):
        return _build_chart_preview_response(
            artifact_type="sweep",
            artifact_name=sweep_name,
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
        if hasattr(form_values, "getlist"):
            values["active_strategies"] = form_values.getlist("active_strategies")
        elif isinstance(values.get("active_strategies"), str):
            values["active_strategies"] = [values["active_strategies"]]

    saved_items = list_saved_items(current_app.config["REPORTS_DIR"])
    dashboard = build_dashboard_context(saved_items=saved_items, strategies=STRATEGY_OPTIONS)

    return render_template(
        "index.html",
        form_values=values,
        field_errors=field_errors or {},
        invalid_fields=set(invalid_fields or ()),
        saved_items=saved_items,
        dashboard=dashboard,
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


def _attach_chart_lab(chart: dict[str, object], *, preview_endpoint: str) -> dict[str, object]:
    metadata = chart["metadata"]
    chart_lab_state = build_chart_lab_state(metadata)
    baseline_label = chart_lab_state["baseline_label"]

    return {
        **chart,
        "chart_lab": {
            **chart_lab_state,
            "preview_endpoint": preview_endpoint,
            "strategies": STRATEGY_OPTIONS,
            "rule_logic_options": RULE_LOGIC_OPTIONS,
            "comparison_cards": build_live_comparison_cards(
                preview_summary=chart["summary"],
                baseline_summary=chart["summary"],
                baseline_label=baseline_label,
                preview_label=baseline_label,
            ),
            "summary_cards": build_summary_cards(chart["summary"]),
            "trade_preview": chart["trade_preview"][:10],
        },
    }


def _build_chart_preview_response(*, artifact_type: str, artifact_name: str):
    try:
        chart, market_data_path = _load_chart_preview_source(
            artifact_type=artifact_type,
            artifact_name=artifact_name,
        )
        raw = _preview_raw_mapping()
        market_data = load_market_data_from_saved_equity(market_data_path)
        preview_request = build_preview_request(
            _metadata_for_chart_preview(chart=chart, market_data=market_data, artifact_name=artifact_name),
            raw,
        )
        result = build_backtest_result(backtest_request=preview_request, data=market_data)
    except FileNotFoundError:
        abort(404)
    except FormValidationError as exc:
        return (
            jsonify(
                {
                    "error": str(exc),
                    "display_field": exc.display_field,
                    "fields": list(exc.field_names),
                }
            ),
            400,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    baseline_label = str(
        chart["metadata"].get("strategy_label")
        or chart["metadata"].get("primary_strategy_label")
        or chart["metadata"].get("strategy")
        or "Sistema salvato"
    )

    return jsonify(
        {
            "preview_label": preview_request.strategy_label,
            "active_rule_labels": [rule.label for rule in preview_request.active_rules()],
            "chart_payload": build_chart_payload(
                equity_curve=result.equity_curve,
                trades=result.trades,
                focus="equity",
            ),
            "summary_cards": build_summary_cards(result.summary),
            "comparison_cards": build_live_comparison_cards(
                preview_summary=result.summary,
                baseline_summary=chart["summary"],
                baseline_label=baseline_label,
                preview_label=preview_request.strategy_label,
            ),
            "trade_preview": build_trade_preview(result.trades, limit=10),
        }
    )


def _load_chart_preview_source(*, artifact_type: str, artifact_name: str) -> tuple[dict[str, object], Path]:
    reports_dir = Path(current_app.config["REPORTS_DIR"])
    if artifact_type == "report":
        chart = load_report_chart_window(
            output_dir=reports_dir,
            report_name=artifact_name,
            focus="equity",
        )
        return chart, reports_dir / artifact_name / "equity_curve.csv"

    chart = load_sweep_chart_window(
        output_dir=reports_dir,
        sweep_name=artifact_name,
        focus="equity",
    )
    return chart, reports_dir / artifact_name / "best_equity_curve.csv"


def _preview_raw_mapping() -> dict[str, object]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload

    raw = request.form.to_dict()
    if hasattr(request.form, "getlist"):
        raw["active_strategies"] = request.form.getlist("active_strategies")
    return raw


def _metadata_for_chart_preview(
    *,
    chart: dict[str, object],
    market_data,
    artifact_name: str,
) -> dict[str, object]:
    metadata = dict(chart["metadata"])
    index = market_data.index
    start_value = metadata.get("start")
    end_value = metadata.get("end")
    if not start_value and len(index):
        start_value = index[0].strftime("%Y-%m-%d")
    if not end_value and len(index):
        end_value = index[-1].strftime("%Y-%m-%d")

    metadata["start"] = start_value or ""
    metadata["end"] = end_value or ""
    metadata["interval"] = metadata.get("interval") or "1d"
    metadata["symbol"] = metadata.get("symbol") or artifact_name.split("-", 1)[0]
    metadata["initial_capital"] = metadata.get("initial_capital") or chart["summary"].get("initial_capital", 10_000)
    metadata["fee_bps"] = metadata.get("fee_bps") or 5
    return metadata


if __name__ == "__main__":
    main()
