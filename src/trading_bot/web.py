from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from flask import Flask, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from trading_bot.application.autosetting import run_autosetting
from trading_bot.application.search_jobs import (
    get_job,
    get_portfolio_job,
    job_status,
    list_saved_searches,
    resume_search_job,
    start_multi_search_job,
    start_portfolio_search_job,
)
from trading_bot.strategies import STRATEGY_SPECS, build_strategy_signal, parse_strategy_parameters
from trading_bot.application.chart_lab import (
    build_chart_lab_state,
    build_preview_indicator_payload,
    build_preview_request,
    load_market_data_from_saved_equity,
)
from trading_bot.application.dashboard import build_dashboard_context, build_session_catalog
from trading_bot.application.execution import build_backtest_result
from trading_bot.application.forms import as_form_values_from_saved_metadata
from trading_bot.application.constants import COSTI_OPERAZIONE
from trading_bot.application.prova_del_caso import PROVE_PREDEFINITE
from trading_bot.application.requests import costi_operazione, flag_value
from trading_bot.data import INTRADAY_LOOKBACK_DAYS, coerce_interval_date_window
from trading_bot.errors import FormValidationError
from trading_bot.reporting import (
    METRIC_TOOLTIPS,
    SUMMARY_LABELS,
    build_chart_payload,
    build_live_comparison_cards,
    build_result_validation_snapshot,
    build_summary_cards,
    build_trade_preview,
    enrich_summary_with_equity_curve,
    list_saved_items,
    load_report_chart_window,
    load_sweep_chart_window,
    metric_tooltip,
)
from trading_bot.services import (
    DEFAULT_REPORTS_DIR,
    INTERVAL_OPTIONS,
    RULE_LOGIC_OPTIONS,
    RUN_MODE_OPTIONS,
    SIZING_OPTIONS,
    STRATEGY_OPTIONS,
    SWEEP_SORT_OPTIONS,
    WALKFORWARD_SORT_OPTIONS,
    WalkForwardResult,
    BacktestRequest,
    SweepRequest,
    as_form_values,
    interval_helper_texts,
    list_strategy_presets,
    run_backtest_request,
    run_sma_sweep_request,
    run_walk_forward,
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
HOME_DRAFT_SESSION_KEY = "home_backtest_draft"
HOME_VIEW_DASHBOARD = "dashboard"
HOME_VIEW_SETUP = "setup"
HOME_VIEW_STRATEGIES = "strategies"
HOME_VIEW_RESULTS = "results"


def create_app(config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY="trading-bot-local-dev",
        REPORTS_DIR=Path(DEFAULT_REPORTS_DIR).resolve(),
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    if config:
        app.config.update(config)
    app.config["REPORTS_DIR"] = Path(app.config["REPORTS_DIR"]).resolve()

    # Espone i tooltip come filtro Jinja: {{ "sharpe_ratio" | tooltip }}
    # restituisce la spiegazione, o stringa vuota se la chiave è sconosciuta.
    app.jinja_env.filters["tooltip"] = metric_tooltip
    # E l'etichetta in italiano corrente: {{ "max_drawdown_pct" | etichetta }}
    # diventa "Il calo peggiore". Senza, un template che mostra una metrica
    # dovrebbe riscriverne il nome a mano, e il giorno che cambia resterebbe
    # indietro in silenzio.
    app.jinja_env.filters["etichetta"] = lambda chiave: SUMMARY_LABELS.get(chiave, chiave)
    # Mappa completa disponibile come variabile globale per il JS (chart lab).
    app.jinja_env.globals["METRIC_TOOLTIPS"] = METRIC_TOOLTIPS

    @app.get("/")
    def index() -> str:
        return _render_home(view=HOME_VIEW_DASHBOARD)

    @app.get("/backtests/new")
    def new_backtest_home() -> str:
        return _render_home(view=HOME_VIEW_SETUP)

    @app.route("/strategies", methods=["GET", "POST"])
    def strategies_home():
        if request.method == "POST":
            _store_home_draft(_resolve_home_form_values(request.form))
        return redirect(url_for("new_backtest_home"))

    @app.get("/history")
    def history_home() -> str:
        return _render_home(view=HOME_VIEW_RESULTS)

    @app.get("/drafts/resume/<report_name>")
    def resume_backtest(report_name: str):
        saved_item = _find_saved_report(report_name)
        metadata = saved_item.get("metadata", {}) if isinstance(saved_item.get("metadata"), dict) else {}
        _store_home_draft(as_form_values_from_saved_metadata(metadata))
        return redirect(url_for("new_backtest_home"))

    @app.post("/backtests")
    def create_backtest():
        normalized_form = _normalize_intraday_form_window(request.form)
        _store_home_draft(_resolve_home_form_values(normalized_form))
        run_mode = str(normalized_form.get("run_mode", "single")).strip().lower()
        try:
            if run_mode == "sweep":
                sweep_request = SweepRequest.from_mapping(normalized_form)
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

            if run_mode == "walkforward":
                return _run_walkforward_view(normalized_form)

            backtest_request = BacktestRequest.from_mapping(normalized_form)
            completed = run_backtest_request(
                backtest_request=backtest_request,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except FormValidationError as exc:
            return _render_home(
                form_values=normalized_form,
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                view=_home_view_for_render(
                    form_values=normalized_form,
                    invalid_fields=exc.field_names,
                ),
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(
                form_values=normalized_form,
                view=_home_view_for_render(form_values=normalized_form, invalid_fields=()),
                status=400,
            )

        flash(f"Backtest completato: {completed.report_dir.name}", "success")
        return redirect(url_for("report_detail", report_name=completed.report_dir.name))

    @app.post("/searches/start")
    def start_search():
        """Avvia in background la ricerca automatica su uno o più mercati."""
        form = _normalize_intraday_form_window(request.form)
        _store_home_draft(_resolve_home_form_values(form))
        symbols = _parse_symbols(str(form.get("symbols") or form.get("symbol") or ""))
        if not symbols:
            flash("Inserisci almeno un simbolo, per esempio SPY o AAPL.", "error")
            return _render_home(form_values=form, view=HOME_VIEW_SETUP, status=400)

        interval = str(form.get("interval", "1d")).strip() or "1d"
        depth = str(form.get("depth", "rapida")).strip().lower()
        if depth not in {"rapida", "media", "lunga", "xl"}:
            depth = "rapida"
        initial_capital = float(str(form.get("initial_capital", "10000")).strip() or "10000")
        preset_costi = costi_operazione(form)
        if preset_costi is not None:
            fee_bps, slippage_bps = preset_costi
        else:
            fee_bps = float(str(form.get("fee_bps", "5")).strip() or "5")
            slippage_bps = float(str(form.get("slippage_bps", "0")).strip() or "0")
        consenti_short = flag_value(form, "consenti_short")
        flat_at_close = flag_value(form, "flat_at_close")
        # La prova del caso costa quanto la ricerca stessa moltiplicata per il
        # numero di storie rimescolate: e' una scelta, non un default nascosto.
        prove_del_caso = PROVE_PREDEFINITE if flag_value(form, "prova_del_caso") else 0

        job_id = start_multi_search_job(
            symbols=symbols,
            interval=interval,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            scan_mode=depth,
            start=str(form.get("start", "")).strip(),
            end=str(form.get("end", "")).strip(),
            reports_dir=current_app.config["REPORTS_DIR"],
            consenti_short=consenti_short,
            slippage_bps=slippage_bps,
            flat_at_close=flat_at_close,
            prove_del_caso=prove_del_caso,
        )
        return redirect(url_for("search_detail", job_id=job_id))

    @app.post("/portfolios/start")
    def start_portfolio_search():
        """Avvia in background la ricerca del portafoglio sui mercati indicati."""
        form = _normalize_intraday_form_window(request.form)
        _store_home_draft(_resolve_home_form_values(form))
        symbols = _parse_symbols(str(form.get("symbols") or form.get("symbol") or ""))
        if len(symbols) < 2:
            flash(
                "Per dividere i soldi servono almeno due mercati: aggiungine un altro, "
                "separato da una virgola.",
                "error",
            )
            return _render_home(form_values=form, view=HOME_VIEW_SETUP, status=400)

        preset_costi = costi_operazione(form)
        if preset_costi is not None:
            fee_bps, slippage_bps = preset_costi
        else:
            fee_bps = float(str(form.get("fee_bps", "5")).strip() or "5")
            slippage_bps = float(str(form.get("slippage_bps", "0")).strip() or "0")

        job_id = start_portfolio_search_job(
            symbols=symbols,
            interval=str(form.get("interval", "1d")).strip() or "1d",
            initial_capital=float(str(form.get("initial_capital", "10000")).strip() or "10000"),
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            start=str(form.get("start", "")).strip(),
            end=str(form.get("end", "")).strip(),
            reports_dir=current_app.config["REPORTS_DIR"],
            consenti_short=flag_value(form, "consenti_short"),
            prove_del_caso=PROVE_PREDEFINITE if flag_value(form, "prova_del_caso") else 0,
        )
        return redirect(url_for("portfolio_detail", job_id=job_id))

    @app.get("/portfolios/<job_id>")
    def portfolio_detail(job_id: str):
        job = get_portfolio_job(job_id, current_app.config["REPORTS_DIR"])
        if job is None:
            abort(404)
        if job["status"] == "done":
            return render_template("portfolio_result.html", result=job["result"], job=job)
        return render_template(
            "search_progress.html", job=job, job_id=job_id,
            status_url=url_for("portfolio_status", job_id=job_id),
        )

    @app.get("/portfolios/<job_id>/status")
    def portfolio_status(job_id: str):
        status = job_status(job_id, current_app.config["REPORTS_DIR"])
        if status is None:
            abort(404)
        return jsonify(status)

    @app.get("/searches/<job_id>")
    def search_detail(job_id: str):
        job = get_job(job_id, current_app.config["REPORTS_DIR"])
        if job is None:
            abort(404)
        if job["status"] == "done":
            return render_template("search_result.html", result=job["result"], job=job)
        return render_template("search_progress.html", job=job, job_id=job_id)

    @app.post("/searches/<job_id>/resume")
    def resume_search(job_id: str):
        """Riprende una ricerca interrotta dal punto in cui era arrivata."""
        if resume_search_job(job_id, current_app.config["REPORTS_DIR"]) is None:
            flash("Non c'è un avanzamento da riprendere per questa ricerca.", "error")
            return redirect(url_for("index"))
        return redirect(url_for("search_detail", job_id=job_id))

    @app.get("/searches/<job_id>/status")
    def search_status(job_id: str):
        status = job_status(job_id, current_app.config["REPORTS_DIR"])
        if status is None:
            abort(404)
        return jsonify(status)

    @app.post("/api/chart-lab/preset")
    def api_save_chart_lab_preset():
        """Salva la configurazione corrente del chart lab come preset (chiamata JSON)."""
        data = request.get_json(force=True) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "Inserisci un nome per il preset."}), 400

        # Ricostruisce il mapping atteso da save_strategy_preset
        merged: dict[str, object] = {
            "preset_name": name,
            "symbol": data.get("symbol", ""),
            "start": data.get("start", ""),
            "end": data.get("end", ""),
            "interval": data.get("interval", "1d"),
            "active_strategies": data.get("active_strategies", []),
            "rule_logic": data.get("rule_logic", "all"),
            "run_mode": "single",
        }
        # Parametri per singola strategia (es. "sma_cross__fast": 20)
        for key, value in data.items():
            if "__" in key:
                merged[key] = value

        try:
            preset = save_strategy_preset(
                raw=merged,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except FormValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        return jsonify({"success": True, "name": preset["name"]}), 201

    @app.post("/presets")
    def create_preset():
        normalized_form = _normalize_intraday_form_window(request.form)
        _store_home_draft(_resolve_home_form_values(normalized_form))
        try:
            preset = save_strategy_preset(
                raw=normalized_form,
                output_dir=current_app.config["REPORTS_DIR"],
            )
        except FormValidationError as exc:
            return _render_home(
                form_values=normalized_form,
                field_errors=_field_errors(exc),
                invalid_fields=exc.field_names,
                view=HOME_VIEW_SETUP,
                status=400,
            )
        except Exception as exc:
            flash(str(exc), "error")
            return _render_home(form_values=normalized_form, view=HOME_VIEW_SETUP, status=400)

        flash(f"Preset salvato: {preset['name']}", "success")
        return _render_home(form_values=normalized_form, view=HOME_VIEW_SETUP, status=201)

    @app.get("/reports/<report_name>")
    def report_detail(report_name: str) -> str:
        return redirect(url_for("report_chart_window", report_name=report_name, focus="price"))

    @app.get("/reports/<report_name>/chart")
    def report_chart_window(report_name: str) -> str:
        focus = str(request.args.get("focus", "price")).strip().lower()
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
            autosetting_endpoint=url_for("report_autosetting", report_name=report_name),
            correlation_endpoint=url_for("report_correlation", report_name=report_name),
            save_endpoint=url_for("api_save_chart_lab_preset"),
        )
        return render_template("chart_window.html", chart=chart)

    @app.post("/reports/<report_name>/chart-preview")
    def report_chart_preview(report_name: str):
        return _build_chart_preview_response(
            artifact_type="report",
            artifact_name=report_name,
        )

    @app.post("/reports/<report_name>/autosetting")
    def report_autosetting(report_name: str):
        return _build_autosetting_response(
            artifact_type="report",
            artifact_name=report_name,
        )

    @app.post("/reports/<report_name>/correlation")
    def report_correlation(report_name: str):
        return _build_correlation_response(
            artifact_type="report",
            artifact_name=report_name,
        )

    @app.get("/sweeps/<sweep_name>")
    def sweep_detail(sweep_name: str):
        return redirect(url_for("sweep_chart_window", sweep_name=sweep_name, focus="price"))

    @app.get("/sweeps/<sweep_name>/chart")
    def sweep_chart_window(sweep_name: str) -> str:
        focus = str(request.args.get("focus", "price")).strip().lower()
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
            autosetting_endpoint=url_for("sweep_autosetting", sweep_name=sweep_name),
            correlation_endpoint=url_for("sweep_correlation", sweep_name=sweep_name),
            save_endpoint=url_for("api_save_chart_lab_preset"),
        )
        return render_template("chart_window.html", chart=chart)

    @app.post("/sweeps/<sweep_name>/chart-preview")
    def sweep_chart_preview(sweep_name: str):
        return _build_chart_preview_response(
            artifact_type="sweep",
            artifact_name=sweep_name,
        )

    @app.post("/sweeps/<sweep_name>/autosetting")
    def sweep_autosetting(sweep_name: str):
        return _build_autosetting_response(
            artifact_type="sweep",
            artifact_name=sweep_name,
        )

    @app.post("/sweeps/<sweep_name>/correlation")
    def sweep_correlation(sweep_name: str):
        return _build_correlation_response(
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


def _run_walkforward_view(form: dict[str, object]):
    """Esegue la walk-forward e renderizza la pagina dei risultati."""
    from trading_bot.data import download_price_data, coerce_interval_date_window

    try:
        req = BacktestRequest.from_mapping(form)
    except FormValidationError as exc:
        flash(str(exc), "error")
        return _render_home(
            form_values=form,
            field_errors=_field_errors(exc),
            invalid_fields=exc.field_names,
            view=HOME_VIEW_SETUP,
            status=400,
        )

    try:
        data = download_price_data(
            symbol=req.data_symbol,
            start=req.start,
            end=req.end,
            interval=req.interval,
        )
        is_days = int(form.get("wf_is_days") or 252)
        oos_days = int(form.get("wf_oos_days") or 63)
        optimize_by = str(form.get("wf_optimize_by") or "sharpe_ratio")
        if optimize_by not in WALKFORWARD_SORT_OPTIONS:
            optimize_by = "sharpe_ratio"

        wf = run_walk_forward(
            data=data,
            strategy_id=req.strategy,
            is_days=is_days,
            oos_days=oos_days,
            optimize_by=optimize_by,
            fee_bps=req.fee_bps,
            sl_pct=req.sl_pct,
            tp_pct=req.tp_pct,
            sizing_method=req.sizing_method,
            sizing_param=req.sizing_param,
            initial_capital=req.initial_capital,
        )
    except Exception as exc:
        flash(str(exc), "error")
        return _render_home(
            form_values=form,
            view=HOME_VIEW_SETUP,
            status=400,
        )

    strategy_label = STRATEGY_OPTIONS.get(req.strategy, {}).get("label", req.strategy)
    return render_template(
        "walkforward.html",
        wf=wf,
        req=req,
        strategy_label=strategy_label,
        optimize_by_label=WALKFORWARD_SORT_OPTIONS.get(wf.optimize_by, wf.optimize_by),
        is_days=is_days,
        oos_days=oos_days,
    )


def _parse_symbols(raw: str) -> list[str]:
    """Estrae la lista di simboli da un campo di testo (separati da virgola/spazio)."""
    tokens: list[str] = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        for token in chunk.split():
            symbol = token.strip().upper()
            if symbol and symbol not in tokens:
                tokens.append(symbol)
    return tokens


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Trading Bot web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the local server.")
    parser.add_argument("--port", type=int, default=8000, help="Port for the local server.")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing generated reports.")
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=True,
                        help="Abilita Flask debug mode (default: on). Usa --no-debug per produzione.")
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
    view: str = HOME_VIEW_DASHBOARD,
    status: int = 200,
) -> str:
    values = _resolve_home_form_values(form_values)
    _store_home_draft(values)

    saved_items = list_saved_items(current_app.config["REPORTS_DIR"])
    dashboard = build_dashboard_context(saved_items=saved_items, strategies=STRATEGY_OPTIONS)
    session_items = _build_home_session_items(saved_items)
    selected_session = _select_home_session(session_items)
    dashboard["latest_session"] = session_items[0] if session_items else None

    return render_template(
        "index.html",
        form_values=values,
        field_errors=field_errors or {},
        invalid_fields=set(invalid_fields or ()),
        current_home_view=view,
        saved_items=saved_items,
        dashboard=dashboard,
        session_items=session_items,
        selected_session=selected_session,
        strategy_presets=list_strategy_presets(current_app.config["REPORTS_DIR"]),
        saved_searches=list_saved_searches(current_app.config["REPORTS_DIR"]),
        strategies=STRATEGY_OPTIONS,
        rule_logic_options=RULE_LOGIC_OPTIONS,
        intervals=INTERVAL_OPTIONS,
        costi_operazione=COSTI_OPERAZIONE,
        interval_hints=interval_helper_texts(),
        interval_lookback_days=INTRADAY_LOOKBACK_DAYS,
        run_modes=RUN_MODE_OPTIONS,
        sweep_sort_options=SWEEP_SORT_OPTIONS,
    ), status


