from __future__ import annotations

from pathlib import Path

from trading_bot.strategies import strategy_options

DEFAULT_REPORTS_DIR = Path("reports")
INTERVAL_OPTIONS = ("1m", "2m", "5m", "15m", "30m", "1h", "90m", "1d", "1wk", "1mo")
RUN_MODE_OPTIONS = ("single", "sweep", "walkforward")
RULE_LOGIC_OPTIONS = {
    "all": "Devono valere tutte (AND)",
    "any": "Ne basta una (OR)",
}
SWEEP_SORT_OPTIONS = {
    "total_return_pct": "Best rendimento totale",
    "excess_return_pct": "Best delta vs hold",
    "sharpe_ratio": "Best Sharpe",
    "max_drawdown_pct": "Best max drawdown",
}
STRATEGY_OPTIONS = strategy_options()
PRESETS_FILENAME = "strategy_presets.json"

SIZING_OPTIONS = {
    "full":       "Tutto il capitale (default)",
    "fixed":      "Frazione fissa (%)",
    "vol_target": "Target volatilità (%/anno)",
}

WALKFORWARD_SORT_OPTIONS = {
    "sharpe_ratio":    "Sharpe ratio",
    "total_return_pct": "Rendimento totale",
    "max_drawdown_pct": "Max drawdown",
}


# ── Costo di un'operazione, in lingua semplice ───────────────────────────────
# "5 bps" non dice niente a chi non lavora in finanza. Il form chiede che tipo
# di intermediario si usa e traduce la scelta in commissioni + slippage; chi sa
# cosa sono i basis point li imposta a mano nelle opzioni avanzate.
COSTI_OPERAZIONE = {
    "economico": {
        "label": "Broker economico — banche online, ETF molto scambiati",
        "fee_bps": 1.0,
        "slippage_bps": 1.0,
        "descrizione": "circa 2 € ogni 10.000 € scambiati",
    },
    "medio": {
        "label": "Situazione normale — la scelta prudente se non sai",
        "fee_bps": 5.0,
        "slippage_bps": 2.0,
        "descrizione": "circa 7 € ogni 10.000 € scambiati",
    },
    "caro": {
        "label": "Banca tradizionale, o mercati poco scambiati",
        "fee_bps": 15.0,
        "slippage_bps": 5.0,
        "descrizione": "circa 20 € ogni 10.000 € scambiati",
    },
}
COSTI_DEFAULT = "medio"
