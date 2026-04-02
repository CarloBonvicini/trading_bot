from __future__ import annotations

import argparse
from pathlib import Path

from trading_bot.backtest import run_backtest, save_report
from trading_bot.data import download_price_data
from trading_bot.strategies import rsi_mean_reversion, sma_crossover


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
    args = build_parser().parse_args()
    data = download_price_data(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        interval=args.interval,
    )

    if args.strategy == "sma_cross":
        signal = sma_crossover(data, fast=args.fast, slow=args.slow)
    else:
        signal = rsi_mean_reversion(
            data,
            period=args.rsi_period,
            lower=args.rsi_lower,
            upper=args.rsi_upper,
        )

    result = run_backtest(
        data=data,
        signal=signal,
        initial_capital=args.initial_capital,
        fee_bps=args.fee_bps,
    )
    report_dir = save_report(
        result=result,
        output_dir=Path(args.output_dir),
        symbol=args.symbol,
        strategy_name=args.strategy,
    )

    print(f"Report saved to: {report_dir}")
    for key, value in result.summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