def _field_errors(exc: FormValidationError) -> dict[str, str]:
    if not exc.display_field:
        return {}
    return {exc.display_field: str(exc)}


def _home_view_for_render(
    *,
    form_values: dict[str, object] | None,
    invalid_fields: tuple[str, ...] | list[str] | set[str] | None,
) -> str:
    return HOME_VIEW_SETUP


def _resolve_home_form_values(form_values: dict[str, object] | None = None) -> dict[str, object]:
    values = as_form_values()
    draft_values = session.get(HOME_DRAFT_SESSION_KEY)
    if isinstance(draft_values, dict):
        values.update(draft_values)

    if not form_values:
        if isinstance(values.get("active_strategies"), str):
            values["active_strategies"] = [values["active_strategies"]]
        return values

    values.update(form_values)
    if hasattr(form_values, "getlist"):
        values["active_strategies"] = form_values.getlist("active_strategies")
    elif isinstance(values.get("active_strategies"), str):
        values["active_strategies"] = [values["active_strategies"]]
    return values


def _normalize_intraday_form_window(form_values):
    normalized_form = form_values.copy() if hasattr(form_values, "copy") else form_values
    if normalized_form is None:
        return form_values

    adjusted_start, adjusted_end, adjusted = coerce_interval_date_window(
        start=str(normalized_form.get("start", "")).strip(),
        end=str(normalized_form.get("end", "")).strip(),
        interval=str(normalized_form.get("interval", "")).strip(),
    )
    if adjusted:
        normalized_form["start"] = adjusted_start
        normalized_form["end"] = adjusted_end
    return normalized_form


