# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandi essenziali

```powershell
# Setup ambiente (prima volta)
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]

# Avviare la dashboard web (localhost:8000)
trading-bot-web

# Eseguire un backtest da CLI
trading-bot --symbol SPY --start 2020-01-01 --end 2025-01-01 --strategy sma_cross --fast 20 --slow 100

# Eseguire i test (suite veloce, ~5 secondi)
python -m pytest

# Eseguire anche i test marcati "lento" (ricerche vere, ~75 secondi)
python -m pytest --lenti

# Eseguire un singolo file di test
python -m pytest tests/test_backtest.py

# Eseguire un singolo test
python -m pytest tests/test_backtest.py::nome_funzione
```

### Regole sui test

- **Sempre `python -m pytest` dalla radice del progetto.** Il pacchetto è
  installato in editable mode e punta a un solo checkout: lanciato altrimenti,
  Python importa quello invece del codice su cui stai lavorando. In un worktree
  serve un ambiente virtuale suo (`python -m venv .venv` +
  `.venv\Scripts\python -m pip install -e .[dev]`) oppure `PYTHONPATH=src`. La
  guardia in `conftest.py` ferma la sessione se il modulo importato non è quello
  del checkout corrente.
- **Gli avvisi di deprecazione sono errori** (`filterwarnings` nel
  `pyproject.toml`): un `FutureWarning` di pandas ignorato è codice che smetterà
  di funzionare a un aggiornamento.
- **I dati sintetici vengono da `conftest.py`** (`mercato_sintetico`,
  `ohlc_da_chiusure`, `mercato_piatto`): non ridichiarare generatori nei singoli
  file di test.
- **`@pytest.mark.lento`** per i test che eseguono ricerche vere, così la suite
  di default resta sotto i cinque secondi. La CI li esegue comunque.

## Architettura

Il flusso dati segue sempre questa pipeline unidirezionale:

```
data.py → strategies.py → backtest.py → reporting.py / templates
```

Il layer `application/` orchestra questa pipeline senza contenere logica di business propria:

- **`application/requests.py`** — parse e validazione dell'input (da form o CLI) in `BacktestRequest` / `SweepRequest`. Tutta la validazione di input vive qui via `FormValidationError`.
- **`application/execution.py`** — collega i moduli core: scarica i dati, costruisce il segnale, esegue il backtest, salva il report. Punto di ingresso per web e CLI.
- **`application/constants.py`** — valori di configurazione condivisi (intervalli, opzioni UI, directory default).
- **`application/presets.py`** — serializzazione/deserializzazione dei preset in `reports/strategy_presets.json`.
- **`application/dashboard.py`** — aggrega statistiche da tutti i report salvati per la home page.
- **`application/forms.py`** — conversione bidirezionale tra `BacktestRequest` e valori del form HTML.
- **`application/chart_lab.py`** — preview indicatori per il strategy lab.
- **`application/strategy_search.py`** — ricerca automatica della strategia migliore su un mercato (holdout finale + walk-forward + prova su dati nuovi). L'affidabilità si misura sul **margine rispetto al comprare-e-tenere** (`excess_return_pct`), mai sullo zero: il motore è long-only, quindi in un periodo di prova al ribasso nessuna strategia potrebbe guadagnare in assoluto. Le strategie sono valutate in parallelo su più processi quando il lavoro supera `SOGLIA_PARALLELO` (`max_workers=1` forza il sequenziale).
- **`application/multi_search.py`** — la stessa ricerca su più mercati insieme, aggregata per strategia (quanti mercati ha battuto, con quale margine medio).

### Moduli core

