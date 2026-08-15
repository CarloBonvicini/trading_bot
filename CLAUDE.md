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

# Eseguire i test (suite veloce, ~8 secondi)
python -m pytest

# Eseguire anche i test marcati "lento" (ricerche vere, ~4 minuti)
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
- **La rete di sicurezza sui segnali** (`tests/test_impronte_strategie.py`) congela il
  comportamento di tutte le strategie su tutta la griglia: se rifattorizzi gli indicatori
  e un solo segnale cambia, il test fallisce e dice dove. Le impronte si rigenerano solo
  dopo una modifica **voluta**, con `python tests/test_impronte_strategie.py --rigenera`:
  se ti trovi a rigenerarle per far passare il test, fermati.
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
- **`application/strategy_search.py`** — ricerca automatica della strategia migliore su un mercato (holdout finale + walk-forward + prova su dati nuovi). L'affidabilità si misura sul **margine rispetto al comprare-e-tenere** (`excess_return_pct`), mai sullo zero: in un periodo di prova al ribasso il confronto con lo zero boccerebbe anche chi ha limitato le perdite. Con `consenti_short` ogni strategia corre due volte (solo rialzo e nei due versi) come `Candidato` distinto, quindi il lavoro raddoppia. Le strategie sono valutate in parallelo su più processi quando il lavoro supera `SOGLIA_PARALLELO` (`max_workers=1` forza il sequenziale).
- **`application/prova_del_caso.py`** — la difesa contro il data mining: una ricerca a profondità media prova oltre 5.000 configurazioni per mercato, quindi la migliore *sembra* sempre buona. `mescola_serie()` permuta i rendimenti (stessa volatilità, zero struttura temporale) e la ricerca viene rifatta lì sopra: se la fortuna arriva dove è arrivata la strategia vera, nessuna vittoria viene riconosciuta. Con più mercati si usa `mescola_mercati()`, che applica **la stessa permutazione a tutti**: chi si muoveva insieme continua a muoversi insieme e a sparire è solo il tempo. Mescolarli uno per uno distruggerebbe anche la struttura *fra* i mercati, cioè la materia prima di una strategia trasversale, e la prova la passerebbe chiunque. Il confronto è sul **margine vs comprare-e-tenere**, mai sul rendimento assoluto (mescolando cambia anche il mercato di riferimento). `prova_dei_vicini()` in `strategy_search.py` è il controllo gemello sui parametri: se il vantaggio sparisce spostandoli di un passo nella griglia, quei numeri li hanno scelti i dati e la vittoria non viene riconosciuta. **Se nessun mercato produce una vittoria riconosciuta il verdetto non incorona nessuno**, per quanto alto sia il semaforo di affidabilità.
- **`application/portafoglio.py`** — il metro di paragone onesto: dividere i soldi in parti uguali fra i mercati in esame e stare fermi (o ribilanciare ogni mese). Confrontare una strategia col comprare-e-tenere di un **singolo** titolo la fa sembrare migliore di quanto sia rispetto a ciò che una persona farebbe davvero. Non ha più una matematica sua: le due versioni noiose sono due portafogli come gli altri (segnale sempre a 1) calcolati da `portafoglio.py`, e il ribilanciato mensile **paga le commissioni** con cui è misurata la strategia che gli si confronta.
- **`application/multi_search.py`** — la stessa ricerca su più mercati insieme, aggregata per strategia (quanti mercati ha battuto, con quale margine medio).
- **`application/ricerca_portafoglio.py`** — la ricerca del portafoglio migliore, con **budget dichiarato** (192 configurazioni: parametri della strategia × politica di allocazione × ribilanciamento). Se la griglia supera il budget la ricerca si ferma e lo dice: senza tetto dichiarato non si può sapere quanto sia facile vincere per caso. Riporta due numeri distinti — il margine **onesto** (scelto sullo sviluppo, misurato una volta sola sulla prova) e quello **col senno di poi** (la migliore sul periodo di prova, che non è un risultato ma la misura di quanto spazio c'era per illudersi). Su mercati senza struttura la procedura onesta non cava niente, mentre il senno di poi arriva a +20 punti: confonderli è il modo più facile di raccontarsi una bugia con dati veri.

### Moduli core

- **`data.py`** — download OHLCV via yfinance, gestione limiti intraday (1m=8gg, 5m=60gg, 1h=730gg), alias simboli (es. GOLD→GC=F). Sempre chiama `coerce_interval_date_window()` prima del download. Gli scaricamenti sono messi in cache su disco in `reports/.cache_dati` (12 ore se la finestra arriva a oggi, 30 giorni se è tutta nel passato); `use_cache=False` la salta, `clear_data_cache()` la svuota.
- **`features.py`** — registro degli indicatori e modelli stimati. I modelli (`mezza_vita`, `zscore`) ricavano i propri numeri dai dati invece di riceverli fissi: la stima è **mobile**, a ogni barra guarda solo le barre precedenti, quindi il lookahead è impedito per costruzione e non per attenzione. `tests/test_causalita.py` lo verifica su tutto il catalogo troncando e stravolgendo il futuro.
- **`features.py`** — registro degli indicatori. Un indicatore si dichiara con `@registra("nome")` e si usa con `indicatore("nome", data, **parametri)`. Il riuso avviene **solo** dentro `contesto_indicatori(data)` e **solo** se i dati sono lo stesso oggetto (confronto di identità): due mercati diversi, o la stessa storia rimescolata, non possono ereditare valori altrui. Fuori dal contesto tutto funziona come prima, senza risparmio — è ciò che rende sicura la migrazione una strategia alla volta.
- **`strategies.py`** — 10 funzioni strategia + `STRATEGY_SPECS` (dizionario con metadati/parametri per ogni strategia) + `STRATEGY_FUNCTIONS` (mapping id→funzione). Per aggiungere una strategia: implementa la funzione, aggiungila ad entrambi i dizionari, crea il `StrategySpec`. Le strategie mean-reversion usano `_segnale_speculare()` (che poggia su `_stateful_signal()`, a tre stati: -1/0/+1). Le strategie di tendenza usano `_verso_da_confronto()`. Le strategie con `supports_sweep=True` supportano lo sweep parametri; `supports_short=False` dichiara che non esiste una regola al ribasso sensata.
- **`backtest.py`** — engine puro: prende `data` e `signal` (pd.Series da -1 a +1: il **segno** è la direzione, il **valore assoluto** è la frazione di capitale impegnata, cioè la convinzione). Le operazioni si contano sul verso (`np.sign`), mai arrotondando: una posizione allo 0,4 è comunque un'operazione, e aumentarla a 0,8 non ne apre un'altra, restituisce `BacktestResult`. Il position shift di 1 barra è critico per evitare lookahead bias — non rimuoverlo mai. Fee e slippage simulati in basis point sul volume scambiato, tenuti separati nel riepilogo (`fees_paid` / `slippage_paid`); `slippage_bps` è 0 di default, quindi va scelto a mano. Con `flat_at_close` nessuna posizione sopravvive alla notte: la prima barra di ogni giornata parte piatta (la regola è ignorata sulle serie giornaliere, dove azzererebbe tutto). Al ribasso stop loss e take profit si scambiano di verso e una guardia ferma il conto a zero se una barra perde più dell'intero capitale (`wiped_out`). Il costo del prestito titoli **non** è modellato. L'annualizzazione (CAGR, volatilità, Sharpe, Sortino) usa `infer_periods_per_year()`, che deduce le barre per anno dal calendario: 252 sul giornaliero, `252 × barre al giorno` sull'intraday.
- **`portafoglio.py`** — il motore di portafoglio: prende N serie e N segnali, restituisce **una curva sola**. La regola dei pesi è la sostanza, non un dettaglio: la somma di quanto è impegnato non può superare il capitale, che è uno — altrimenti ogni mercato in più aggiungerebbe leva di nascosto. Due politiche esplicite (`QUOTA_FRA_SCELTI`, `QUOTA_FISSA`) e un ribilanciamento che è una scelta (`OGNI_BARRA`, `MAI`, o un calendario): fra due ribilanciamenti i pesi **derivano** col mercato, e ogni spostamento paga. Con un mercato solo il risultato è **identico** a `run_backtest`, e non per attenzione: la posizione la calcola la stessa `posizione_eseguita()`, il riepilogo la stessa `_build_summary()`, le operazioni lo stesso `_build_trades()`. Il metro di paragone non è più il comprare-e-tenere di un titolo ma il portafoglio noioso sugli stessi mercati (con N=1 coincidono). `trades.csv` guadagna la colonna `symbol` e si aggiunge `pesi.csv`: colonne e file nuovi, nessuna chiave rinominata.
- **`trasversali.py`** — le strategie che ordinano i mercati fra loro: `(dict[str, DataFrame], **parametri) -> DataFrame di segnali`. Il contratto delle 18 strategie a mercato singolo **non cambia**, così la rete sulle impronte continua a dire la verità. `forza_relativa` è la prima: compra i più forti del gruppo, con regola al ribasso esplicita (vende i più deboli) che tace quando i mercati in gara sono troppo pochi per non contraddirsi. `tests/test_trasversali.py` ripete su tutti i mercati insieme il troncamento e lo stravolgimento del futuro — una classifica è il posto più comodo dove nasconderlo.
- **`walkforward.py`** — finestre IS/OOS scorrevoli. Il segnale di ogni combinazione si calcola **una volta sull'intera serie** e poi si ritaglia sulla finestra: è il warm-up degli indicatori (senza, un indicatore più lungo della finestra resta piatto a zero) ed evita di ricalcolare lo stesso segnale per ogni finestra. A parità di punteggio vince sempre una combinazione che ha operato: quelle inerti hanno Sharpe 0 secco e batterebbero tutte quelle in perdita.
- **`reporting.py`** — trasforma `BacktestResult` in payload per la UI (card summary, dati grafico). Label italiane in `SUMMARY_LABELS`.
- **`errors.py`** — `FormValidationError` con tracking dei campi per evidenziazione UI.

### Interfacce

- **`web.py`** — app Flask. Routes principali: `/` (dashboard), `/backtests/new` (form), `/strategies` (strategy builder), `/history`, `/searches/*` (ricerca automatica), `/portfolios/*` (ricerca di portafoglio), `/api/*` (JSON per preview indicatori e stato form). Sempre usa `BacktestRequest.from_mapping(request.form)` per parsare i form.
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

Un portafoglio salva la stessa cartella (`portafoglio-SIMBOLI-TIMESTAMP/`) con in più `pesi.csv` — quanto capitale stava su ogni mercato barra per barra — e la colonna `symbol` in `trades.csv`. Le ricerche di portafoglio stanno in `reports/portfolio_searches/`, **non** insieme a quelle a mercato singolo: sono due risultati di forma diversa e mescolarli farebbe leggere l'uno con lo schema dell'altro.

I nomi delle colonne e le chiavi JSON dei file salvati sono un'interfaccia pubblica: non cambiarli senza migrare i report esistenti.

## Regole del progetto

### Sempre
- **Lingua italiana** — variabili, commenti, messaggi UI, errori: tutto in italiano.
- **Niente gergo nelle etichette** — l'app è per chi non conosce la finanza: `SUMMARY_LABELS`
  usa italiano corrente ("Il calo peggiore", non "Max drawdown") e il termine tecnico vive
  nella spiegazione a comparsa (`METRIC_TOOLTIPS`, formula "… In gergo: max drawdown."). Ogni
  metrica mostrata **deve** avere la sua spiegazione: c'è un test che lo verifica. Ogni report
  si apre con `build_plain_verdict()`, che dice in euro com'è andata e avvisa quando il
  risultato è troppo fragile per fidarsi.
- **Nessun lookahead bias** — il position shift in `backtest.py` (`.shift(1)`) non si tocca.
- **Il ribasso è sempre una scelta esplicita** — `consenti_short` di default è `False` ovunque: nessun percorso deve aprire posizioni al ribasso senza che l'utente l'abbia chiesto.
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
6. Accetta `consenti_short: bool = False` e scrivi la regola al ribasso **esplicita**: non usare l'opposto della condizione di uscita, che spesso è uno stop e non un segnale di inversione. Se una regola sensata non esiste, dichiara `supports_short=False`.

## Aggiungere una strategia trasversale

Una strategia trasversale guarda tutti i mercati insieme e decide su ciascuno confrontandolo con gli altri. Vive in `trasversali.py`, non in `strategies.py`.

1. Implementa la funzione con firma `(mercati: Mapping[str, pd.DataFrame], **params) -> pd.DataFrame` (una colonna per mercato, valori da -1 a +1).
2. Aggiungila a `FUNZIONI_TRASVERSALI` e crea il suo `SpecTrasversale` in `SPEC_TRASVERSALI`.
3. Lavora sulle barre comuni a tutti i mercati e lascia **vuoti** (NaN) i mercati su cui la storia non basta ancora: metterli a zero li farebbe entrare in classifica a metà gruppo invece di restarne fuori.
4. Ogni decisione deve usare solo dati fino a quella barra. Una classifica calcolata sull'intera serie è la forma più elegante di lookahead che si possa scrivere, e non fallisce: produce un risultato splendido e falso. `tests/test_trasversali.py` lo verifica su tutto il catalogo.
5. Se supporta il ribasso, aggiungi la sua griglia in `GRIGLIE_PORTAFOGLIO` e ricontrolla il budget: la ricerca si ferma se la griglia lo supera.
