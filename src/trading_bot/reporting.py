from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError
from trading_bot.strategies import (
    STRATEGY_SPECS,
    adx_components,
    build_combined_signal,
    build_strategy_signal,
    commodity_channel_index,
    on_balance_volume,
    relative_strength_index,
    williams_r_indicator,
)

SUMMARY_LABELS = {
    # Nomi in italiano corrente: il termine tecnico sta nella spiegazione a
    # comparsa (METRIC_TOOLTIPS), non nell'etichetta. Chi apre il report vuole
    # sapere cosa significa il numero, non come si chiama in gergo.
    "initial_capital": "Soldi messi all'inizio",
    "final_equity": "Quanto ti resta alla fine",
    "gross_final_equity": "Quanto ti resterebbe senza costi",
    "benchmark_final_equity": "Se avessi solo comprato e aspettato",
    "total_return_pct": "Guadagno totale",
    "annual_return_pct": "Guadagno medio all'anno",
    "annual_volatility_pct": "Quanto oscilla",
    "sharpe_ratio": "Guadagno rispetto al rischio",
    "sortino_ratio": "Guadagno rispetto alle discese",
    "calmar_ratio": "Guadagno rispetto al calo peggiore",
    "max_drawdown_pct": "Il calo peggiore",
    "trade_count": "Operazioni fatte",
    "win_rate_pct": "Operazioni chiuse in guadagno",
    "profit_factor": "Guadagni contro perdite",
    "avg_win_pct": "Guadagno medio quando va bene",
    "avg_loss_pct": "Perdita media quando va male",
    "expectancy_pct": "Risultato medio per operazione",
    "sl_tp_exit_count": "Chiusure automatiche (stop e obiettivo)",
    "end_of_day_exit_count": "Chiusure serali",
    "exposure_pct": "Tempo passato a mercato",
    "long_exposure_pct": "Tempo puntando sul rialzo",
    "short_exposure_pct": "Tempo puntando sul ribasso",
    "short_trade_count": "Operazioni al ribasso",
    "wiped_out": "Capitale azzerato",
    "wiped_out_date": "Giorno dell'azzeramento",
    "benchmark_return_pct": "Comprando e basta",
    "benchmark_max_drawdown_pct": "Calo peggiore comprando e basta",
    "excess_return_pct": "Differenza con comprare e basta",
    "fees_paid": "Commissioni pagate",
    "slippage_paid": "Costo dello scarto di prezzo",
    "trading_costs_paid": "Costi totali",
    "fees_paid_pct_initial_capital": "Costi sul capitale iniziale",
    "fee_drag_equity": "Quanto ti sono costati i costi",
}

# Glossario tooltip per le metriche e gli strumenti: testo conciso (1-2 frasi)
# mostrato in hover/info-icon nei template. Le chiavi corrispondono a chiavi
# di SUMMARY_LABELS o a id di strumenti UI (es. "autosetting", "walkforward").
METRIC_TOOLTIPS: dict[str, str] = {
    "trading_costs_paid": "Commissioni piu' scarto di prezzo: tutto quello che l'operare ti e' costato.",
    "slippage_paid": "Quanto e' costato lo scarto fra il prezzo visto a schermo e quello davvero ottenuto. In gergo: slippage.",
    "wiped_out_date": "Il giorno in cui il capitale si e' azzerato e il test si e' fermato.",
    "wiped_out": "Vero se il capitale si e' azzerato: succede solo con la vendita allo scoperto, dove la perdita non ha un tetto.",
    "end_of_day_exit_count": "Quante volte la posizione e' stata chiusa prima della chiusura di giornata, per non restare esposti durante la notte.",
    "short_trade_count": "Quante delle operazioni puntavano sulla discesa invece che sulla salita.",
    "short_exposure_pct": "La fetta di tempo passata puntando sul ribasso (vendita allo scoperto).",
    "long_exposure_pct": "La fetta di tempo passata puntando sul rialzo, cioe' avendo comprato.",
    "benchmark_max_drawdown_pct": "Il calo peggiore che avrebbe sopportato chi ha solo comprato e tenuto: utile per capire se la strategia ti ha risparmiato qualcosa.",
    "initial_capital": "I soldi con cui parte il test. Non e' denaro vero: serve a calcolare le percentuali.",
    # ── Rendimento ────────────────────────────────────────────────────
    "total_return_pct":      "Variazione percentuale dell'equity dall'inizio alla fine. Non considera la durata del periodo.",
    "annual_return_pct": "Il guadagno medio per ogni anno, tenendo conto dell'interesse composto. In gergo: CAGR.",
    "benchmark_return_pct": "Quanto avresti ottenuto comprando e basta, senza fare nulla per tutto il periodo: e' il risultato da battere.",
    "excess_return_pct": "Quanto hai guadagnato in piu' (o in meno) rispetto a comprare il primo giorno e non fare piu' niente. E' il confronto che conta.",
    "final_equity": "I soldi che ti ritrovi alla fine, commissioni e scarti di prezzo gia' pagati.",
    "gross_final_equity": "Quanto ti ritroveresti se operare non costasse niente: il confronto mostra il peso dei costi.",
    "benchmark_final_equity": "Quanto ti ritroveresti avendo comprato il primo giorno e aspettato senza fare altro.",
    # ── Rischio ───────────────────────────────────────────────────────
    "annual_volatility_pct": "Di quanto oscilla il capitale in un anno: piu' e' alto, piu' il percorso e' movimentato. In gergo: volatilita' annualizzata.",
    "max_drawdown_pct": "Quanto e' sceso il capitale dal suo punto piu' alto prima di risalire: e' il momento in cui avresti avuto piu' voglia di mollare. In gergo: max drawdown.",
    "sharpe_ratio": "Quanto guadagni in rapporto a quanto oscilla il capitale: sopra 1 e' buono, sopra 2 e' raro. In gergo: Sharpe ratio.",
    "sortino_ratio": "Come il precedente, ma conta solo le oscillazioni verso il basso: premia chi scende poco anche se sale a scatti. In gergo: Sortino ratio.",
    "calmar_ratio": "Quante volte il guadagno di un anno copre il calo peggiore che avresti sopportato. In gergo: Calmar ratio.",
    # ── Trade ─────────────────────────────────────────────────────────
    "trade_count":           "Numero totale di operazioni chiuse nel periodo.",
    "win_rate_pct": "Su cento operazioni chiuse, quante sono finite in guadagno. Attenzione: si puo' guadagnare vincendo poche volte e perdere vincendo spesso. In gergo: win rate.",
    "profit_factor": "Quanti euro hai guadagnato per ogni euro perso. Sotto 1 la strategia perde. In gergo: profit factor.",
    "avg_win_pct":           "Guadagno medio per ogni trade vincente.",
    "avg_loss_pct":          "Perdita media per ogni trade in loss (valore negativo).",
    "expectancy_pct": "Quanto rende in media una singola operazione, buone e cattive messe insieme. In gergo: expectancy.",
    # ── Costi ─────────────────────────────────────────────────────────
    "fees_paid":             "Totale commissioni pagate (basate sulla fee in basis points).",
    "fees_paid_pct_initial_capital": "Peso delle fee sul capitale iniziale: utile per capire se i costi erodono la strategia.",
    "fee_drag_equity":       "Differenza in euro tra equity lorda (senza fee) e netta. Quanto ti sono costate operativamente le commissioni.",
    # ── Posizione ─────────────────────────────────────────────────────
    "exposure_pct": "La fetta di tempo in cui i tuoi soldi erano davvero investiti invece che fermi. In gergo: esposizione.",
    "sl_tp_exit_count":      "Numero di uscite forzate da stop loss o take profit. Indica quanto i protettori intervengono.",
    # ── Strumenti UI ──────────────────────────────────────────────────
    "autosetting":           "Scansiona una griglia di parametri sul training set (70%) e valida i migliori sull'out-of-sample. Evidenzia overfitting.",
    "walkforward":           "Ottimizza i parametri su finestre IS scorrevoli e li testa subito dopo su OOS. Più realistico dell'autosetting singolo.",
    "scan_modes":            "Rapida: griglia base. Media: 2× più densa. Lunga: 4×. XL: 8× (può richiedere minuti).",
    "sl_pct":                "Stop loss: percentuale di perdita massima per trade prima della chiusura forzata. Vuoto = disabilitato.",
    "tp_pct":                "Take profit: percentuale di guadagno per chiudere automaticamente il trade. Vuoto = disabilitato.",
    "sizing_full":           "Tutto il capitale in posizione quando attiva (default). Massimo rendimento ma anche massimo rischio.",
    "sizing_fixed":          "Frazione fissa del capitale (es. 50%). Riduce l'esposizione in modo uniforme.",
    "sizing_vol_target":     "Adatta la dimensione alla volatilità: posizione grande in mercati calmi, piccola in mercati nervosi.",
    "rule_logic_all":        "AND: il segnale è long solo quando TUTTE le regole sono long. Selettivo, pochi trade.",
    "rule_logic_any":        "OR: il segnale è long quando almeno UNA regola è long. Permissivo, molti trade.",
    "correlation":           "Calcola la correlazione tra i segnali generati da tutte le strategie sui dati attuali. Strategie poco correlate sono più efficaci se combinate.",
}


def metric_tooltip(key: str) -> str:
    """Restituisce il testo del tooltip per una metrica/strumento, o '' se sconosciuto."""
    return METRIC_TOOLTIPS.get(key, "")

REPORT_NAME_PATTERN = re.compile(r"^(?P<symbol>.+)-(?P<strategy>[a-z_]+)-(?P<timestamp>\d{8}-\d{6})$")
EMPTY_TRADE_COLUMNS = (
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "pnl_pct",
    "holding_days",
)


def list_saved_items(output_dir: str | Path) -> list[dict[str, object]]:
    output_path = Path(output_dir)
    if not output_path.exists():
        return []

    items: list[dict[str, object]] = []
    for item_dir in output_path.iterdir():
        if not item_dir.is_dir():
            continue
        summary_file = item_dir / "summary.json"
        if not summary_file.exists():
            continue
        metadata = read_report_metadata(item_dir)
        artifact_type = str(metadata.get("artifact_type", "report"))
        if artifact_type == "sweep":
            items.append(_build_sweep_list_item(item_dir=item_dir, metadata=metadata))
        else:
            items.append(_build_report_list_item(report_dir=item_dir, metadata=metadata))

    items.sort(
        key=lambda item: (
            str(item["created_at"]),
            item["name"],
        ),
        reverse=True,
    )
    return items


def list_reports(output_dir: str | Path) -> list[dict[str, object]]:
    return [item for item in list_saved_items(output_dir) if item.get("artifact_type") == "report"]