def _store_home_draft(values: dict[str, object]) -> None:
    active_strategies = values.get("active_strategies", [])
    if isinstance(active_strategies, str):
        normalized_active = [active_strategies]
    elif isinstance(active_strategies, (list, tuple, set)):
        normalized_active = [str(item) for item in active_strategies if str(item).strip()]
    else:
        normalized_active = []

    session[HOME_DRAFT_SESSION_KEY] = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in values.items()
        if not callable(value)
    }
    session[HOME_DRAFT_SESSION_KEY]["active_strategies"] = normalized_active


def _find_saved_report(report_name: str) -> dict[str, object]:
    for item in list_saved_items(current_app.config["REPORTS_DIR"]):
        if item.get("artifact_type") != "report":
            continue
        if str(item.get("name")) == report_name:
            return item
    abort(404)


def _build_home_session_items(saved_items: list[dict[str, object]]) -> list[dict[str, object]]:
    session_items = build_session_catalog(saved_items)
    for item in session_items:
        if item["artifact_type"] == "sweep":
            item["open_url"] = url_for("sweep_chart_window", sweep_name=item["name"], focus="price")
            item["open_label"] = "Apri grafico"
            item["resume_url"] = ""
        else:
            item["open_url"] = url_for("report_chart_window", report_name=item["name"], focus="price")
            item["open_label"] = "Apri grafico"
            item["resume_url"] = url_for("resume_backtest", report_name=item["name"])
    return session_items


