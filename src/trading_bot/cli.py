from __future__ import annotations

import argparse

from trading_bot.services import BacktestRequest, run_backtest_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a simple strategy backtest.")
    parser.add_argument("--symbol", required=True, help="Ticker or symbol, for example SPY or BTC-USD.")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument("--interval", default="1d", help="Data interval. Default: 1d.")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["sma_cross", "rsi_mean_reversion"],
        help="Strategy to test.",
    )
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Initial capital.")
    parser.add_argument("--fee-bps", type=float, default=5.0, help="Fee in basis points per position change.")
    parser.add_argument("--fast", type=int, default=20, help="Fast moving average window for sma_cross.")
    parser.add_argument("--slow", type=int, default=100, help="Slow moving average window for sma_cross.")
    parser.add_argument("--rsi-period", type=int, default=14, help="RSI window for rsi_mean_reversion.")
    parser.add_argument("--rsi-lower", type=float, default=30.0, help="Entry threshold for rsi_mean_reversion.")
    parser.add_argument("--rsi-upper", type=float, default=55.0, help="Exit threshold for rsi_mean_reversion.")
    parser.add_argument("--output-dir", default="reports", help="Directory for generated reports.")
    return parser


def main() -> None:
    parsed = build_parser().parse_args()
    backtest_request = BacktestRequest(
        symbol=parsed.symbol,
        start=parsed.start,
        end=parsed.end,
        interval=parsed.interval,
        strategy=parsed.strategy,
        initial_capital=parsed.initial_capital,
        fee_bps=parsed.fee_bps,
        fast=parsed.fast,
        slow=parsed.slow,
        rsi_period=parsed.rsi_period,
        rsi_lower=parsed.rsi_lower,
        rsi_upper=parsed.rsi_upper,
    )
    completed = run_backtest_request(
        backtest_request=backtest_request,
        output_dir=parsed.output_dir,
    )

    print(f"Report saved to: {completed.report_dir}")
    for key, value in completed.result.summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