def load_report(output_dir: str | Path, report_name: str) -> dict[str, object]:
    report_dir = Path(output_dir) / report_name
    if not report_dir.exists():
        raise FileNotFoundError(f"Report '{report_name}' not found.")

    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    metadata = hydrate_report_metadata(
        metadata=read_report_metadata(report_dir),
        report_dir=report_dir,
        summary=summary,
    )
    equity_curve = _read_equity_curve(report_dir)
    trades = _read_trades(report_dir / "trades.csv")
    comparison = build_comparison(summary)

    return {
        "artifact_type": "report",
        "name": report_name,
        "path": report_dir,
        "summary": summary,
        "metadata": metadata,
        "verdetto": build_plain_verdict(summary, barre=len(equity_curve)),
        "summary_cards": build_summary_cards(summary),
        "comparison": comparison,
        "overview_cards": build_report_overview_cards(summary, comparison),
        "metric_sections": build_report_metric_sections(summary, comparison),
        "insights": build_report_insights(summary, comparison),
        "meta_chips": build_report_meta_chips(metadata, summary),
        "equity_chart": build_line_chart(
            {
                "Strategy": equity_curve["equity"],
                "Buy & hold": equity_curve["benchmark_equity"],
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
        ),
        "drawdown_chart": build_line_chart(
            {"Drawdown": equity_curve["drawdown"] * 100},
            colors={"Drawdown": "#ef4444"},
        ),
        "equity_curve_rows": equity_curve.tail(20).to_dict(orient="records"),
        "trades": trades.fillna("").to_dict(orient="records"),
        "trade_preview": build_trade_preview(trades, limit=20),
    }


def load_sweep(output_dir: str | Path, sweep_name: str) -> dict[str, object]:
    sweep_dir = Path(output_dir) / sweep_name
    if not sweep_dir.exists():
        raise FileNotFoundError(f"Sweep '{sweep_name}' not found.")

    metadata = read_report_metadata(sweep_dir)
    summary = _read_json(sweep_dir / "summary.json")
    results = pd.read_csv(sweep_dir / "results.csv")
    best_summary = enrich_summary(_read_json(sweep_dir / "best_summary.json"), sweep_dir)
    best_equity_curve = _read_best_equity_curve(sweep_dir)
    best_trades = _read_trades(sweep_dir / "best_trades.csv")

    top_results = results.sort_values(by=["rank"], ascending=True).head(40).copy()
    ranking_chart = build_line_chart(
        {"Top total return": sample_series(top_results["total_return_pct"], max_points=40)},
        colors={"Top total return": "#0f766e"},
        width=860,
        height=220,
        padding=24,
    )

    # Parametri ottimali: nuovo formato (best_parameters dict) o legacy fast/slow
    best_parameters = summary.get("best_parameters")
    if not isinstance(best_parameters, dict) or not best_parameters:
        best_parameters = {
            name: summary.get(f"best_{name}", "")
            for name in ("fast", "slow")
            if f"best_{name}" in summary
        }

    # Colonne della top table: rank, tutti i parametri della strategia, poi metriche
    param_columns = [name for name in best_parameters.keys() if name in results.columns]
    metric_columns = [
        col for col in (
            "total_return_pct", "benchmark_return_pct", "excess_return_pct",
            "sharpe_ratio", "max_drawdown_pct", "fees_paid",
        ) if col in results.columns
    ]

    return {
        "artifact_type": "sweep",
        "name": sweep_name,
        "path": sweep_dir,
        "metadata": metadata,
        "summary": summary,
        "summary_cards": build_sweep_summary_cards(summary),
        "best_summary_cards": build_summary_cards(best_summary),
        "best_parameters": best_parameters,
        "best_comparison": build_comparison(best_summary),
        "best_equity_chart": build_line_chart(
            {
                "Strategy": best_equity_curve["equity"],
                "Buy & hold": best_equity_curve["benchmark_equity"],
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
        ),
        "best_drawdown_chart": build_line_chart(
            {"Drawdown": best_equity_curve["drawdown"] * 100},
            colors={"Drawdown": "#ef4444"},
        ),
        "ranking_chart": ranking_chart,
        "top_results": top_results.to_dict(orient="records"),
        "top_results_columns": ["rank", *param_columns, *metric_columns],
        "best_trade_preview": build_trade_preview(best_trades, limit=20),
    }


def load_report_chart_window(output_dir: str | Path, report_name: str, focus: str = "equity") -> dict[str, object]:
    report_dir = Path(output_dir) / report_name
    if not report_dir.exists():
        raise FileNotFoundError(f"Report '{report_name}' not found.")

    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    equity_curve = _read_equity_curve(report_dir)
    metadata = hydrate_report_metadata(
        metadata=read_report_metadata(report_dir),
        report_dir=report_dir,
        summary=summary,
    )
    trades = _read_trades(report_dir / "trades.csv")

    return _build_chart_window_context(
        artifact_type="report",
        artifact_name=report_name,
        metadata=metadata,
        summary=summary,
        equity_curve=equity_curve,
        trades=trades,
        focus=focus,
        title=f"{metadata.get('symbol') or report_name} - {metadata.get('strategy_label') or metadata.get('strategy') or 'Backtest'}",
        subtitle=(
            f"Periodo {metadata.get('start', 'n/a')} -> {metadata.get('end', 'n/a')} - "
            f"Intervallo {metadata.get('interval', 'n/a')} - Fee {metadata.get('fee_bps', 'n/a')} bps"
            f"{_market_feed_suffix(metadata)}"
        ),
    )


def load_sweep_chart_window(output_dir: str | Path, sweep_name: str, focus: str = "equity") -> dict[str, object]:
    sweep_dir = Path(output_dir) / sweep_name
    if not sweep_dir.exists():
        raise FileNotFoundError(f"Sweep '{sweep_name}' not found.")

    metadata = read_report_metadata(sweep_dir)
    summary = _read_json(sweep_dir / "summary.json")
    best_summary = enrich_summary(_read_json(sweep_dir / "best_summary.json"), sweep_dir)
    best_equity_curve = _read_best_equity_curve(sweep_dir)
    best_trades = _read_trades(sweep_dir / "best_trades.csv")
    parameter_labels = metadata.get("parameter_labels", {"fast": "Fast", "slow": "Slow"})
    marker_metadata = _sweep_signal_context(metadata=metadata, summary=summary)

    # Costruisce in modo generico la stringa "Best <param> N / <param> M" per
    # qualsiasi numero di parametri ottimizzati.
    best_parameters = summary.get("best_parameters")
    if not isinstance(best_parameters, dict) or not best_parameters:
        best_parameters = {
            name: summary.get(f"best_{name}")
            for name in ("fast", "slow")
            if f"best_{name}" in summary
        }
    best_params_label = " / ".join(
        f"{parameter_labels.get(name, name.title())} {value}"
        for name, value in best_parameters.items()
        if value is not None and value != ""
    ) or "parametri n/a"

    return _build_chart_window_context(
        artifact_type="sweep",
        artifact_name=sweep_name,
        metadata=marker_metadata,
        summary=best_summary,
        equity_curve=best_equity_curve,
        trades=best_trades,
        focus=focus,
        title=f"{metadata.get('symbol') or sweep_name} - Best {metadata.get('strategy_label') or metadata.get('strategy') or 'Sweep'}",
        subtitle=(
            f"Best {best_params_label} - "
            f"Periodo {metadata.get('start', 'n/a')} -> {metadata.get('end', 'n/a')} - "
            f"Intervallo {metadata.get('interval', 'n/a')}"
            f"{_market_feed_suffix(metadata)}"
        ),
    )


def _market_feed_suffix(metadata: dict[str, object]) -> str:
    symbol = str(metadata.get("symbol") or "").strip().upper()
    data_symbol = str(metadata.get("data_symbol") or "").strip().upper()
    if not symbol or not data_symbol or symbol == data_symbol:
        return ""
    return f" - Feed {data_symbol}"


def _sweep_signal_context(*, metadata: dict[str, object], summary: dict[str, object]) -> dict[str, object]:
    enriched = dict(metadata)
    strategy_id = str(metadata.get("strategy") or metadata.get("primary_strategy") or "").strip()
    if strategy_id not in STRATEGY_SPECS:
        return enriched

    default_parameters = STRATEGY_SPECS[strategy_id].defaults()
    best_parameters = dict(default_parameters)
    # Nuovo formato: best_parameters dict completo
    summary_best = summary.get("best_parameters")
    if isinstance(summary_best, dict):
        for name, value in summary_best.items():
            if name in best_parameters:
                best_parameters[name] = value
    # Retro-compat con i sweep vecchi che salvavano best_fast/best_slow
    for legacy_key, param_name in (("best_fast", "fast"), ("best_slow", "slow")):
        if legacy_key in summary and param_name in best_parameters:
            best_parameters[param_name] = summary.get(legacy_key)

    strategy_label = str(
        metadata.get("strategy_label")
        or metadata.get("primary_strategy_label")
        or STRATEGY_SPECS[strategy_id].label
    )
    enriched.setdefault("primary_strategy", strategy_id)
    enriched.setdefault("primary_strategy_label", strategy_label)
    enriched["parameters"] = best_parameters
    enriched["active_strategy_ids"] = [strategy_id]
    enriched["active_rules"] = [
        {
            "slot": "rule_1",
            "strategy": strategy_id,
            "strategy_label": strategy_label,
            "parameters": best_parameters,
        }
    ]
    return enriched


def hydrate_report_metadata(
    *,
    metadata: dict[str, object],
    report_dir: Path,
    summary: dict[str, object],
) -> dict[str, object]:
    enriched = dict(metadata)
    try:
        equity_curve = _read_equity_curve(report_dir)
    except FileNotFoundError:
        equity_curve = pd.DataFrame()

    if "strategy_label" not in enriched and enriched.get("strategy"):
        enriched["strategy_label"] = str(enriched["strategy"]).replace("_", " ").title()

    start_label, end_label = _infer_report_range(equity_curve)
    if not enriched.get("start") and start_label:
        enriched["start"] = start_label
    if not enriched.get("end") and end_label:
        enriched["end"] = end_label
    if not enriched.get("interval"):
        inferred_interval = _infer_interval_label(equity_curve)
        if inferred_interval:
            enriched["interval"] = inferred_interval
    if "initial_capital" not in enriched and "initial_capital" in summary:
        enriched["initial_capital"] = summary.get("initial_capital")
    return enriched


def build_report_meta_chips(summary_metadata: dict[str, object], summary: dict[str, object]) -> list[dict[str, str]]:
    period_start = str(summary_metadata.get("start", "")).strip()
    period_end = str(summary_metadata.get("end", "")).strip()
    period_value = " -> ".join(part for part in (period_start, period_end) if part) or "n/d"

    trade_count_value = _to_float(summary.get("trade_count"))
    fee_bps_value = _to_float(summary_metadata.get("fee_bps"))

    chips = [
        {"label": "Periodo", "value": period_value},
        {"label": "Ogni barra", "value": str(summary_metadata.get("interval", "n/d"))},
        {
            "label": "Costo per operazione",
            "value": (
                f"{fee_bps_value / 100:.2f}%" if fee_bps_value is not None else "n/d"
            ),
        },
        {
            "label": "Operazioni",
            "value": str(int(trade_count_value)) if trade_count_value is not None else "n/d",
        },
    ]
    return chips


def build_report_overview_cards(
    summary: dict[str, object],
    comparison: dict[str, object],
) -> list[dict[str, str]]:
    delta_value = _to_float(comparison.get("delta_pct"))
    drawdown_value = _to_float(summary.get("max_drawdown_pct"))
    sharpe_value = _to_float(summary.get("sharpe_ratio"))

    return [
        {
            "label": "Rendimento strategia",
            "value": _format_percent_metric(summary.get("total_return_pct")),
            "hint": f"Equity finale {_format_number_metric(summary.get('final_equity'))}",
            "tone": "neutral",
        },
        {
            "label": "Buy & hold",
            "value": _format_percent_metric(summary.get("benchmark_return_pct")),
            "hint": f"Equity finale {_format_number_metric(summary.get('benchmark_final_equity'))}",
            "tone": "neutral",
        },
        {
            "label": "Delta vs hold",
            "value": _format_percent_metric(delta_value, signed=True),
            "hint": comparison.get("verdict", "Confronto col benchmark"),
            "tone": _delta_tone(delta_value),
        },
        {
            "label": "Il calo peggiore",
            "value": _format_percent_metric(drawdown_value),
            "hint": "Quanto è sceso il capitale dal punto più alto.",
            "tone": _drawdown_tone(drawdown_value),
        },
        {
            "label": "Guadagno rispetto al rischio",
            "value": _format_ratio_metric(sharpe_value),
            "hint": _interpret_sharpe(sharpe_value),
            "tone": _sharpe_tone(sharpe_value),
        },
    ]


def build_report_metric_sections(
    summary: dict[str, object],
    comparison: dict[str, object],
) -> list[dict[str, object]]:
    delta_value = _to_float(comparison.get("delta_pct"))
    trade_count_value = _to_float(summary.get("trade_count"))
    exposure_value = _to_float(summary.get("exposure_pct"))
    drawdown_value = _to_float(summary.get("max_drawdown_pct"))
    sharpe_value = _to_float(summary.get("sharpe_ratio"))
    fee_drag_value = _to_float(summary.get("fee_drag_equity"))

    return [
        {
            "eyebrow": "performance",
            "title": "Rendimento e benchmark",
            "cards": [
                {
                    "label": "Strategia",
                    "value": _format_percent_metric(summary.get("total_return_pct")),
                    "hint": f"Capitale finale {_format_number_metric(summary.get('final_equity'))}",
                    "tone": "neutral",
                },
                {
                    "label": "Buy & hold",
                    "value": _format_percent_metric(summary.get("benchmark_return_pct")),
                    "hint": f"Capitale finale {_format_number_metric(summary.get('benchmark_final_equity'))}",
                    "tone": "neutral",
                },
                {
                    "label": "Differenza",
                    "value": _format_percent_metric(delta_value, signed=True),
                    "hint": "Positivo = meglio del benchmark",
                    "tone": _delta_tone(delta_value),
                },
                {
                    "label": "Rendimento annuo",
                    "value": _format_percent_metric(summary.get("annual_return_pct")),
                    "hint": "Media annualizzata del test",
                    "tone": "neutral",
                },
            ],
        },
        {
            "eyebrow": "rischio",
            "title": "Rischio e tenuta",
            "cards": [
                {
                    "label": "Il calo peggiore",
                    "value": _format_percent_metric(drawdown_value),
                    "hint": "Peggior calo dal massimo precedente",
                    "tone": _drawdown_tone(drawdown_value),
                },
                {
                    "label": "Guadagno rispetto al rischio",
                    "value": _format_ratio_metric(sharpe_value),
                    "hint": _interpret_sharpe(sharpe_value),
                    "tone": _sharpe_tone(sharpe_value),
                },
                {
                    "label": "Numero trade",
                    "value": str(int(trade_count_value)) if trade_count_value is not None else "n/d",
                    "hint": "Operazioni chiuse nel periodo",
                    "tone": "neutral",
                },
                {
                    "label": "Esposizione",
                    "value": _format_percent_metric(exposure_value),
                    "hint": "Tempo medio in posizione sul mercato",
                    "tone": "neutral",
                },
            ],
        },
        {
            "eyebrow": "costi",
            "title": "Costi e attrito",
            "cards": [
                {
                    "label": "Spese totali",
                    "value": _format_number_metric(summary.get("fees_paid")),
                    "hint": "Commissioni sommate nel periodo",
                    "tone": "neutral",
                },
                {
                    "label": "Spese sul capitale",
                    "value": _format_percent_metric(summary.get("fees_paid_pct_initial_capital")),
                    "hint": "Quanto pesano sui soldi messi all'inizio",
                    "tone": "neutral",
                },
                {
                    "label": "Quanto ti resterebbe senza costi",
                    "value": _format_number_metric(summary.get("gross_final_equity")),
                    "hint": "Il risultato se operare fosse gratis",
                    "tone": "neutral",
                },
                {
                    "label": "Quanto ti sono costati i costi",
                    "value": _format_number_metric(fee_drag_value),
                    "hint": "Differenza fra il risultato con e senza costi",
                    "tone": "warning" if fee_drag_value not in (None, 0) else "neutral",
                },
            ],
        },
    ]


def build_report_insights(summary: dict[str, object], comparison: dict[str, object]) -> list[dict[str, str]]:
    strategy_return = _format_percent_metric(summary.get("total_return_pct"))
    hold_return = _format_percent_metric(summary.get("benchmark_return_pct"))
    delta_value = _to_float(comparison.get("delta_pct"))
    drawdown_value = _to_float(summary.get("max_drawdown_pct"))
    fees_value = _format_number_metric(summary.get("fees_paid"))
    fee_pct_value = _format_percent_metric(summary.get("fees_paid_pct_initial_capital"))
    trade_count_value = _to_float(summary.get("trade_count"))
    exposure_value = _format_percent_metric(summary.get("exposure_pct"))

    return [
        {
            "title": "Confronto col benchmark",
            "body": (
                f"La strategia ha chiuso a {strategy_return} contro {hold_return} del buy & hold. "
                f"Delta finale {_format_percent_metric(delta_value, signed=True)}."
            ),
            "tone": _delta_tone(delta_value),
        },
        {
            "title": "Rischio massimo sopportato",
            "body": (
                f"Nel momento peggiore il portafoglio era a {_format_percent_metric(drawdown_value)} "
                "dal massimo precedente."
            ),
            "tone": _drawdown_tone(drawdown_value),
        },
        {
            "title": "Costo operativo",
            "body": (
                f"Hai pagato {fees_value} di fee, pari a {fee_pct_value} del capitale iniziale."
            ),
            "tone": "neutral",
        },
        {
            "title": "Attivita' del sistema",
            "body": (
                f"Il sistema ha chiuso {int(trade_count_value) if trade_count_value is not None else 'n/d'} trade "
                f"con esposizione media {exposure_value}."
            ),
            "tone": "neutral",
        },
    ]


# ── Verdetto in lingua semplice ──────────────────────────────────────────────
# Il report è nato come strumento da terminale: grafico, metriche, controlli.
# Chi lo apre senza saperne di finanza però ha una sola domanda — "com'è
# andata?" — e prima di questo riquadro la pagina non gliela rispondeva da
# nessuna parte.

# Sotto questo numero di operazioni il risultato dipende più dal caso che dalla
# strategia: dieci lanci di moneta possono uscire tutti testa.
POCHE_OPERAZIONI = 10
# Sotto un anno di storia una strategia non ha visto abbastanza mercato.
POCHE_BARRE = 180


def build_plain_verdict(
    summary: dict[str, object], barre: int | None = None
) -> dict[str, object]:
    """Traduce il riepilogo in una frase che si capisce senza saper leggere i numeri.

    Restituisce ``{tono, titolo, frase, confronto, avvisi}``: il tono guida il
    colore del riquadro, gli avvisi dicono quando il risultato non è
    abbastanza solido per farci affidamento.
    """
    capitale = _to_float(summary.get("initial_capital")) or 0.0
    finale = _to_float(summary.get("final_equity")) or 0.0
    mercato = _to_float(summary.get("benchmark_final_equity")) or 0.0
    guadagno = finale - capitale
    margine = finale - mercato
    operazioni = int(_to_float(summary.get("trade_count")) or 0)

    if summary.get("wiped_out"):
        return {
            "tono": "negative",
            "titolo": "Capitale azzerato",
            "frase": (
                f"Il {summary.get('wiped_out_date', '')} una posizione al ribasso ha perso più "
                f"dell'intero capitale: dei {_euro(capitale)} di partenza non è rimasto niente, "
                "e da quel punto il test si ferma."
            ),
            "confronto": (
                "È il rischio specifico della vendita allo scoperto: se il prezzo raddoppia, "
                "chi ha puntato sulla discesa perde tutto."
            ),
            "avvisi": _avvisi(summary, barre, operazioni),
        }

    if guadagno >= 0:
        titolo = f"Avresti guadagnato {_euro(guadagno)}"
        tono = "positive"
    else:
        titolo = f"Avresti perso {_euro(abs(guadagno))}"
        tono = "negative"

    frase = (
        f"Partendo da {_euro(capitale)}, alla fine del periodo ti saresti trovato "
        f"{_euro(finale)}."
    )

    if mercato > 0:
        if margine >= 0:
            confronto = (
                f"Comprando e basta il primo giorno, senza fare più niente, ne avresti avuti "
                f"{_euro(mercato)}: questa strategia ti ha fatto guadagnare {_euro(margine)} "
                "in più di quanto avresti ottenuto stando fermo."
            )
        else:
            confronto = (
                f"Comprando e basta il primo giorno, senza fare più niente, ne avresti avuti "
                f"{_euro(mercato)}: questa strategia ti è costata {_euro(abs(margine))} "
                "rispetto a non fare niente."
            )
            # Guadagnare meno che stando fermi non è un buon risultato, anche
            # se il numero è positivo.
            tono = "neutral" if guadagno >= 0 else "negative"
    else:
        confronto = ""

    return {
        "tono": tono,
        "titolo": titolo,
        "frase": frase,
        "confronto": confronto,
        "avvisi": _avvisi(summary, barre, operazioni),
    }


def _avvisi(summary: dict[str, object], barre: int | None, operazioni: int) -> list[str]:
    """Quando il risultato non è abbastanza solido per farci affidamento."""
    avvisi: list[str] = []

    if operazioni == 0:
        avvisi.append(
            "La strategia non ha mai comprato né venduto in tutto il periodo: "
            "non c'è nessun risultato da leggere."
        )
    elif operazioni < POCHE_OPERAZIONI:
        avvisi.append(
            f"Solo {operazioni} operazioni in tutto il periodo: troppo poche per distinguere "
            "una strategia che funziona da una serie fortunata. Con dieci lanci di moneta "
            "può uscire testa ogni volta."
        )

    if barre is not None and barre < POCHE_BARRE:
        avvisi.append(
            "Il periodo di prova è breve: la strategia non ha ancora visto abbastanza mercato "
            "(né una discesa vera, probabilmente). Allarga le date prima di fidarti."
        )

    caduta = _to_float(summary.get("max_drawdown_pct"))
    if caduta is not None and caduta <= -30:
        avvisi.append(
            f"Lungo la strada avresti visto il capitale scendere del {abs(caduta):.0f}% dal suo "
            "massimo: chiediti se saresti riuscito a non vendere in quel momento."
        )

    costi = _to_float(summary.get("trading_costs_paid"))
    guadagno_lordo = (_to_float(summary.get("gross_final_equity")) or 0.0) - (
        _to_float(summary.get("initial_capital")) or 0.0
    )
    if costi and guadagno_lordo > 0 and costi > guadagno_lordo * 0.5:
        avvisi.append(
            f"Commissioni e slippage si sono mangiati {_euro(costi)}, cioè più di metà di quanto "
            "la strategia aveva guadagnato prima dei costi: opera troppo spesso."
        )

    return avvisi


def _euro(valore: float) -> str:
    """Importo in euro, senza decimali: qui i centesimi sono solo rumore."""
    return f"{valore:,.0f} €".replace(",", ".")


def build_summary_cards(summary: dict[str, object]) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for key in (
        "total_return_pct",
        "benchmark_return_pct",
        "excess_return_pct",
        "final_equity",
        "gross_final_equity",
        "benchmark_final_equity",
        "fees_paid",
        "fees_paid_pct_initial_capital",
        "max_drawdown_pct",
        "sharpe_ratio",
    ):
        value = summary.get(key, "")
        suffix = "%" if key.endswith("_pct") else ""
        if key.endswith("_equity") or key == "fees_paid":
            display_value = f"{value:,.2f}" if isinstance(value, (float, int)) else str(value)
        else:
            display_value = f"{value}{suffix}" if suffix else str(value)
        cards.append({"label": SUMMARY_LABELS.get(key, key), "value": display_value})
    return cards


def build_chart_snapshot_cards(summary: dict[str, object]) -> list[dict[str, str]]:
    # (label, chiave, tipo, gruppo)
    # Un nuovo gruppo inserisce un separatore visivo nella strip flat.
    fields = (
        ("Rendimento",  "total_return_pct",     "signed_percent", "rendimenti"),
        ("Buy & hold",  "benchmark_return_pct", "percent",        "rendimenti"),
        ("Delta",       "excess_return_pct",    "signed_percent", "rendimenti"),
        ("Rend. annuo", "annual_return_pct",    "signed_percent", "rendimenti"),
        ("Max DD",      "max_drawdown_pct",     "percent",        "rischio"),
        ("Sharpe",      "sharpe_ratio",         "ratio",          "rischio"),
        ("Trade",       "trade_count",          "integer",        "attivita"),
        ("Esposizione", "exposure_pct",         "percent",        "attivita"),
        ("Fee",         "fees_paid",            "number",         "attivita"),
    )
    cards: list[dict[str, str]] = []
    prev_group = ""
    for label, key, kind, group in fields:
        value = summary.get(key)
        numeric = _to_float(value)
        if kind == "percent":
            display_value = _format_percent_metric(value)
            value_class = _delta_tone(numeric)
        elif kind == "signed_percent":
            display_value = _format_percent_metric(value, signed=True)
            value_class = _delta_tone(numeric)
        elif kind == "ratio":
            display_value = _format_ratio_metric(value)
            value_class = _delta_tone(numeric)
        elif kind == "integer":
            display_value = str(int(numeric)) if numeric is not None else "n/d"
            value_class = "neutral"
        else:
            display_value = _format_number_metric(value)
            value_class = "neutral"
        cards.append({
            "label":      label,
            "value":      display_value,
            "value_class": value_class,
            "sep_before": bool(prev_group and group != prev_group),
        })
        prev_group = group
    return cards


def build_sweep_summary_cards(summary: dict[str, object]) -> list[dict[str, object]]:
    """Card di riepilogo per uno sweep, dinamiche rispetto ai parametri ottimizzati."""
    cards: list[dict[str, object]] = [
        {"label": "Combinazioni valide", "value": str(summary.get("run_count", ""))},
        {"label": "Combinazioni scartate", "value": str(summary.get("invalid_combinations", ""))},
    ]

    # Mostra le card "Best <param>" per ciascun parametro ottimizzato, leggendo
    # da ``best_parameters`` (nuovo formato) oppure dai vecchi campi best_fast/
    # best_slow per i sweep storici.
    best_params = summary.get("best_parameters")
    if isinstance(best_params, dict) and best_params:
        for name, value in best_params.items():
            cards.append({"label": f"Best {name}", "value": str(value)})
    else:
        for legacy_key, label in (("best_fast", "Best fast"), ("best_slow", "Best slow")):
            if legacy_key in summary:
                cards.append({"label": label, "value": str(summary.get(legacy_key, ""))})

    for key, label in (
        ("best_total_return_pct", "Best rendimento"),
        ("best_sharpe_ratio", "Best Sharpe"),
        ("best_max_drawdown_pct", "Best max drawdown"),
        ("best_fees_paid", "Best spese"),
    ):
        value = summary.get(key, "")
        if key.endswith("_pct"):
            display_value = f"{value}%"
        elif key.endswith("_paid"):
            display_value = f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
        else:
            display_value = str(value)
        cards.append({"label": label, "value": display_value})
    return cards


def build_comparison(summary: dict[str, object]) -> dict[str, object]:
    delta = float(summary.get("excess_return_pct", 0.0))
    if delta > 0:
        verdict = "La strategia ha battuto il semplice hold."
    elif delta < 0:
        verdict = "La strategia ha fatto peggio del semplice hold."
    else:
        verdict = "La strategia ha fatto come il semplice hold."

    return {
        "strategy_return_pct": summary.get("total_return_pct", ""),
        "hold_return_pct": summary.get("benchmark_return_pct", ""),
        "delta_pct": summary.get("excess_return_pct", ""),
        "strategy_final_equity": summary.get("final_equity", ""),
        "gross_strategy_final_equity": summary.get("gross_final_equity", ""),
        "hold_final_equity": summary.get("benchmark_final_equity", ""),
        "fees_paid": summary.get("fees_paid", ""),
        "fees_pct_initial_capital": summary.get("fees_paid_pct_initial_capital", ""),
        "fee_drag_equity": summary.get("fee_drag_equity", ""),
        "verdict": verdict,
    }


def build_live_comparison_cards(
    preview_summary: dict[str, object],
    baseline_summary: dict[str, object],
    *,
    baseline_label: str,
    preview_label: str,
) -> list[dict[str, str]]:
    preview_return = float(preview_summary.get("total_return_pct", 0.0))
    benchmark_return = float(
        preview_summary.get(
            "benchmark_return_pct",
            baseline_summary.get("benchmark_return_pct", 0.0),
        )
    )
    preview_drawdown = float(preview_summary.get("max_drawdown_pct", 0.0))
    benchmark_drawdown = float(
        preview_summary.get(
            "benchmark_max_drawdown_pct",
            baseline_summary.get("benchmark_max_drawdown_pct", 0.0),
        )
    )
    preview_final_equity = float(preview_summary.get("final_equity", 0.0))
    benchmark_final_equity = float(
        preview_summary.get(
            "benchmark_final_equity",
            baseline_summary.get("benchmark_final_equity", 0.0),
        )
    )
    preview_fees = float(preview_summary.get("fees_paid", 0.0))
    preview_sharpe = preview_summary.get("sharpe_ratio")
    sharpe_str = f"{float(preview_sharpe):+.2f}" if preview_sharpe is not None else "n/d"

    delta = preview_return - benchmark_return

    return [
        {
            "label": "Differenza con comprare e basta",
            "value": f"{delta:+.2f}%",
            "hint": f"strategia {preview_return:+.2f}% · comprando e basta {benchmark_return:+.2f}%",
            "tone": _delta_tone(delta),
        },
        {
            "label": "Guadagno rispetto al rischio",
            "value": sharpe_str,
            "hint": "sopra 1 è buono (in gergo: Sharpe)",
            "tone": "neutral",
        },
        {
            "label": "Il calo peggiore",
            "value": f"{preview_drawdown:.2f}%",
            "hint": "quanto è sceso dal punto più alto",
            "tone": "neutral",
        },
        {
            "label": "Commissioni pagate",
            "value": _format_number_metric(preview_fees),
            "hint": "",
            "tone": "neutral",
        },
    ]


def build_result_validation_snapshot(
    summary: dict[str, object],
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, list[dict[str, str]]]:
    normalized_trades = trades.fillna("")
    closed_trades = _closed_trades(normalized_trades)
    closed_count = len(closed_trades.index)
    open_count = max(len(normalized_trades.index) - closed_count, 0)

    pnl_series = pd.to_numeric(closed_trades.get("pnl_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    win_count = int((pnl_series > 0).sum())
    loss_count = int((pnl_series < 0).sum())
    flat_count = int((pnl_series == 0).sum())
    win_rate = round((win_count / closed_count) * 100, 2) if closed_count else None
    avg_trade = round(float(pnl_series.mean()), 2) if not pnl_series.empty else None
    best_trade = round(float(pnl_series.max()), 2) if not pnl_series.empty else None
    worst_trade = round(float(pnl_series.min()), 2) if not pnl_series.empty else None

    durations_minutes = [
        duration
        for duration in (
            _trade_duration_minutes(
                entry_raw=str(row.get("entry_date", "")).strip(),
                exit_raw=str(row.get("exit_date", "")).strip(),
            )
            for row in closed_trades.to_dict(orient="records")
        )
        if duration is not None
    ]
    avg_duration_minutes = round(sum(durations_minutes) / len(durations_minutes)) if durations_minutes else None
    median_duration_minutes = round(float(pd.Series(durations_minutes).median())) if durations_minutes else None

    summary_trade_count = _to_float(summary.get("trade_count"))
    summary_final_equity = _to_float(summary.get("final_equity"))
    summary_benchmark_equity = _to_float(summary.get("benchmark_final_equity"))
    file_final_equity = _last_series_value(equity_curve.get("equity"))
    file_benchmark_equity = _last_series_value(equity_curve.get("benchmark_equity"))

    trade_count_check = _build_consistency_check(
        label="Operazioni concluse",
        summary_value=summary_trade_count,
        file_value=float(closed_count),
        summary_display=str(int(summary_trade_count)) if summary_trade_count is not None else "n/d",
        file_display=str(closed_count),
        tolerance=0.0,
        ok_hint="Il numero di operazioni del riepilogo coincide con quelle elencate nel file.",
        mismatch_hint="Il numero di operazioni del riepilogo non coincide con quelle elencate nel file.",
    )
    final_equity_check = _build_consistency_check(
        label="Quanto ti resta alla fine",
        summary_value=summary_final_equity,
        file_value=file_final_equity,
        summary_display=_format_number_metric(summary_final_equity),
        file_display=_format_number_metric(file_final_equity),
        tolerance=0.05,
        ok_hint="La cifra finale del riepilogo coincide con l'ultimo punto dell'andamento salvato.",
        mismatch_hint="La cifra finale del riepilogo non coincide con l'ultimo punto dell'andamento salvato.",
    )
    benchmark_equity_check = _build_consistency_check(
        label="Comprando e basta",
        summary_value=summary_benchmark_equity,
        file_value=file_benchmark_equity,
        summary_display=_format_number_metric(summary_benchmark_equity),
        file_display=_format_number_metric(file_benchmark_equity),
        tolerance=0.05,
        ok_hint="Il confronto col comprare-e-tenere coincide fra riepilogo e andamento salvato.",
        mismatch_hint="Il confronto col comprare-e-tenere non coincide fra riepilogo e andamento salvato.",
    )

    checks = [trade_count_check, final_equity_check, benchmark_equity_check]
    mismatch_count = sum(1 for check in checks if check["status_class"] == "warning")
    overall_check = {
        "label": "Controllo dei conti",
        "status_label": "OK" if mismatch_count == 0 else "ATTENZIONE",
        "status_class": "positive" if mismatch_count == 0 else "warning",
        "value": f"{len(checks) - mismatch_count} su {len(checks)} tornano",
        "hint": (
            "I tre file salvati (riepilogo, andamento e operazioni) raccontano la stessa storia."
            if mismatch_count == 0
            else "Almeno un conto non torna fra i file salvati: meglio non fidarsi di questo risultato."
        ),
    }

    cards = [
        {
            "label": "Operazioni concluse",
            "value": str(closed_count),
            "hint": f"Ancora aperte a fine periodo: {open_count}.",
            "tone": "neutral",
        },
        {
            "label": "Operazioni chiuse in guadagno",
            "value": _format_percent_metric(win_rate),
            "hint": f"{win_count} in guadagno · {loss_count} in perdita · {flat_count} in pari.",
            "tone": _delta_tone((win_rate or 0) - 50) if win_rate is not None else "neutral",
        },
        {
            "label": "Risultato medio per operazione",
            "value": _format_percent_metric(avg_trade, signed=True),
            "hint": (
                f"La migliore {_format_percent_metric(best_trade, signed=True)} · "
                f"la peggiore {_format_percent_metric(worst_trade, signed=True)}."
            ),
            "tone": _delta_tone(avg_trade),
        },
        {
            "label": "Durata media di un'operazione",
            "value": _format_duration_from_minutes(avg_duration_minutes),
            "hint": f"Metà sono durate meno di {_format_duration_from_minutes(median_duration_minutes)}.",
            "tone": "neutral",
        },
    ]

    return {"cards": cards, "checks": [overall_check, *checks]}


def build_market_snapshot(equity_curve: pd.DataFrame) -> dict[str, object]:
    timestamp_display = _extract_date_labels(equity_curve)[-1] if not equity_curve.empty else ""
    snapshot = {
        "has_market": False,
        "timestamp_display": timestamp_display,
        "open_display": "n/a",
        "high_display": "n/a",
        "low_display": "n/a",
        "close_display": "n/a",
        "change_display": "n/a",
        "change_pct_display": "n/a",
        "change_class": "neutral",
        "volume_display": "",
    }

    if equity_curve.empty or "close" not in equity_curve.columns:
        return snapshot

    last_row = equity_curve.iloc[-1]
    previous_row = equity_curve.iloc[-2] if len(equity_curve) > 1 else None

    close_value = _to_float(last_row.get("close"))
    if close_value is None:
        return snapshot

    open_value = _to_float(last_row.get("open"))
    high_value = _to_float(last_row.get("high"))
    low_value = _to_float(last_row.get("low"))
    previous_close = _to_float(previous_row.get("close")) if previous_row is not None else open_value
    volume_value = _to_float(last_row.get("volume"))

    change_value = (close_value - previous_close) if previous_close is not None else None
    change_pct_value = ((change_value / previous_close) * 100) if previous_close not in (None, 0) and change_value is not None else None
    if change_value is None:
        change_class = "neutral"
    elif change_value > 0:
        change_class = "positive"
    elif change_value < 0:
        change_class = "negative"
    else:
        change_class = "neutral"

    snapshot.update(
        {
            "has_market": True,
            "open_display": _format_terminal_number(open_value) if open_value is not None else "n/a",
            "high_display": _format_terminal_number(high_value) if high_value is not None else "n/a",
            "low_display": _format_terminal_number(low_value) if low_value is not None else "n/a",
            "close_display": _format_terminal_number(close_value),
            "change_display": _format_signed_number(change_value) if change_value is not None else "n/a",
            "change_pct_display": _format_signed_percent(change_pct_value) if change_pct_value is not None else "n/a",
            "change_class": change_class,
            "volume_display": _format_compact_number(volume_value) if volume_value is not None else "",
        }
    )
    return snapshot


def build_chart_layers(payload: dict[str, object]) -> list[dict[str, object]]:
    market = payload.get("market", {})
    equity = payload.get("equity", {})
    entry_markers = payload.get("entry_markers", {})
    exit_markers = payload.get("exit_markers", {})
    return [
        {"key": "price", "label": "Prezzo", "enabled": True, "locked": True},
        {
            "key": "volume",
            "label": "Volume",
            "enabled": any(value not in (None, 0, 0.0) for value in market.get("volume", [])),
            "locked": False,
        },
        {"key": "entry", "label": "Ingresso", "enabled": bool(entry_markers.get("x")), "locked": False},
        {"key": "exit", "label": "Uscita", "enabled": bool(exit_markers.get("x")), "locked": False},
        {"key": "strategy", "label": "Strategia", "enabled": bool(equity.get("strategy")), "locked": True},
        {"key": "benchmark", "label": "Buy & hold", "enabled": bool(equity.get("benchmark")), "locked": False},
        {"key": "gross", "label": "Senza fee", "enabled": bool(equity.get("gross")), "locked": False},
        {"key": "drawdown", "label": "Drawdown", "enabled": True, "locked": False},
    ]


def enrich_summary(summary: dict[str, object], report_dir: Path) -> dict[str, object]:
    if _has_summary_enrichment(summary):
        return dict(summary)

    equity_curve = _read_summary_enrichment_curve(report_dir)
    return enrich_summary_with_equity_curve(summary=summary, equity_curve=equity_curve)


def enrich_summary_with_equity_curve(summary: dict[str, object], equity_curve: pd.DataFrame) -> dict[str, object]:
    enriched = dict(summary)
    if _has_summary_enrichment(enriched):
        return enriched

    initial_capital = float(enriched.get("initial_capital", 0.0))
    total_return_pct = float(enriched.get("total_return_pct", 0.0))
    benchmark_equity = equity_curve["benchmark_equity"].astype(float) if "benchmark_equity" in equity_curve.columns else pd.Series(dtype=float)

    if "benchmark_final_equity" not in enriched:
        benchmark_final_equity = float(benchmark_equity.iloc[-1]) if len(benchmark_equity) else initial_capital
        enriched["benchmark_final_equity"] = round(benchmark_final_equity, 2)

    if "benchmark_return_pct" not in enriched:
        benchmark_final_equity = float(enriched.get("benchmark_final_equity", initial_capital))
        benchmark_return_pct = round(((benchmark_final_equity / initial_capital) - 1) * 100, 2) if initial_capital else 0.0
        enriched["benchmark_return_pct"] = benchmark_return_pct

    if "benchmark_max_drawdown_pct" not in enriched:
        enriched["benchmark_max_drawdown_pct"] = (
            _compute_drawdown_pct(benchmark_equity) if len(benchmark_equity) else 0.0
        )

    benchmark_return_pct = float(enriched.get("benchmark_return_pct", 0.0))
    if "excess_return_pct" not in enriched:
        enriched["excess_return_pct"] = round(total_return_pct - benchmark_return_pct, 2)

    needs_cost_metrics = any(
        key not in enriched
        for key in ("gross_final_equity", "fees_paid", "fees_paid_pct_initial_capital", "fee_drag_equity")
    )
    if needs_cost_metrics:
        gross_equity = _ensure_gross_equity(equity_curve, initial_capital)
        transaction_cost_amount = _ensure_transaction_cost_amount(equity_curve, initial_capital)
        gross_final_equity = float(gross_equity.iloc[-1]) if len(gross_equity) else float(
            enriched.get("final_equity", initial_capital)
        )
        fees_paid = float(transaction_cost_amount.sum()) if len(transaction_cost_amount) else 0.0
        final_equity = float(enriched.get("final_equity", 0.0))

        enriched.setdefault("gross_final_equity", round(gross_final_equity, 2))
        enriched.setdefault("fees_paid", round(fees_paid, 2))
        enriched.setdefault(
            "fees_paid_pct_initial_capital",
            round((fees_paid / initial_capital) * 100, 2) if initial_capital else 0.0,
        )
        enriched.setdefault("fee_drag_equity", round(gross_final_equity - final_equity, 2))
    return enriched


def read_report_metadata(report_dir: Path) -> dict[str, object]:
    metadata_file = report_dir / "metadata.json"
    if metadata_file.exists():
        metadata = _read_json(metadata_file)
    else:
        metadata = {}

    if "symbol" not in metadata or "strategy" not in metadata:
        metadata.update(_metadata_from_report_name(report_dir.name))
    if "created_at" not in metadata:
        metadata["created_at"] = report_dir.stat().st_mtime
    if "artifact_type" not in metadata:
        metadata["artifact_type"] = "report"
    return metadata


def build_line_chart(
    series_map: dict[str, pd.Series],
    colors: dict[str, str],
    width: int = 860,
    height: int = 280,
    padding: int = 24,
) -> dict[str, object]:
    prepared = {label: series.astype(float).reset_index(drop=True) for label, series in series_map.items()}
    if not prepared:
        raise ValueError("At least one series is required to build a chart.")

    values = pd.concat(prepared.values(), axis=0)
    minimum = float(values.min())
    maximum = float(values.max())
    if minimum == maximum:
        minimum -= 1.0
        maximum += 1.0

    chart_series = []
    for label, series in prepared.items():
        chart_series.append(
            {
                "label": label,
                "color": colors[label],
                "points": _series_to_points(
                    series=series,
                    minimum=minimum,
                    maximum=maximum,
                    width=width,
                    height=height,
                    padding=padding,
                ),
                "latest": round(float(series.iloc[-1]), 2),
            }
        )

    return {
        "width": width,
        "height": height,
        "min_label": round(minimum, 2),
        "max_label": round(maximum, 2),
        "zero_y": _value_to_y(
            value=0.0,
            minimum=minimum,
            maximum=maximum,
            height=height,
            padding=padding,
        ),
        "series": chart_series,
    }


def sample_series(series: pd.Series, max_points: int = 140) -> pd.Series:
    if len(series) <= max_points:
        return series.astype(float).reset_index(drop=True)

    step = max(len(series) // max_points, 1)
    sampled = series.iloc[::step]
    if sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])
    return sampled.astype(float).reset_index(drop=True)


def _series_to_points(
    series: pd.Series,
    minimum: float,
    maximum: float,
    width: int,
    height: int,
    padding: int,
) -> str:
    values = series.tolist()
    plot_width = max(width - (padding * 2), 1)
    denominator = max(len(values) - 1, 1)
    points = []
    for index, value in enumerate(values):
        x = padding + (plot_width * index / denominator)
        y = _value_to_y(
            value=float(value),
            minimum=minimum,
            maximum=maximum,
            height=height,
            padding=padding,
        )
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def _value_to_y(value: float, minimum: float, maximum: float, height: int, padding: int) -> float:
    scale = (value - minimum) / (maximum - minimum)
    plot_height = height - (padding * 2)
    return height - padding - (scale * plot_height)


def _metadata_from_report_name(report_name: str) -> dict[str, object]:
    match = REPORT_NAME_PATTERN.match(report_name)
    if not match:
        return {"strategy_label": "Backtest"}

    metadata = match.groupdict()
    strategy = str(metadata["strategy"])
    return {
        "symbol": metadata["symbol"],
        "strategy": strategy,
        "strategy_label": strategy.replace("_", " ").title(),
        "created_at": metadata["timestamp"],
    }


def _infer_report_range(equity_curve: pd.DataFrame) -> tuple[str, str]:
    labels = _extract_date_labels(equity_curve)
    if not labels:
        return "", ""
    return labels[0], labels[-1]


def _infer_interval_label(equity_curve: pd.DataFrame) -> str:
    if "date" not in equity_curve.columns or len(equity_curve.index) < 2:
        return ""

    dates = pd.to_datetime(equity_curve["date"], errors="coerce").dropna()
    if len(dates) < 2:
        return ""

    deltas = dates.diff().dropna()
    if deltas.empty:
        return ""

    median_delta = deltas.median()
    if pd.isna(median_delta):
        return ""

    total_minutes = median_delta.total_seconds() / 60
    interval_candidates = [
        ("1m", 1),
        ("2m", 2),
        ("5m", 5),
        ("15m", 15),
        ("30m", 30),
        ("1h", 60),
        ("90m", 90),
        ("1d", 24 * 60),
        ("1wk", 7 * 24 * 60),
        ("1mo", 30 * 24 * 60),
    ]
    closest_label, closest_value = min(
        interval_candidates,
        key=lambda candidate: abs(candidate[1] - total_minutes),
    )
    if closest_value == 0:
        return ""
    tolerance = max(closest_value * 0.3, 1)
    return closest_label if abs(total_minutes - closest_value) <= tolerance else ""


def _format_number_metric(value: object, decimals: int = 2) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "n/d"
    return f"{numeric:,.{decimals}f}"


def _format_percent_metric(value: object, *, signed: bool = False, decimals: int = 2) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "n/d"
    sign = "+" if signed and numeric > 0 else ""
    return f"{sign}{numeric:.{decimals}f}%"


def _format_ratio_metric(value: object, decimals: int = 2) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "n/d"
    return f"{numeric:.{decimals}f}"


def _delta_tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _drawdown_tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    drawdown_abs = abs(value)
    if drawdown_abs <= 10:
        return "positive"
    if drawdown_abs <= 20:
        return "warning"
    return "negative"


def _sharpe_tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value >= 1.5:
        return "positive"
    if value >= 1:
        return "warning"
    return "negative"


def _interpret_sharpe(value: float | None) -> str:
    if value is None:
        return "Qualita' del rendimento non disponibile."
    if value >= 2:
        return "Molto buono: rendimento molto pulito rispetto alla volatilita'."
    if value >= 1.5:
        return "Buono: rischio/rendimento solido."
    if value >= 1:
        return "Discreto: il profilo rischio/rendimento regge."
    if value >= 0.5:
        return "Debole: rendimento poco efficiente rispetto al rischio."
    return "Molto debole: troppo rumore per il rendimento prodotto."


def _read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_equity_curve(report_dir: Path) -> pd.DataFrame:
    return pd.read_csv(report_dir / "equity_curve.csv")


def _read_best_equity_curve(sweep_dir: Path) -> pd.DataFrame:
    return pd.read_csv(sweep_dir / "best_equity_curve.csv")


def build_chart_payload(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    focus: str,
    interval: str = "",
    indicators: list[dict[str, object]] | None = None,
    signal_context: dict[str, object] | None = None,
    marker_context: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_trades = trades.fillna("")
    effective_marker_context = marker_context or _build_trade_marker_context(
        equity_curve=equity_curve,
        signal_context=signal_context or {},
    )
    return {
        "focus": focus,
        "interval": str(interval or "").strip().lower(),
        "dates": _extract_date_labels(equity_curve),
        "market": {
            "has_candles": all(column in equity_curve.columns for column in ("open", "high", "low")),
            "open": _series_to_json_list(equity_curve.get("open")),
            "high": _series_to_json_list(equity_curve.get("high")),
            "low": _series_to_json_list(equity_curve.get("low")),
            "close": _series_to_json_list(equity_curve.get("close")),
            "volume": _series_to_json_list(equity_curve.get("volume")),
        },
        "equity": {
            "strategy": _series_to_json_list(equity_curve.get("equity")),
            "gross": _series_to_json_list(equity_curve.get("gross_equity")),
            "benchmark": _series_to_json_list(equity_curve.get("benchmark_equity")),
        },
        "drawdown_pct": _series_to_json_list((equity_curve.get("drawdown", pd.Series(dtype=float)).fillna(0.0) * 100)),
        "entry_markers": _build_trade_markers(normalized_trades, side="entry", marker_context=effective_marker_context),
        "exit_markers": _build_trade_markers(normalized_trades, side="exit", marker_context=effective_marker_context),
        "indicators": list(indicators or []),
    }


def _build_chart_window_context(
    artifact_type: str,
    artifact_name: str,
    metadata: dict[str, object],
    summary: dict[str, object],
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    focus: str,
    title: str,
    subtitle: str,
) -> dict[str, object]:
    normalized_trades = trades.fillna("")
    marker_context = _build_trade_marker_context(
        equity_curve=equity_curve,
        signal_context=metadata,
    )
    payload = build_chart_payload(
        equity_curve=equity_curve,
        trades=normalized_trades,
        focus=focus,
        interval=str(metadata.get("interval", "")),
        signal_context=metadata,
        marker_context=marker_context,
    )

    return {
        "artifact_type": artifact_type,
        "artifact_name": artifact_name,
        "title": title,
        "subtitle": subtitle,
        "metadata": metadata,
        "summary": summary,
        # Il verdetto in lingua semplice: e' la prima cosa che si legge nella
        # pagina, prima del grafico e delle metriche.
        "verdetto": build_plain_verdict(summary, barre=len(equity_curve)),
        "market_snapshot": build_market_snapshot(equity_curve),
        "layers": build_chart_layers(payload),
        "summary_cards": build_summary_cards(summary),
        "snapshot_cards": build_chart_snapshot_cards(summary),
        "trade_preview": build_trade_preview(normalized_trades, limit=None, marker_context=marker_context),
        "validation": build_result_validation_snapshot(summary, equity_curve, normalized_trades),
        "chart_payload": payload,
    }


def _build_report_list_item(report_dir: Path, metadata: dict[str, object]) -> dict[str, object]:
    summary = enrich_summary(_read_json(report_dir / "summary.json"), report_dir)
    equity_curve = _read_equity_curve(report_dir)
    return {
        "artifact_type": "report",
        "name": report_dir.name,
        "path": report_dir,
        "summary": summary,
        "metadata": metadata,
        "created_at": metadata.get("created_at", ""),
        "comparison": build_comparison(summary),
        "detail_url": f"/reports/{report_dir.name}",
        "preview_chart": build_line_chart(
            {
                "Strategy": sample_series(equity_curve["equity"], max_points=72),
                "Buy & hold": sample_series(equity_curve["benchmark_equity"], max_points=72),
            },
            colors={"Strategy": "#0f766e", "Buy & hold": "#c084fc"},
            width=300,
            height=94,
            padding=10,
        ),
    }


def _build_sweep_list_item(item_dir: Path, metadata: dict[str, object]) -> dict[str, object]:
    summary = _read_json(item_dir / "summary.json")
    results = pd.read_csv(item_dir / "results.csv")
    sorted_results = results.sort_values(by=["rank"], ascending=True) if "rank" in results.columns else results
    preview_chart = build_line_chart(
        {"Top total return": sample_series(sorted_results["total_return_pct"], max_points=50)},
        colors={"Top total return": "#0f766e"},
        width=300,
        height=94,
        padding=10,
    )
    return {
        "artifact_type": "sweep",
        "name": item_dir.name,
        "path": item_dir,
        "summary": summary,
        "metadata": metadata,
        "created_at": metadata.get("created_at", ""),
        "detail_url": f"/sweeps/{item_dir.name}",
        "preview_chart": preview_chart,
    }


def _extract_date_labels(equity_curve: pd.DataFrame) -> list[str]:
    if "date" in equity_curve.columns:
        dates = pd.to_datetime(equity_curve["date"], errors="coerce")
    else:
        dates = pd.to_datetime(equity_curve.index, errors="coerce")

    labels: list[str] = []
    for value in dates:
        if pd.isna(value):
            labels.append("")
            continue
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            labels.append(value.strftime("%Y-%m-%d"))
        else:
            labels.append(value.strftime("%Y-%m-%d %H:%M"))
    return labels


def _series_to_json_list(series: pd.Series | None) -> list[float | None]:
    if series is None:
        return []
    values: list[float | None] = []
    for value in series.tolist():
        if pd.isna(value):
            values.append(None)
        else:
            values.append(round(float(value), 6))
    return values


def _build_trade_markers(
    trades: pd.DataFrame,
    side: str,
    marker_context: dict[str, object] | None = None,
) -> dict[str, list[object]]:
    date_key = f"{side}_date"
    price_key = f"{side}_price"
    markers = {"x": [], "y": [], "text": []}

    for trade in trades.to_dict(orient="records"):
        trade_date = str(trade.get(date_key, "")).strip()
        if not trade_date:
            continue

        price = trade.get(price_key, "")
        try:
            y_value = float(price)
        except (TypeError, ValueError):
            continue

        pnl = str(trade.get("pnl_pct", "")).strip() or "open"
        markers["x"].append(trade_date)
        markers["y"].append(round(y_value, 6))
        markers["text"].append(
            _build_trade_marker_popup_text(
                trade=trade,
                side=side,
                trade_date=trade_date,
                price=y_value,
                pnl=pnl,
                marker_context=marker_context or {},
            )
        )

    return markers


def _build_trade_marker_popup_text(
    *,
    trade: dict[str, object],
    side: str,
    trade_date: str,
    price: float,
    pnl: str,
    marker_context: dict[str, object],
) -> str:
    lines = [
        f"{'ENTRY' if side == 'entry' else 'EXIT'} | {trade_date}",
        f"Prezzo esecuzione: {_format_trade_price(price)}",
    ]

    frame = marker_context.get("frame")
    execution_position = _find_marker_position(trade_date, marker_context)
    trigger_position = _marker_trigger_position(execution_position)
    if isinstance(frame, pd.DataFrame) and execution_position is not None and 0 <= execution_position < len(frame.index):
        execution_row = frame.iloc[execution_position]
        candle_line = _format_marker_candle_line(execution_row)
        if candle_line:
            lines.append(f"Candela esecuzione: {candle_line.removeprefix('Candela: ')}")

        volume_line = _format_marker_volume_line(execution_row)
        if volume_line:
            lines.append(volume_line)

        if trigger_position is not None and trigger_position != execution_position:
            trigger_row = frame.iloc[trigger_position]
            trigger_timestamp = _marker_date_key(trigger_row.get("__timestamp"))
            lines.append(f"Trigger strategia letto sulla candela precedente: {trigger_timestamp}")
            trigger_candle_line = _format_marker_candle_line(trigger_row)
            if trigger_candle_line:
                lines.append(f"Candela trigger: {trigger_candle_line.removeprefix('Candela: ')}")

        lines.extend(
            _build_marker_state_lines(
                side=side,
                execution_position=execution_position,
                trigger_position=trigger_position,
                marker_context=marker_context,
            )
        )
    else:
        lines.append("Stato candela non disponibile nel report salvato.")

    if side == "exit":
        pnl_value = _to_float(trade.get("pnl_pct"))
        if pnl_value is not None:
            lines.append(f"PnL trade: {_format_signed_percent(pnl_value)}")
        duration_display = _format_trade_duration(
            str(trade.get("entry_date", "")).strip(),
            str(trade.get("exit_date", "")).strip(),
            trade.get("holding_days"),
        )
        if duration_display not in {"-", "In corso"}:
            lines.append(f"Durata trade: {duration_display}")
    elif pnl and pnl != "open":
        pnl_value = _to_float(pnl)
        if pnl_value is not None:
            lines.append(f"PnL a chiusura trade: {_format_signed_percent(pnl_value)}")

    return "\n".join(line for line in lines if line)


def _build_trade_marker_context(
    *,
    equity_curve: pd.DataFrame,
    signal_context: dict[str, object],
) -> dict[str, object]:
    frame = equity_curve.copy()
    if "date" in frame.columns:
        timestamps = pd.to_datetime(frame["date"], errors="coerce")
    else:
        timestamps = pd.to_datetime(frame.index, errors="coerce")
    frame["__timestamp"] = timestamps
    frame = frame.dropna(subset=["__timestamp"]).reset_index(drop=True)
    if frame.empty:
        return {"frame": frame, "date_lookup": {}}

    market_data = frame.set_index("__timestamp", drop=True)
    active_rules = _extract_signal_rules(signal_context)
    rule_logic = str(signal_context.get("rule_logic", "all") or "all").strip().lower()
    if rule_logic not in {"all", "any"}:
        rule_logic = "all"

    rule_states = [_build_rule_state(rule, market_data) for rule in active_rules]
    groups_raw = signal_context.get("groups") or []
    signal_groups = [g for g in groups_raw if isinstance(g, dict)] if len(groups_raw) > 1 else None
    signal_expression = signal_context.get("expression") if isinstance(signal_context.get("expression"), dict) else None
    combined_signal = None
    if rule_states:
        combined_signal = build_combined_signal(
            data=market_data,
            rules=[(state["strategy_id"], state["parameters"]) for state in rule_states],
            combination_mode=rule_logic,
            groups=signal_groups,
            expression=signal_expression,
        ).reset_index(drop=True)

    date_lookup: dict[str, int] = {}
    for position, timestamp in enumerate(frame["__timestamp"]):
        key = _marker_date_key(timestamp)
        if key and key not in date_lookup:
            date_lookup[key] = position

    return {
        "frame": frame,
        "date_lookup": date_lookup,
        "rule_logic": rule_logic,
        "rule_logic_label": "AND" if rule_logic == "all" else "OR",
        "strategy_label": str(
            signal_context.get("strategy_label")
            or signal_context.get("primary_strategy_label")
            or signal_context.get("strategy")
            or "Strategia"
        ),
        "rule_states": rule_states,
        "combined_signal": combined_signal,
    }


def _extract_signal_rules(signal_context: dict[str, object]) -> list[dict[str, object]]:
    extracted: list[dict[str, object]] = []
    raw_rules = signal_context.get("active_rules") or []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue
        strategy_id = str(raw_rule.get("strategy", "")).strip()
        if strategy_id not in STRATEGY_SPECS:
            continue
        extracted.append(
            {
                "strategy_id": strategy_id,
                "label": str(raw_rule.get("strategy_label") or STRATEGY_SPECS[strategy_id].label),
                "parameters": {
                    **STRATEGY_SPECS[strategy_id].defaults(),
                    **{str(key): value for key, value in (raw_rule.get("parameters") or {}).items()},
                },
            }
        )

    if extracted:
        return extracted

    strategy_id = str(signal_context.get("primary_strategy") or signal_context.get("strategy") or "").strip()
    if strategy_id in STRATEGY_SPECS:
        return [
            {
                "strategy_id": strategy_id,
                "label": str(
                    signal_context.get("strategy_label")
                    or signal_context.get("primary_strategy_label")
                    or STRATEGY_SPECS[strategy_id].label
                ),
                "parameters": {
                    **STRATEGY_SPECS[strategy_id].defaults(),
                    **{str(key): value for key, value in (signal_context.get("parameters") or {}).items()},
                },
            }
        ]

    return []


def _build_rule_state(rule: dict[str, object], market_data: pd.DataFrame) -> dict[str, object]:
    strategy_id = str(rule["strategy_id"])
    parameters = {str(key): value for key, value in (rule.get("parameters") or {}).items()}
    close = market_data["close"].astype(float)

    state: dict[str, object] = {
        "strategy_id": strategy_id,
        "label": str(rule.get("label") or STRATEGY_SPECS[strategy_id].label),
        "parameters": parameters,
        "position": build_strategy_signal(strategy_id=strategy_id, data=market_data, parameters=parameters).reset_index(drop=True),
    }

    if strategy_id == "sma_cross":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        state["fast_series"] = close.rolling(window=fast, min_periods=fast).mean().reset_index(drop=True)
        state["slow_series"] = close.rolling(window=slow, min_periods=slow).mean().reset_index(drop=True)
    elif strategy_id == "ema_cross":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        state["fast_series"] = close.ewm(span=fast, adjust=False, min_periods=fast).mean().reset_index(drop=True)
        state["slow_series"] = close.ewm(span=slow, adjust=False, min_periods=slow).mean().reset_index(drop=True)
    elif strategy_id == "rsi_mean_reversion":
        period = int(parameters["period"])
        state["rsi"] = relative_strength_index(close, period=period).reset_index(drop=True)
    elif strategy_id == "macd_trend":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        signal_period = int(parameters["signal"])
        fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
        state["macd"] = macd_line.reset_index(drop=True)
        state["signal_line"] = signal_line.reset_index(drop=True)
    elif strategy_id == "bollinger_reversion":
        period = int(parameters["period"])
        std_dev = float(parameters["std_dev"])
        basis = close.rolling(window=period, min_periods=period).mean()
        deviation = close.rolling(window=period, min_periods=period).std(ddof=0)
        state["basis"] = basis.reset_index(drop=True)
        state["lower_band"] = (basis - (deviation * std_dev)).reset_index(drop=True)
        state["frame_close"] = close.reset_index(drop=True)
    elif strategy_id == "stochastic_reversion":
        high = market_data["high"].astype(float)
        low = market_data["low"].astype(float)
        k_period = int(parameters["k_period"])
        d_period = int(parameters["d_period"])
        smooth = int(parameters["smooth"])
        lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
        highest_high = high.rolling(window=k_period, min_periods=k_period).max()
        denominator = (highest_high - lowest_low).replace(0.0, pd.NA)
        raw_k = ((close - lowest_low) / denominator) * 100
        slow_k = raw_k.rolling(window=smooth, min_periods=smooth).mean()
        slow_d = slow_k.rolling(window=d_period, min_periods=d_period).mean()
        state["slow_k"] = slow_k.reset_index(drop=True)
        state["slow_d"] = slow_d.reset_index(drop=True)
    elif strategy_id == "cci_reversion":
        period = int(parameters["period"])
        state["cci"] = commodity_channel_index(market_data, period=period).reset_index(drop=True)
    elif strategy_id == "williams_r_reversion":
        period = int(parameters["period"])
        state["williams_r"] = williams_r_indicator(market_data, period=period).reset_index(drop=True)
    elif strategy_id == "adx_trend":
        period = int(parameters["period"])
        components = adx_components(market_data, period=period).reset_index(drop=True)
        state["adx"] = components["adx"]
        state["plus_di"] = components["plus_di"]
        state["minus_di"] = components["minus_di"]
    elif strategy_id == "obv_trend":
        fast = int(parameters["fast"])
        slow = int(parameters["slow"])
        obv = on_balance_volume(market_data)
        state["fast_series"] = obv.ewm(span=fast, adjust=False, min_periods=fast).mean().reset_index(drop=True)
        state["slow_series"] = obv.ewm(span=slow, adjust=False, min_periods=slow).mean().reset_index(drop=True)

    return state


def _find_marker_position(trade_date: str, marker_context: dict[str, object]) -> int | None:
    return marker_context.get("date_lookup", {}).get(_marker_date_key(trade_date))


def _marker_date_key(value: object) -> str:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return ""
    if getattr(timestamp, "tzinfo", None) is not None:
        timestamp = timestamp.tz_localize(None)
    if timestamp.hour == 0 and timestamp.minute == 0 and timestamp.second == 0:
        return timestamp.strftime("%Y-%m-%d")
    return timestamp.strftime("%Y-%m-%d %H:%M")


def _format_marker_candle_line(row: pd.Series) -> str:
    open_value = _format_trade_price(row.get("open"))
    high_value = _format_trade_price(row.get("high"))
    low_value = _format_trade_price(row.get("low"))
    close_value = _format_trade_price(row.get("close"))
    if all(value == "-" for value in (open_value, high_value, low_value, close_value)):
        return ""
    return f"Candela: O {open_value} | H {high_value} | L {low_value} | C {close_value}"


def _format_marker_volume_line(row: pd.Series) -> str:
    volume_value = _to_float(row.get("volume"))
    if volume_value is None:
        return ""
    return f"Volume: {volume_value:,.0f}"


def _build_marker_state_lines(
    *,
    side: str,
    execution_position: int,
    trigger_position: int | None,
    marker_context: dict[str, object],
) -> list[str]:
    lines: list[str] = []
    rule_states = marker_context.get("rule_states") or []
    combined_signal = marker_context.get("combined_signal")
    rule_logic = str(marker_context.get("rule_logic", "all"))
    rule_logic_label = str(marker_context.get("rule_logic_label", "AND"))
    strategy_label = str(marker_context.get("strategy_label", "Strategia"))
    signal_position = trigger_position if trigger_position is not None else execution_position

    if isinstance(combined_signal, pd.Series) and not combined_signal.empty and signal_position < len(combined_signal.index):
        current_state = int(round(float(combined_signal.iloc[signal_position])))
        previous_state = int(round(float(combined_signal.iloc[signal_position - 1]))) if signal_position > 0 else 0
        lines.append(
            f"Segnale strategia: {'FLAT' if previous_state == 0 else 'LONG'} -> {'LONG' if current_state > 0 else 'FLAT'}"
        )

    if rule_states:
        long_rules = sum(1 for rule_state in rule_states if _series_flag(rule_state.get("position"), signal_position))
        lines.append(f"Setup: {strategy_label} | Logica {rule_logic_label}")
        if side == "entry":
            if rule_logic == "all":
                lines.append(f"Regole long sulla candela trigger: {long_rules}/{len(rule_states)}. Il combinato entra quando tutte sono attive.")
            else:
                lines.append(f"Regole long sulla candela trigger: {long_rules}/{len(rule_states)}. Il combinato entra quando almeno una e' attiva.")
        else:
            if rule_logic == "all":
                lines.append(f"Regole rimaste long sulla candela trigger: {long_rules}/{len(rule_states)}. Basta che una perda il segnale per uscire.")
            else:
                lines.append(f"Regole rimaste long sulla candela trigger: {long_rules}/{len(rule_states)}. In OR si esce solo quando nessuna resta attiva.")
        lines.append("Dettaglio regole:")
        for rule_state in rule_states:
            lines.append(f"- {_describe_rule_at_position(rule_state, position=signal_position, side=side)}")

    return lines


def _marker_trigger_position(execution_position: int | None) -> int | None:
    if execution_position is None:
        return None
    return max(execution_position - 1, 0)


def _describe_rule_at_position(rule_state: dict[str, object], *, position: int, side: str) -> str:
    strategy_id = str(rule_state.get("strategy_id", ""))
    label = str(rule_state.get("label") or strategy_id)
    parameters = rule_state.get("parameters") or {}

    if strategy_id in {"sma_cross", "ema_cross", "obv_trend"}:
        fast_value = _series_value(rule_state.get("fast_series"), position)
        slow_value = _series_value(rule_state.get("slow_series"), position)
        if fast_value is None or slow_value is None:
            return f"{label}: valori non ancora disponibili su questa candela."
        operator = ">" if fast_value > slow_value else "<="
        metric_name = "OBV" if strategy_id == "obv_trend" else ("EMA" if strategy_id == "ema_cross" else "SMA")
        fast_label = int(parameters.get("fast", 0))
        slow_label = int(parameters.get("slow", 0))
        reason = "conferma long" if side == "entry" else ("perdita del long" if fast_value <= slow_value else "regola ancora long")
        return (
            f"{label}: {metric_name} {fast_label} {_format_trade_price(fast_value)} {operator} "
            f"{metric_name} {slow_label} {_format_trade_price(slow_value)} ({reason})."
        )

    if strategy_id == "rsi_mean_reversion":
        rsi_value = _series_value(rule_state.get("rsi"), position)
        if rsi_value is None:
            return f"{label}: RSI non disponibile su questa candela."
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        if side == "entry":
            verdict = f"RSI {rsi_value:.2f} <= soglia ingresso {lower:.2f}" if rsi_value <= lower else f"RSI {rsi_value:.2f} sopra soglia ingresso {lower:.2f}"
        else:
            verdict = f"RSI {rsi_value:.2f} >= soglia uscita {upper:.2f}" if rsi_value >= upper else f"RSI {rsi_value:.2f} sotto soglia uscita {upper:.2f}"
        return f"{label}: {verdict}."

    if strategy_id == "macd_trend":
        macd_value = _series_value(rule_state.get("macd"), position)
        signal_value = _series_value(rule_state.get("signal_line"), position)
        if macd_value is None or signal_value is None:
            return f"{label}: MACD non disponibile su questa candela."
        operator = ">" if macd_value > signal_value else "<="
        reason = "trend favorevole" if side == "entry" and macd_value > signal_value else ("trend debole" if side == "exit" and macd_value <= signal_value else "stato invariato")
        return f"{label}: MACD {_format_trade_price(macd_value)} {operator} signal {_format_trade_price(signal_value)} ({reason})."

    if strategy_id == "bollinger_reversion":
        basis = _series_value(rule_state.get("basis"), position)
        lower_band = _series_value(rule_state.get("lower_band"), position)
        close_value = _series_value(rule_state.get("frame_close"), position)
        if basis is None or lower_band is None:
            return f"{label}: bande non disponibili su questa candela."
        close_display = _format_trade_price(close_value) if close_value is not None else "n/d"
        if side == "entry":
            verdict = f"close {close_display} <= lower band {_format_trade_price(lower_band)}"
        else:
            verdict = f"close {close_display} >= basis {_format_trade_price(basis)}"
        return f"{label}: {verdict}."

    if strategy_id == "stochastic_reversion":
        slow_k = _series_value(rule_state.get("slow_k"), position)
        slow_d = _series_value(rule_state.get("slow_d"), position)
        if slow_k is None or slow_d is None:
            return f"{label}: Stochastic non disponibile su questa candela."
        lower = float(parameters["lower"])
        upper = float(parameters["upper"])
        if side == "entry":
            verdict = f"%K {slow_k:.2f} <= {lower:.2f} e %K > %D ({slow_d:.2f})" if slow_k <= lower and slow_k > slow_d else f"%K {slow_k:.2f}, %D {slow_d:.2f}"
        else:
            verdict = f"%K {slow_k:.2f} >= {upper:.2f} e %K < %D ({slow_d:.2f})" if slow_k >= upper and slow_k < slow_d else f"%K {slow_k:.2f}, %D {slow_d:.2f}"
        return f"{label}: {verdict}."

    if strategy_id == "cci_reversion":
        cci_value = _series_value(rule_state.get("cci"), position)
        if cci_value is None:
            return f"{label}: CCI non disponibile su questa candela."
        threshold = float(parameters["lower"] if side == "entry" else parameters["upper"])
        operator = "<=" if side == "entry" else ">="
        return f"{label}: CCI {cci_value:.2f} {operator} {threshold:.2f}."

    if strategy_id == "williams_r_reversion":
        wr_value = _series_value(rule_state.get("williams_r"), position)
        if wr_value is None:
            return f"{label}: Williams %R non disponibile su questa candela."
        threshold = float(parameters["lower"] if side == "entry" else parameters["upper"])
        operator = "<=" if side == "entry" else ">="
        return f"{label}: Williams %R {wr_value:.2f} {operator} {threshold:.2f}."

    if strategy_id == "adx_trend":
        adx_value = _series_value(rule_state.get("adx"), position)
        plus_di = _series_value(rule_state.get("plus_di"), position)
        minus_di = _series_value(rule_state.get("minus_di"), position)
        if adx_value is None or plus_di is None or minus_di is None:
            return f"{label}: ADX non disponibile su questa candela."
        threshold = float(parameters["threshold"])
        if side == "entry":
            verdict = (
                f"ADX {adx_value:.2f} >= {threshold:.2f} e +DI {plus_di:.2f} > -DI {minus_di:.2f}"
                if adx_value >= threshold and plus_di > minus_di
                else f"ADX {adx_value:.2f}, +DI {plus_di:.2f}, -DI {minus_di:.2f}"
            )
        else:
            verdict = (
                f"ADX {adx_value:.2f} < {threshold:.2f} oppure +DI {plus_di:.2f} <= -DI {minus_di:.2f}"
                if adx_value < threshold or plus_di <= minus_di
                else f"ADX {adx_value:.2f}, +DI {plus_di:.2f}, -DI {minus_di:.2f}"
            )
        return f"{label}: {verdict}."

    return f"{label}: stato della regola disponibile, dettaglio non ancora specializzato."


def _series_value(series: object, position: int) -> float | None:
    if not isinstance(series, pd.Series) or position < 0 or position >= len(series.index):
        return None
    return _to_float(series.iloc[position])


def _series_flag(series: object, position: int) -> bool:
    value = _series_value(series, position)
    return bool(value and value > 0)


def build_trade_preview(
    trades: pd.DataFrame,
    limit: int | None,
    marker_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if trades.empty:
        return []

    normalized = _sort_trades_chronologically(trades.fillna(""))
    if limit is not None:
        normalized = normalized.head(limit)
    rows = normalized.to_dict(orient="records")
    return [
        _format_trade_preview_row(
            row,
            sequence=index,
            marker_context=marker_context,
        )
        for index, row in enumerate(rows, start=1)
    ]


def _sort_trades_chronologically(trades: pd.DataFrame) -> pd.DataFrame:
    sorted_frame = trades.copy()
    sorted_frame["__entry_sort"] = pd.to_datetime(sorted_frame.get("entry_date", ""), errors="coerce")
    sorted_frame["__exit_sort"] = pd.to_datetime(sorted_frame.get("exit_date", ""), errors="coerce")
    sorted_frame["__order"] = range(len(sorted_frame.index))
    sorted_frame = sorted_frame.sort_values(
        by=["__entry_sort", "__exit_sort", "__order"],
        ascending=[True, True, True],
        na_position="last",
        kind="stable",
    )
    return sorted_frame.drop(columns=["__entry_sort", "__exit_sort", "__order"], errors="ignore")


def _format_trade_preview_row(
    row: dict[str, object],
    *,
    sequence: int,
    marker_context: dict[str, object] | None = None,
) -> dict[str, object]:
    entry_raw = str(row.get("entry_date", "")).strip()
    exit_raw = str(row.get("exit_date", "")).strip()
    entry_date_display, entry_time_display = _split_trade_timestamp(entry_raw)
    exit_date_display, exit_time_display = _split_trade_timestamp(exit_raw) if exit_raw else ("In corso", "")
    pnl_value = _to_float(row.get("pnl_pct"))
    status_label, status_class = _trade_status(exit_raw=exit_raw, pnl_value=pnl_value)
    detail_context = marker_context or {}
    entry_detail_text = (
        _build_trade_marker_popup_text(
            trade=row,
            side="entry",
            trade_date=entry_raw,
            price=_to_float(row.get("entry_price")) or 0.0,
            pnl=str(row.get("pnl_pct", "")).strip() or "open",
            marker_context=detail_context,
        )
        if entry_raw and marker_context
        else ""
    )
    exit_detail_text = (
        _build_trade_marker_popup_text(
            trade=row,
            side="exit",
            trade_date=exit_raw,
            price=_to_float(row.get("exit_price")) or 0.0,
            pnl=str(row.get("pnl_pct", "")).strip() or "open",
            marker_context=detail_context,
        )
        if exit_raw and marker_context
        else "Operazione ancora aperta: non esiste ancora una candela di uscita da analizzare."
    )

    direzione = str(row.get("direction", "") or "long").strip().lower()
    return {
        "sequence": sequence,
        "status_label": status_label,
        "status_class": status_class,
        # Verso dell'operazione: i report salvati prima del supporto al ribasso
        # non hanno la colonna, e in quel caso erano tutte al rialzo.
        "direction": direzione,
        "direction_display": "Ribasso" if direzione == "short" else "Rialzo",
        "detail_title": f"Operazione #{sequence}",
        "entry_raw": entry_raw,
        "exit_raw": exit_raw,
        "entry_price_display": _format_trade_price(row.get("entry_price")),
        "exit_price_display": _format_trade_price(row.get("exit_price")) if exit_raw else "In corso",
        "entry_date_display": entry_date_display,
        "entry_time_display": entry_time_display,
        "exit_date_display": exit_date_display,
        "exit_time_display": exit_time_display,
        "pnl_display": f"{pnl_value:+.2f}%" if pnl_value is not None else "-",
        "duration_display": _format_trade_duration(
            entry_raw=entry_raw,
            exit_raw=exit_raw,
            fallback_days=row.get("holding_days"),
        ),
        "entry_detail_text": entry_detail_text,
        "exit_detail_text": exit_detail_text,
    }


def _split_trade_timestamp(raw: str) -> tuple[str, str]:
    if not raw:
        return "-", ""

    timestamp = pd.to_datetime(raw, errors="coerce")
    if pd.isna(timestamp):
        return raw, ""

    if ":" in raw:
        return timestamp.strftime("%d/%m/%Y"), timestamp.strftime("%H:%M")
    return timestamp.strftime("%d/%m/%Y"), ""


def _trade_status(exit_raw: str, pnl_value: float | None) -> tuple[str, str]:
    if not exit_raw:
        return "OPEN", "open"
    if pnl_value is None:
        return "CLOSED", "neutral"
    if pnl_value > 0:
        return "WIN", "positive"
    if pnl_value < 0:
        return "LOSS", "negative"
    return "FLAT", "neutral"


def _closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "exit_date" not in trades.columns:
        return trades.iloc[0:0].copy()
    closed_mask = trades["exit_date"].astype(str).str.strip() != ""
    return trades.loc[closed_mask].copy()


def _trade_duration_minutes(entry_raw: str, exit_raw: str) -> int | None:
    if not entry_raw or not exit_raw:
        return None

    entry_ts = pd.to_datetime(entry_raw, errors="coerce")
    exit_ts = pd.to_datetime(exit_raw, errors="coerce")
    if pd.isna(entry_ts) or pd.isna(exit_ts):
        return None
    return max(int((exit_ts - entry_ts).total_seconds() // 60), 0)


def _format_trade_duration(entry_raw: str, exit_raw: str, fallback_days: object) -> str:
    if not entry_raw or not exit_raw:
        return "In corso"

    total_minutes = _trade_duration_minutes(entry_raw=entry_raw, exit_raw=exit_raw)
    if total_minutes is not None:
        return _format_duration_from_minutes(total_minutes)

    days_value = _to_float(fallback_days)
    if days_value is None:
        return "-"
    if days_value == 1:
        return "1 g"
    return f"{int(days_value)} g"


def _format_duration_from_minutes(total_minutes: int | float | None) -> str:
    if total_minutes is None:
        return "n/d"

    minutes_int = max(int(round(float(total_minutes))), 0)
    days = minutes_int // (24 * 60)
    hours = (minutes_int % (24 * 60)) // 60
    minutes = minutes_int % 60
    if days > 0:
        return f"{days} g {hours} h" if hours else f"{days} g"
    if hours > 0:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    if minutes > 0:
        return f"{minutes} min"
    return "< 1 min"


def _format_trade_price(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:.4f}".rstrip("0").rstrip(".")


def _compute_drawdown_pct(series: pd.Series) -> float:
    numeric_series = pd.to_numeric(series, errors="coerce").dropna()
    if numeric_series.empty:
        return 0.0
    rolling_peak = numeric_series.cummax().replace(0.0, pd.NA)
    drawdown = ((numeric_series / rolling_peak) - 1.0).fillna(0.0) * 100
    return round(float(drawdown.min()), 2)


def _format_terminal_number(value: float | None, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _format_signed_number(value: float | None, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _format_signed_percent(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def _format_compact_number(value: float, decimals: int = 1) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    return _format_terminal_number(value, decimals=0)


def _to_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_signed_int(value: int) -> str:
    return f"{value:+d}"


def _last_series_value(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.iloc[-1])


def _build_consistency_check(
    *,
    label: str,
    summary_value: float | None,
    file_value: float | None,
    summary_display: str,
    file_display: str,
    tolerance: float,
    ok_hint: str,
    mismatch_hint: str,
) -> dict[str, str]:
    if summary_value is None or file_value is None:
        return {
            "label": label,
            "status_label": "N/D",
            "status_class": "neutral",
            "value": f"summary {summary_display} · file {file_display}",
            "hint": "Dati non sufficienti per verificare questo controllo.",
        }

    if abs(summary_value - file_value) <= tolerance:
        return {
            "label": label,
            "status_label": "OK",
            "status_class": "positive",
            "value": f"summary {summary_display} · file {file_display}",
            "hint": ok_hint,
        }

    return {
        "label": label,
        "status_label": "ATTENZIONE",
        "status_class": "warning",
        "value": f"summary {summary_display} · file {file_display}",
        "hint": mismatch_hint,
    }


def _has_summary_enrichment(summary: dict[str, object]) -> bool:
    return all(
        key in summary
        for key in (
            "benchmark_return_pct",
            "benchmark_final_equity",
            "benchmark_max_drawdown_pct",
            "excess_return_pct",
            "fees_paid",
            "fees_paid_pct_initial_capital",
            "fee_drag_equity",
            "gross_final_equity",
        )
    )


def _read_summary_enrichment_curve(item_dir: Path) -> pd.DataFrame:
    for filename in ("equity_curve.csv", "best_equity_curve.csv"):
        candidate = item_dir / filename
        if candidate.exists():
            return pd.read_csv(candidate)
    raise FileNotFoundError(f"No equity curve found in '{item_dir}'.")


def _ensure_gross_equity(equity_curve: pd.DataFrame, initial_capital: float) -> pd.Series:
    if "gross_equity" in equity_curve.columns:
        return equity_curve["gross_equity"].astype(float)

    if "gross_strategy_return" in equity_curve.columns:
        gross_returns = equity_curve["gross_strategy_return"].astype(float)
    elif all(column in equity_curve.columns for column in ("position", "market_return")):
        gross_returns = equity_curve["position"].astype(float) * equity_curve["market_return"].astype(float)
    elif "equity" in equity_curve.columns:
        return equity_curve["equity"].astype(float)
    else:
        return pd.Series([float(initial_capital)], dtype=float)
    return initial_capital * (1 + gross_returns).cumprod()


def _ensure_transaction_cost_amount(equity_curve: pd.DataFrame, initial_capital: float) -> pd.Series:
    if "transaction_cost_amount" in equity_curve.columns:
        return equity_curve["transaction_cost_amount"].astype(float)

    if "transaction_cost_rate" in equity_curve.columns:
        transaction_cost_rate = equity_curve["transaction_cost_rate"].astype(float)
    elif all(column in equity_curve.columns for column in ("position", "market_return", "strategy_return")):
        gross_returns = equity_curve["position"].astype(float) * equity_curve["market_return"].astype(float)
        transaction_cost_rate = (gross_returns - equity_curve["strategy_return"].astype(float)).clip(lower=0.0)
    elif "equity" in equity_curve.columns:
        return pd.Series([0.0] * len(equity_curve.index), index=equity_curve.index, dtype=float)
    else:
        return pd.Series([0.0], dtype=float)

    equity_before = equity_curve["equity"].astype(float).shift(1).fillna(initial_capital)
    return equity_before * transaction_cost_rate


def _read_trades(path: Path) -> pd.DataFrame:
    try:
        trades = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

    if trades.empty and not list(trades.columns):
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

    for column in EMPTY_TRADE_COLUMNS:
        if column not in trades.columns:
            trades[column] = ""
    return trades
