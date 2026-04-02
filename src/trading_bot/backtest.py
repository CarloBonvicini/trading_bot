from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestResult:
    summary: dict[str, float | int | str]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame


def run_backtest(
    data: pd.DataFrame,
    signal: pd.Series,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
) -> BacktestResult:
    if "close" not in data.columns:
        raise ValueError("The input data must contain a 'close' column.")
    if initial_capital <= 0:
        raise ValueError("Initial capital must be positive.")
    if fee_bps < 0:
        raise ValueError("fee_bps cannot be negative.")

    close = data["close"].astype(float)
    position = signal.reindex(data.index).fillna(0.0).clip(lower=0.0, upper=1.0)
    executed_position = position.shift(1).fillna(0.0)
    daily_returns = close.pct_change().fillna(0.0)
    position_change = executed_position.diff().abs().fillna(executed_position.abs())
    transaction_cost = position_change * (fee_bps / 10_000.0)
    strategy_returns = (executed_position * daily_returns) - transaction_cost

    equity = initial_capital * (1 + strategy_returns).cumprod()
    benchmark_equity = initial_capital * (1 + daily_returns).cumprod()
    drawdown = equity / equity.cummax() - 1

    equity_curve = pd.DataFrame(
        {
            "close": close,
            "signal": position,
            "position": executed_position,
            "market_return": daily_returns,
            "strategy_return": strategy_returns,
            "equity": equity,
            "benchmark_equity": benchmark_equity,
            "drawdown": drawdown,
        }
    )

    trades = _build_trades(close=close, position=executed_position)
    summary = _build_summary(
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=initial_capital,
    )
    return BacktestResult(summary=summary, equity_curve=equity_curve, trades=trades)


def save_report(
    result: BacktestResult,
    output_dir: str | Path,
    symbol: str,
    strategy_name: str,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = Path(output_dir) / f"{symbol.replace('/', '_')}-{strategy_name}-{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    with (report_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(result.summary, handle, indent=2)

    result.equity_curve.to_csv(report_dir / "equity_curve.csv", index_label="date")
    result.trades.to_csv(report_dir / "trades.csv", index=False)
    return report_dir


def _build_summary(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
) -> dict[str, float | int | str]:
    strategy_returns = equity_curve["strategy_return"]
    final_equity = float(equity_curve["equity"].iloc[-1])
    benchmark_final_equity = float(equity_curve["benchmark_equity"].iloc[-1])
    total_return = (final_equity / initial_capital) - 1
    benchmark_return = (benchmark_final_equity / initial_capital) - 1
    periods = len(equity_curve)
    years = periods / TRADING_DAYS_PER_YEAR if periods else 0.0
    annual_return = (final_equity / initial_capital) ** (1 / years) - 1 if years > 0 else 0.0
    annual_volatility = strategy_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe_ratio = (
        strategy_returns.mean() / strategy_returns.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if annual_volatility > 0
        else 0.0
    )

    return {
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "benchmark_final_equity": round(benchmark_final_equity, 2),
        "excess_return_pct": round((total_return - benchmark_return) * 100, 2),
        "annual_return_pct": round(annual_return * 100, 2),
        "annual_volatility_pct": round(annual_volatility * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 3),
        "max_drawdown_pct": round(float(equity_curve["drawdown"].min()) * 100, 2),
        "trade_count": int(len(trades)),
        "exposure_pct": round(float(equity_curve["position"].mean()) * 100, 2),
        "benchmark_return_pct": round(benchmark_return * 100, 2),
    }


def _build_trades(close: pd.Series, position: pd.Series) -> pd.DataFrame:
    position_change = position.diff().fillna(position)
    entries = position_change[position_change > 0]
    exits = position_change[position_change < 0]
    exit_dates = list(exits.index)
    trades: list[dict[str, object]] = []

    for index, entry_date in enumerate(entries.index):
        exit_date = exit_dates[index] if index < len(exit_dates) else None
        entry_price = float(close.loc[entry_date])
        exit_price = float(close.loc[exit_date]) if exit_date is not None else None
        pnl_pct = ((exit_price / entry_price) - 1) * 100 if exit_price is not None else None
        holding_days = int((exit_date - entry_date).days) if exit_date is not None else None
        trades.append(
            {
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "entry_price": round(entry_price, 4),
                "exit_date": exit_date.strftime("%Y-%m-%d") if exit_date is not None else "",
                "exit_price": round(exit_price, 4) if exit_price is not None else "",
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else "",
                "holding_days": holding_days if holding_days is not None else "",
            }
        )

    return pd.DataFrame(trades)