def _select_home_session(session_items: list[dict[str, object]]) -> dict[str, object] | None:
    if not session_items:
        return None

    requested_name = str(request.args.get("session", "")).strip()
    if requested_name:
        for item in session_items:
            if item["name"] == requested_name:
                return item
    return session_items[0]


def _attach_chart_lab(
    chart: dict[str, object],
    *,
    preview_endpoint: str,
    autosetting_endpoint: str = "",
    correlation_endpoint: str = "",
    save_endpoint: str = "",
) -> dict[str, object]:
    metadata = chart["metadata"]
    chart_lab_state = build_chart_lab_state(metadata)
    baseline_label = chart_lab_state["baseline_label"]

    return {
        **chart,
        "chart_lab": {
            **chart_lab_state,
            "preview_endpoint": preview_endpoint,
            "autosetting_endpoint": autosetting_endpoint,
            "correlation_endpoint": correlation_endpoint,
            "save_endpoint": save_endpoint,
            # Metadati del report necessari per salvare un preset dal chart lab
            "report_symbol": str(metadata.get("symbol", "")),
            "report_start": str(metadata.get("start", "")),
            "report_end": str(metadata.get("end", "")),
            "report_interval": str(metadata.get("interval", "1d")),
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
            "indicator_payload": chart["chart_payload"].get("indicators", []),
            "validation_cards": chart["validation"]["cards"],
            "validation_checks": chart["validation"]["checks"],
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
        preview_summary = enrich_summary_with_equity_curve(
            summary=result.summary,
            equity_curve=result.equity_curve,
        )
        indicator_payload = build_preview_indicator_payload(
            backtest_request=preview_request,
            market_data=market_data,
        )
        validation = build_result_validation_snapshot(
            summary=preview_summary,
            equity_curve=result.equity_curve,
            trades=result.trades,
        )
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
        or "Setup iniziale del report"
    )

    return jsonify(
        {
            "preview_label": preview_request.strategy_label,
            "active_rule_labels": [rule.label for rule in preview_request.active_rules()],
            "chart_payload": build_chart_payload(
                equity_curve=result.equity_curve,
                trades=result.trades,
                focus="equity",
                interval=str(chart["metadata"].get("interval", "")),
                indicators=indicator_payload,
                signal_context=preview_request.metadata(),
            ),
            "summary_cards": build_summary_cards(preview_summary),
            "comparison_cards": build_live_comparison_cards(
                preview_summary=preview_summary,
                baseline_summary=chart["summary"],
                baseline_label=baseline_label,
                preview_label=preview_request.strategy_label,
            ),
            "trade_preview": build_trade_preview(result.trades, limit=10),
            "indicator_payload": indicator_payload,
            "validation_cards": validation["cards"],
            "validation_checks": validation["checks"],
        }
    )


def _build_correlation_response(*, artifact_type: str, artifact_name: str):
    try:
        chart, market_data_path = _load_chart_preview_source(
            artifact_type=artifact_type,
            artifact_name=artifact_name,
        )
        market_data = load_market_data_from_saved_equity(market_data_path)
    except FileNotFoundError:
        abort(404)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    payload = request.get_json(silent=True) or {}
    signals: dict[str, pd.Series] = {}
    failed: list[str] = []

    for strategy_id, spec in STRATEGY_SPECS.items():
        try:
            params = parse_strategy_parameters(strategy_id, payload)
            signal = build_strategy_signal(strategy_id, market_data, params).fillna(0.0)
            signals[spec.label] = signal
        except Exception:
            failed.append(strategy_id)

    if len(signals) < 2:
        return jsonify({"error": "Meno di 2 strategie calcolabili sul dataset corrente."}), 400

    corr = pd.DataFrame(signals).dropna().corr().round(3)
    return jsonify({
        "labels": list(corr.columns),
        "matrix": corr.values.tolist(),
        "failed_strategies": failed,
    })


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


def _build_autosetting_response(*, artifact_type: str, artifact_name: str):
    try:
        chart, market_data_path = _load_chart_preview_source(
            artifact_type=artifact_type,
            artifact_name=artifact_name,
        )
        payload = request.get_json(silent=True) or {}
        strategy_id = str(payload.get("strategy_id", "")).strip()
        if not strategy_id:
            return jsonify({"error": "strategy_id mancante."}), 400

        fee_bps = float(payload.get("fee_bps", chart.get("summary", {}).get("fee_bps") or 5))
        initial_capital = float(
            chart.get("summary", {}).get("initial_capital") or 10_000.0
        )
        scan_mode = str(payload.get("scan_mode", "rapida")).strip()
        if scan_mode not in ("rapida", "media", "lunga", "xl"):
            scan_mode = "rapida"

        market_data = load_market_data_from_saved_equity(market_data_path)
        autosetting_result = run_autosetting(
            strategy_id=strategy_id,
            data=market_data,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            scan_mode=scan_mode,
        )
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(autosetting_result)


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
