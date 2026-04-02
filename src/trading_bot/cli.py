from __future__ import annotations

import argparse

from trading_bot.services import BacktestRequest, STRATEGY_OPTIONS, run_backtest_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a simple strategy backtest.")
    parser.add_argument("--symbol", required=True, help="Ticker or symbol, for example SPY or BTC-USD.")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument("--interval", default="1d", help="Data interval. Default: 1d.")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=sorted(STRATEGY_OPTIONS.keys()),
        help="Strategy to test.",
    )
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Initial capital.")
    parser.add_argument("--fee-bps", type=float, default=5.0, help="Fee in basis points per position change.")
    parser.add_argument("--fast", type=int, default=20, help="Fast window for crossover-based strategies.")
    parser.add_argument("--slow", type=int, default=100, help="Slow window for crossover-based strategies.")
    parser.add_argument("--period", type=int, default=14, help="Generic period for RSI, CCI, Williams, ADX or Bollinger.")
    parser.add_argument("--lower", type=float, default=30.0, help="Generic lower entry threshold for mean reversion strategies.")
    parser.add_argument("--upper", type=float, default=55.0, help="Generic upper exit threshold for mean reversion strategies.")
    parser.add_argument("--signal", type=int, default=9, help="Signal window for MACD.")
    parser.add_argument("--std-dev", type=float, default=2.0, help="Standard deviation multiplier for Bollinger bands.")
    parser.add_argument("--k-period", type=int, default=14, help="Stochastic K period.")
    parser.add_argument("--d-period", type=int, default=3, help="Stochastic D period.")
    parser.add_argument("--smooth", type=int, default=3, help="Stochastic smoothing.")
    parser.add_argument("--threshold", type=float, default=25.0, help="Generic strength threshold, for example ADX.")
    parser.add_argument("--output-dir", default="reports", help="Directory for generated reports.")
    return parser


def main() -> None:
    parsed = build_parser().parse_args()
    backtest_request = BacktestRequest.from_mapping(
        {
            "symbol": parsed.symbol,
            "start": parsed.start,
            "end": parsed.end,
            "interval": parsed.interval,
            "strategy": parsed.strategy,
            "initial_capital": parsed.initial_capital,
            "fee_bps": parsed.fee_bps,
            "fast": parsed.fast,
            "slow": parsed.slow,
            "period": parsed.period,
            "lower": parsed.lower,
            "upper": parsed.upper,
            "signal": parsed.signal,
            "std_dev": parsed.std_dev,
            "k_period": parsed.k_period,
            "d_period": parsed.d_period,
            "smooth": parsed.smooth,
            "threshold": parsed.threshold,
        }
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
