from __future__ import annotations

from pathlib import Path

from trading_bot.strategies import strategy_options

DEFAULT_REPORTS_DIR = Path("reports")
INTERVAL_OPTIONS = ("1m", "2m", "5m", "15m", "30m", "1h", "90m", "1d", "1wk", "1mo")
RUN_MODE_OPTIONS = ("single", "sweep")
SWEEP_SORT_OPTIONS = {
    "total_return_pct": "Best rendimento totale",
    "excess_return_pct": "Best delta vs hold",
    "sharpe_ratio": "Best Sharpe",
    "max_drawdown_pct": "Best max drawdown",
}
STRATEGY_OPTIONS = strategy_options()
PRESETS_FILENAME = "strategy_presets.json"