- **`data.py`** — download OHLCV via yfinance, gestione limiti intraday (1m=8gg, 5m=60gg, 1h=730gg), alias simboli (es. GOLD→GC=F). Sempre chiama `coerce_interval_date_window()` prima del download. Gli scaricamenti sono messi in cache su disco in `reports/.cache_dati` (12 ore se la finestra arriva a oggi, 30 giorni se è tutta nel passato); `use_cache=False` la salta, `clear_data_cache()` la svuota.
- **`strategies.py`** — 10 funzioni strategia + `STRATEGY_SPECS` (dizionario con metadati/parametri per ogni strategia) + `STRATEGY_FUNCTIONS` (mapping id→funzione). Per aggiungere una strategia: implementa la funzione, aggiungila ad entrambi i dizionari, crea il `StrategySpec`. Le strategie mean-reversion usano `_stateful_signal()` per tracciare lo stato entry/exit. Le strategie con `supports_sweep=True` supportano lo sweep parametri.
- **`backtest.py`** — engine puro: prende `data` e `signal` (pd.Series 0/1), restituisce `BacktestResult`. Il position shift di 1 barra è critico per evitare lookahead bias — non rimuoverlo mai. Fee simulate in basis points. L'annualizzazione (CAGR, volatilità, Sharpe, Sortino) usa `infer_periods_per_year()`, che deduce le barre per anno dal calendario: 252 sul giornaliero, `252 × barre al giorno` sull'intraday.
- **`walkforward.py`** — finestre IS/OOS scorrevoli. Il segnale di ogni combinazione si calcola **una volta sull'intera serie** e poi si ritaglia sulla finestra: è il warm-up degli indicatori (senza, un indicatore più lungo della finestra resta piatto a zero) ed evita di ricalcolare lo stesso segnale per ogni finestra. A parità di punteggio vince sempre una combinazione che ha operato: quelle inerti hanno Sharpe 0 secco e batterebbero tutte quelle in perdita.
- **`reporting.py`** — trasforma `BacktestResult` in payload per la UI (card summary, dati grafico). Label italiane in `SUMMARY_LABELS`.
- **`errors.py`** — `FormValidationError` con tracking dei campi per evidenziazione UI.

### Interfacce

- **`web.py`** — app Flask. Routes principali: `/` (dashboard), `/backtests/new` (form), `/strategies` (strategy builder), `/history`, `/api/*` (JSON per preview indicatori e stato form). Sempre usa `BacktestRequest.from_mapping(request.form)` per parsare i form.
- **`cli.py`** — argparse, entrypoint `trading-bot`. Costruisce un `BacktestRequest` e chiama `run_backtest_request()`.

### Output su disco

Ogni run crea una cartella in `reports/`:
```
SYMBOL-STRATEGY-TIMESTAMP/
  summary.json        # 15+ metriche di performance
  metadata.json       # config del backtest (simbolo, date, parametri, preset)
  equity_curve.csv    # serie temporale giornaliera con equity, drawdown, signal
  trades.csv          # lista trade entry/exit con P&L
```
Lo sweep aggiunge: `results.csv`, `best_summary.json`, `best_equity_curve.csv`, `best_trades.csv`.

I nomi delle colonne e le chiavi JSON dei file salvati sono un'interfaccia pubblica: non cambiarli senza migrare i report esistenti.

## Regole del progetto

### Sempre
- **Lingua italiana** — variabili, commenti, messaggi UI, errori: tutto in italiano.
- **Nessun lookahead bias** — il position shift in `backtest.py` (`.shift(1)`) non si tocca.
- **Report retrocompatibili** — nessuna modifica ai nomi di chiavi in `summary.json`, `metadata.json`, `equity_curve.csv`, `trades.csv` senza gestire i report vecchi.
- **Un file = una responsabilità** — non mescolare logica di business con routing Flask o rendering UI.

### Con giudizio
- **Test obbligatori** per logica di backtest e strategie; opzionali per UI e utility.
- **Nuove dipendenze** si aggiungono solo se giustificate; si preferisce usare ciò che c'è già (flask, pandas, yfinance).
- **Nessun commit con test rotti** — se un test esiste, deve passare.

### Mai
- Il bot rimane locale: nessuna chiamata a server esterni non documentata.
- Nessuna feature lasciata a metà nel codebase — o funziona o non esiste.

## Aggiungere una nuova strategia

1. Implementa la funzione in `strategies.py` con firma `(data: pd.DataFrame, **params) -> pd.Series`.
2. Aggiungila a `STRATEGY_FUNCTIONS` e crea il suo `StrategySpec` in `STRATEGY_SPECS`.
3. Se usa high/low/volume, chiama `_require_columns()` prima di accedere alle colonne.
4. Se è mean-reversion con stato, usa `_stateful_signal()`.
5. Se supporta sweep parametri, imposta `supports_sweep=True` nello `StrategySpec`.
