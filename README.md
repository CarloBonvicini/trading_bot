# Trading Bot Research Starter

Starter leggero in Python per fare ricerca e backtest prima di costruire un bot live.

## Cosa include

- download dati storici con `yfinance`
- due strategie iniziali:
  - `sma_cross`
  - `rsi_mean_reversion`
- backtest long-only con costi di transazione
- report salvati in `reports/` con:
  - `summary.json`
  - `equity_curve.csv`
  - `trades.csv`

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Primo backtest

```powershell
trading-bot `
  --symbol SPY `
  --start 2018-01-01 `
  --end 2025-01-01 `
  --strategy sma_cross `
  --fast 20 `
  --slow 100
```

Esempio con RSI:

```powershell
trading-bot `
  --symbol BTC-USD `
  --start 2020-01-01 `
  --end 2025-01-01 `
  --strategy rsi_mean_reversion `
  --rsi-period 14 `
  --rsi-lower 30 `
  --rsi-upper 55
```

## Output

Ogni esecuzione crea una cartella in `reports/`:

```text
reports/
  SPY-sma_cross-20260402-224500/
    equity_curve.csv
    summary.json
    trades.csv
```

## Come usarlo bene

1. Parti con un solo mercato e un solo timeframe.
2. Testa idee semplici prima di aggiungere complessita'.
3. Confronta strategie usando drawdown, Sharpe, numero trade e stabilita'.
4. Passa a paper trading solo dopo un backtest sensato.

## Limiti di questa prima versione

- usa un modello semplice close-to-close
- e' long-only
- non gestisce ancora portfolio multi-asset
- non simula slippage avanzato o ordini intraday

Questo e' voluto: serve per scegliere velocemente una direzione di ricerca, non per andare live domani.

