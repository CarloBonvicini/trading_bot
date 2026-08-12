from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252

# Sopra questa media di barre al giorno la serie è considerata intraday.
_SOGLIA_INTRADAY = 1.5
# Sotto questo numero di barre non c'è abbastanza calendario per dedurre nulla.
_MIN_BARRE_INFERENZA = 10

# ── Metodi di position sizing ────────────────────────────────────────────────
SIZING_FULL = "full"        # 100% del capitale (default)
SIZING_FIXED = "fixed"      # Frazione fissa del capitale
SIZING_VOL_TARGET = "vol_target"  # Target di volatilità annualizzata

# Soglia sotto la quale due frazioni di posizione sono considerate uguali
# (evita di marcare microvariazioni di sizing come trade reali).
_POSITION_EQ_TOL = 1e-9

# Verso di un'operazione, come compare nella colonna "direction" di trades.csv.
DIREZIONE_LONG = "long"
DIREZIONE_SHORT = "short"


@dataclass
class BacktestResult:
    summary: dict[str, float | int | str]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame


def infer_periods_per_year(index: pd.Index) -> float:
    """Quante barre entrano in un anno di mercato, dedotte dal calendario.

    Serve ad annualizzare correttamente rendimento annuo, volatilità, Sharpe e
    Sortino: usare 252 su barre orarie gonfia i valori di circa 6-7 volte e su
    barre da un minuto di quasi 400.

    - Serie intraday (più barre nello stesso giorno): ``252 × barre al giorno``.
    - Serie giornaliere o più larghe: ``252 / giorni di borsa per barra``, così
      il caso giornaliero resta esattamente 252 (nessuna variazione sui report
      già salvati) e settimanale/mensile scendono a ~50 e ~12.
    """
    if not isinstance(index, pd.DatetimeIndex) or len(index) < _MIN_BARRE_INFERENZA:
        return float(TRADING_DAYS_PER_YEAR)

    giorni_distinti = index.normalize().nunique()
    if giorni_distinti <= 0:
        return float(TRADING_DAYS_PER_YEAR)

    barre_per_giorno = len(index) / giorni_distinti
    if barre_per_giorno >= _SOGLIA_INTRADAY:
        return float(TRADING_DAYS_PER_YEAR) * barre_per_giorno

    distanze = index.to_series().diff().dropna()
    distanze = distanze[distanze > pd.Timedelta(0)]
    if distanze.empty:
        return float(TRADING_DAYS_PER_YEAR)

    giorni_solari = float(distanze.median() / pd.Timedelta(days=1))
    # 5 giorni di borsa ogni 7 solari: una barra settimanale "vale" 5 giorni.
    giorni_borsa_per_barra = max(1, round(giorni_solari * 5.0 / 7.0))
    return float(TRADING_DAYS_PER_YEAR) / giorni_borsa_per_barra


def serie_intraday(index: pd.Index) -> bool:
    """Vero se nello stesso giorno ci sono più barre (5m, 1h...).

    Serve a non applicare regole intraday a una serie giornaliera, dove ogni
    barra è già l'ultima della sua giornata.
    """
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
        return False
    giorni = index.normalize().nunique()
    if giorni <= 0:
        return False
    return (len(index) / giorni) >= _SOGLIA_INTRADAY


def _prima_barra_del_giorno(index: pd.DatetimeIndex) -> np.ndarray:
    """Maschera True sulla prima barra di ogni giornata di contrattazione."""
    giorni = index.normalize().to_numpy()
    prima = np.empty(len(giorni), dtype=bool)
    prima[0] = True
    prima[1:] = giorni[1:] != giorni[:-1]
    return prima


def apply_sl_tp(
    data: pd.DataFrame,
    position: pd.Series,
    sl_pct: float | None,
    tp_pct: float | None,
) -> tuple[pd.Series, pd.Series]:
    """Applica stop loss e take profit alla serie di posizione già shiftata.

    Restituisce ``(posizione modificata, maschera_uscite_sl_tp)`` dove la
    maschera è True nelle barre in cui è scattato lo SL o il TP.

    Convenzione: la ``position`` in ingresso è già stata shiftata di una barra
    in ``run_backtest``, quindi ``position[i] != 0`` significa che siamo entrati
    al close della barra ``i-1`` (l'entry price è ``close[i-1]``). Nella stessa
    barra ``i`` si controlla se il prezzo ha toccato una delle due soglie.

    Le soglie sono speculari a seconda del verso: al rialzo si perde quando il
    prezzo scende (``low``) e si guadagna quando sale (``high``), al ribasso
    esattamente il contrario.

    Quando entrambi SL e TP sono colpiti nella stessa candela non possiamo
    sapere quale è scattato per primo: in questo caso assumiamo
    conservativamente che sia stato lo SL (worst case per il trader).
    """
    if sl_pct is None and tp_pct is None:
        return position, pd.Series(False, index=position.index)

    close = data["close"].to_numpy(dtype=float)
    high = data["high"].to_numpy(dtype=float) if "high" in data.columns else close
    low = data["low"].to_numpy(dtype=float) if "low" in data.columns else close

    pos = position.to_numpy(dtype=float).copy()
    sl_tp_exit = np.zeros(len(pos), dtype=bool)
    n = len(pos)
    entry_price = 0.0
    verso = 0.0  # +1 al rialzo, -1 al ribasso, 0 fuori mercato

    for i in range(n):
        verso_barra = math.copysign(1.0, pos[i]) if pos[i] != 0 else 0.0

        # Fuori mercato, oppure ribaltamento da long a short (o viceversa):
        # in entrambi i casi qui comincia una posizione nuova.
        if verso_barra != 0.0 and verso_barra != verso:
            # Nuova entry: prezzo entrata = close della barra precedente
            # (coerente con lo shift di 1 applicato in run_backtest).
            entry_price = close[i - 1] if i > 0 else close[i]
            verso = verso_barra
            # Controllo SL/TP anche nello stesso bar di entry: il low/high
            # corrente potrebbe già aver toccato la soglia.
            if _check_sl_tp_hit(
                entry_price=entry_price, low=low[i], high=high[i],
                sl_pct=sl_pct, tp_pct=tp_pct, verso=verso,
            ):
                pos[i] = 0.0
                sl_tp_exit[i] = True
                verso = 0.0
                entry_price = 0.0
        elif verso != 0.0:
            if verso_barra == 0.0:
                verso = 0.0
                entry_price = 0.0
            elif _check_sl_tp_hit(
                entry_price=entry_price, low=low[i], high=high[i],
                sl_pct=sl_pct, tp_pct=tp_pct, verso=verso,
            ):
                pos[i] = 0.0
                sl_tp_exit[i] = True
                verso = 0.0
                entry_price = 0.0

    return pd.Series(pos, index=position.index, name=position.name), pd.Series(
        sl_tp_exit, index=position.index
    )


def _check_sl_tp_hit(
    *,
    entry_price: float,
    low: float,
    high: float,
    sl_pct: float | None,
    tp_pct: float | None,
    verso: float = 1.0,
) -> bool:
    """True se nel bar corrente è stato colpito SL o TP.

    ``verso`` vale +1 per una posizione al rialzo e -1 per una al ribasso: chi
    è short perde quando il prezzo sale, quindi le due soglie si scambiano.
    """
    if verso >= 0:
        if sl_pct is not None and low <= entry_price * (1.0 - sl_pct / 100.0):
            return True
        if tp_pct is not None and high >= entry_price * (1.0 + tp_pct / 100.0):
            return True
        return False

    if sl_pct is not None and high >= entry_price * (1.0 + sl_pct / 100.0):
        return True
    if tp_pct is not None and low <= entry_price * (1.0 - tp_pct / 100.0):
        return True
    return False


def compute_position_size(
    data: pd.DataFrame,
    position: pd.Series,
    method: str = SIZING_FULL,
    param: float = 1.0,
    periods_per_year: float | None = None,
) -> pd.Series:
    """Calcola la dimensione della posizione in base al metodo di sizing scelto.

    - ``full``:       100% del capitale quando in posizione (default).
    - ``fixed``:      ``param``% del capitale (es. param=50 → 50%).
    - ``vol_target``: dimensione inversamente proporzionale alla volatilità
                      realizzata (20 barre), calibrata per targetare ``param``%
                      di volatilità annualizzata. Massimo 2× l'investimento.
    """
    if method == SIZING_FIXED:
        frac = max(0.0, min(1.0, param / 100.0))
        return position * frac

    if method == SIZING_VOL_TARGET:
        if param <= 0:
            return position  # protezione: target nullo → ignora
        target = param / 100.0
        barre_anno = periods_per_year or infer_periods_per_year(data.index)
        returns = data["close"].pct_change()
        realized_vol = returns.rolling(20, min_periods=5).std() * math.sqrt(barre_anno)
        realized_vol = realized_vol.replace(0.0, np.nan).ffill().bfill().fillna(target)
        size = (target / realized_vol).clip(upper=2.0)
        return position * size

    # SIZING_FULL (default)
    return position


def run_backtest(
    data: pd.DataFrame,
    signal: pd.Series,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    sizing_method: str = SIZING_FULL,
    sizing_param: float = 100.0,
    flat_at_close: bool = False,
) -> BacktestResult:
    if "close" not in data.columns:
        raise ValueError("The input data must contain a 'close' column.")
    if initial_capital <= 0:
        raise ValueError("Initial capital must be positive.")
    if fee_bps < 0:
        raise ValueError("fee_bps cannot be negative.")
    if slippage_bps < 0:
        raise ValueError("slippage_bps cannot be negative.")

    # Barre per anno dedotte dal calendario: su intraday 252 sarebbe sbagliato.
    periods_per_year = infer_periods_per_year(data.index)

    close = data["close"].astype(float)
    # Da -1 (tutto al ribasso) a +1 (tutto al rialzo). Un segnale negativo su un
    # motore solo long veniva azzerato qui in silenzio.
    position = signal.reindex(data.index).fillna(0.0).clip(lower=-1.0, upper=1.0)
    # Shift di 1 barra: il segnale generato dalla barra t è eseguibile dalla t+1.
    # Questo è il presidio chiave contro il lookahead bias — non rimuovere.
    executed_position = position.shift(1).fillna(0.0)

    # Stop loss / take profit (path-dependent, applicato dopo lo shift).
    # IMPORTANT: SL/TP lavora sulla posizione a verso pieno (-1/0/+1) PRIMA del
    # sizing, così possiamo distinguere chiaramente trade reali da variazioni
    # di sizing (vol_target ecc.) ai fini del tracking trade.
    # Niente posizioni tenute da un giorno all'altro: la prima barra di ogni
    # giornata parte piatta, cioè si è chiuso tutto alla chiusura precedente.
    # Su una serie giornaliera la regola non ha senso (ogni barra è già l'ultima
    # della sua giornata) e viene ignorata invece di azzerare ogni posizione.
    eod_mask = pd.Series(False, index=data.index)
    if flat_at_close and serie_intraday(data.index):
        prima_del_giorno = pd.Series(_prima_barra_del_giorno(data.index), index=data.index)
        eod_mask = prima_del_giorno & (executed_position != 0.0)
        executed_position = executed_position.where(~prima_del_giorno, 0.0)

    executed_position, sl_tp_mask = apply_sl_tp(data, executed_position, sl_pct, tp_pct)

    daily_returns = close.pct_change().fillna(0.0)

    def _conti(posizione_intera: pd.Series) -> dict[str, pd.Series]:
        """Dalla posizione a verso pieno a rendimenti, costi ed equity."""
        dimensionata = compute_position_size(
            data, posizione_intera, sizing_method, sizing_param,
            periods_per_year=periods_per_year,
        )
        variazione = dimensionata.diff().abs().fillna(dimensionata.abs())
        commissioni = variazione * (fee_bps / 10_000.0)
        # Slippage: la differenza fra il prezzo che vedi e quello che ottieni
        # davvero (spread e impatto dell'ordine). Come le commissioni si paga
        # sul volume scambiato, ma è una voce diversa e va tenuta distinta:
        # sulle commissioni si può trattare, sullo slippage no.
        slippage = variazione * (slippage_bps / 10_000.0)
        costo = commissioni + slippage
        lordo = dimensionata * daily_returns
        netto = lordo - costo
        return {
            "posizione": dimensionata,
            "costo": costo,
            "commissioni": commissioni,
            "slippage": slippage,
            "lordo": lordo,
            "netto": netto,
            "equity": initial_capital * (1 + netto).cumprod(),
        }

    conti = _conti(executed_position)

    # Rovina: al ribasso la perdita non ha un tetto. Se in una barra il
    # rendimento scende sotto il -100% il capitale sarebbe negativo, e da lì in
    # poi ogni metrica (drawdown, Sharpe, grafico) sarebbe priva di senso.
    # Chiudiamo tutto da quella barra e teniamo il conto a zero.
    barra_rovina = _prima_barra_di_rovina(conti["netto"])
    if barra_rovina is not None:
        executed_position = executed_position.copy()
        executed_position.iloc[barra_rovina + 1:] = 0.0
        sl_tp_mask = sl_tp_mask.copy()
        sl_tp_mask.iloc[barra_rovina + 1:] = False
        eod_mask = eod_mask.copy()
        eod_mask.iloc[barra_rovina + 1:] = False
        conti = _conti(executed_position)

    binary_position = executed_position
    executed_position = conti["posizione"]
    transaction_cost = conti["costo"]
    fee_cost = conti["commissioni"]
    slippage_cost = conti["slippage"]
    gross_strategy_return = conti["lordo"]
    strategy_returns = conti["netto"]
    equity = conti["equity"]

    benchmark_equity = initial_capital * (1 + daily_returns).cumprod()
    gross_equity = initial_capital * (1 + gross_strategy_return).cumprod()
    if barra_rovina is not None:
        equity.iloc[barra_rovina:] = 0.0
        gross_equity.iloc[barra_rovina:] = 0.0

    equity_before = equity.shift(1).fillna(initial_capital)
    transaction_cost_amount = equity_before * transaction_cost
    fee_cost_amount = equity_before * fee_cost
    slippage_cost_amount = equity_before * slippage_cost
    drawdown = equity / equity.cummax() - 1

    market_columns = {
        column: data[column].astype(float)
        for column in ("open", "high", "low", "close", "volume")
        if column in data.columns
    }
    if "close" not in market_columns:
        market_columns["close"] = close

    equity_curve = pd.DataFrame(
        {
            **market_columns,
            "signal": position,
            "position": executed_position,
            "binary_position": binary_position,
            "sl_tp_exit": sl_tp_mask.astype(int),
            "end_of_day_exit": eod_mask.astype(int),
            "market_return": daily_returns,
            "gross_strategy_return": gross_strategy_return,
            "strategy_return": strategy_returns,
            # transaction_cost_* e' il costo totale (commissioni + slippage):
            # coincide con i report vecchi, dove lo slippage non esisteva.
            "transaction_cost_rate": transaction_cost,
            "transaction_cost_amount": transaction_cost_amount,
            "fee_cost_amount": fee_cost_amount,
            "slippage_cost_amount": slippage_cost_amount,
            "equity": equity,
            "gross_equity": gross_equity,
            "benchmark_equity": benchmark_equity,
            "drawdown": drawdown,
        }
    )

    # Trade tracking basato sulla posizione binaria (0/1): le variazioni di
    # sizing intra-trade non vengono contate come ingressi/uscite separati.
    trades = _build_trades(
        close=close, binary_position=binary_position, sl_tp_mask=sl_tp_mask, eod_mask=eod_mask,
    )
    summary = _build_summary(
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=initial_capital,
        periods_per_year=periods_per_year,
        barra_rovina=barra_rovina,
    )
    return BacktestResult(summary=summary, equity_curve=equity_curve, trades=trades)


def _prima_barra_di_rovina(strategy_returns: pd.Series) -> int | None:
    """Indice della prima barra che azzera (o supera) l'intero capitale.

    Serve solo con posizioni al ribasso o a leva: al rialzo senza leva il
    rendimento di una barra non può scendere sotto il -100%.
    """
    rovina = strategy_returns <= -1.0
    if not bool(rovina.any()):
        return None
    return int(np.argmax(rovina.to_numpy()))


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
    periods_per_year: float = float(TRADING_DAYS_PER_YEAR),
    barra_rovina: int | None = None,
) -> dict[str, float | int | str]:
    strategy_returns = equity_curve["strategy_return"]
    final_equity = float(equity_curve["equity"].iloc[-1])
    gross_final_equity = float(equity_curve["gross_equity"].iloc[-1])
    benchmark_final_equity = float(equity_curve["benchmark_equity"].iloc[-1])
    total_costs_paid = float(equity_curve["transaction_cost_amount"].sum())
    total_fees_paid = float(
        equity_curve["fee_cost_amount"].sum()
        if "fee_cost_amount" in equity_curve.columns
        else total_costs_paid
    )
    total_slippage_paid = float(
        equity_curve["slippage_cost_amount"].sum()
        if "slippage_cost_amount" in equity_curve.columns
        else 0.0
    )
    total_return = (final_equity / initial_capital) - 1
    benchmark_return = (benchmark_final_equity / initial_capital) - 1
    periods = len(equity_curve)
    years = periods / periods_per_year if periods and periods_per_year > 0 else 0.0

    # CAGR: rendimento annualizzato composto. Se la serie è più corta di un
    # anno restituiamo il rendimento totale per evitare amplificazioni assurde.
    if years >= 1.0 and initial_capital > 0:
        annual_return = (final_equity / initial_capital) ** (1 / years) - 1
    else:
        annual_return = total_return

    annual_volatility = strategy_returns.std(ddof=0) * math.sqrt(periods_per_year)
    sharpe_ratio = _compute_sharpe(strategy_returns, periods_per_year)
    sortino_ratio = _compute_sortino(strategy_returns, periods_per_year)
    calmar_ratio = _compute_calmar(annual_return=annual_return, drawdown=equity_curve["drawdown"])

    # Statistiche trade (richiedono pnl_pct numerico sui trade chiusi)
    trade_stats = _compute_trade_stats(trades)

    return {
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "gross_final_equity": round(gross_final_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "benchmark_final_equity": round(benchmark_final_equity, 2),
        "excess_return_pct": round((total_return - benchmark_return) * 100, 2),
        "fees_paid": round(total_fees_paid, 2),
        "fees_paid_pct_initial_capital": round((total_fees_paid / initial_capital) * 100, 2),
        "slippage_paid": round(total_slippage_paid, 2),
        "trading_costs_paid": round(total_costs_paid, 2),
        "fee_drag_equity": round(gross_final_equity - final_equity, 2),
        "annual_return_pct": round(annual_return * 100, 2),
        "annual_volatility_pct": round(annual_volatility * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 3),
        "sortino_ratio": round(float(sortino_ratio), 3),
        "calmar_ratio": round(float(calmar_ratio), 3),
        "max_drawdown_pct": round(float(equity_curve["drawdown"].min()) * 100, 2),
        "trade_count": int(trade_stats["trade_count"]),
        "win_rate_pct": trade_stats["win_rate_pct"],
        "profit_factor": trade_stats["profit_factor"],
        "avg_win_pct": trade_stats["avg_win_pct"],
        "avg_loss_pct": trade_stats["avg_loss_pct"],
        "expectancy_pct": trade_stats["expectancy_pct"],
        "sl_tp_exit_count": int(equity_curve["sl_tp_exit"].sum()) if "sl_tp_exit" in equity_curve.columns else 0,
        "end_of_day_exit_count": (
            int(equity_curve["end_of_day_exit"].sum())
            if "end_of_day_exit" in equity_curve.columns
            else 0
        ),
        # Valore assoluto: senza, una strategia sempre a mercato che alterna
        # rialzo e ribasso risulterebbe ferma (i due versi si annullano).
        "exposure_pct": round(float(equity_curve["position"].abs().mean()) * 100, 2),
        "long_exposure_pct": round(float(equity_curve["position"].clip(lower=0).mean()) * 100, 2),
        "short_exposure_pct": round(float(equity_curve["position"].clip(upper=0).abs().mean()) * 100, 2),
        "short_trade_count": int(trade_stats["short_trade_count"]),
        # Capitale azzerato: possibile solo con posizioni al ribasso o a leva.
        "wiped_out": barra_rovina is not None,
        "wiped_out_date": (
            _format_trade_timestamp(equity_curve.index[barra_rovina])
            if barra_rovina is not None
            else ""
        ),
        "benchmark_return_pct": round(benchmark_return * 100, 2),
    }


def _compute_sharpe(
    returns: pd.Series, periods_per_year: float = float(TRADING_DAYS_PER_YEAR)
) -> float:
    """Sharpe ratio annualizzato con risk-free rate = 0.

    Convenzione: ``std(ddof=0)`` (deviazione di popolazione) per coerenza con
    annual_volatility_pct. Differenza vs ddof=1 trascurabile su N>30.
    """
    if returns.empty:
        return 0.0
    std = returns.std(ddof=0)
    if std <= 0:
        return 0.0
    return float(returns.mean() / std * math.sqrt(periods_per_year))


def _compute_sortino(
    returns: pd.Series, periods_per_year: float = float(TRADING_DAYS_PER_YEAR)
) -> float:
    """Sortino ratio: come Sharpe ma usa solo la volatilità dei rendimenti negativi.

    Premia le strategie che hanno bassa volatilità al ribasso anche se la
    volatilità totale è alta (es. forti rialzi seguiti da fasi piatte).
    """
    if returns.empty:
        return 0.0
    downside = returns[returns < 0]
    if downside.empty:
        # Nessun giorno negativo: ritorno infinito → cap a 999 per leggibilità.
        return 999.0 if returns.mean() > 0 else 0.0
    downside_std = downside.std(ddof=0)
    if downside_std <= 0:
        return 0.0
    return float(returns.mean() / downside_std * math.sqrt(periods_per_year))


def _compute_calmar(*, annual_return: float, drawdown: pd.Series) -> float:
    """Calmar ratio: CAGR / |max drawdown|.

    Indica quante volte il rendimento annuo copre il peggior calo storico.
    """
    if drawdown.empty:
        return 0.0
    max_dd = float(drawdown.min())  # è negativo (es. -0.25)
    if max_dd >= 0:
        return 999.0 if annual_return > 0 else 0.0
    return float(annual_return / abs(max_dd))


def _compute_trade_stats(trades: pd.DataFrame) -> dict[str, float | int | None]:
    """Statistiche aggregate sui trade.

    Convenzione: ``trade_count`` è il numero totale di operazioni aperte
    (incluse quelle ancora in corso a fine serie). Le statistiche di
    profittabilità (win rate, profit factor, expectancy) sono invece calcolate
    solo sui trade chiusi, perché per quelli aperti il PnL non è ancora
    definito.
    """
    if trades.empty:
        return {
            "trade_count": 0,
            "short_trade_count": 0,
            "win_rate_pct": None,
            "profit_factor": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "expectancy_pct": None,
        }

    total_count = int(len(trades))
    short_count = (
        int((trades["direction"] == DIREZIONE_SHORT).sum())
        if "direction" in trades.columns
        else 0
    )
    pnl_series = (
        pd.to_numeric(trades["pnl_pct"], errors="coerce").dropna()
        if "pnl_pct" in trades.columns
        else pd.Series(dtype=float)
    )

    if pnl_series.empty:
        return {
            "trade_count": total_count,
            "short_trade_count": short_count,
            "win_rate_pct": None,
            "profit_factor": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "expectancy_pct": None,
        }

    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series < 0]
    win_count = int(len(wins))
    loss_count = int(len(losses))
    closed = int(len(pnl_series))

    win_rate = round(win_count / closed * 100, 2) if closed else None
    avg_win = round(float(wins.mean()), 2) if win_count else None
    avg_loss = round(float(losses.mean()), 2) if loss_count else None

    # Profit factor: somma vincite / |somma perdite|. Cappato a 999 se non
    # ci sono perdite ma ci sono vincite. None se non c'è nulla da calcolare.
    sum_wins = float(wins.sum()) if win_count else 0.0
    sum_losses = abs(float(losses.sum())) if loss_count else 0.0
    if win_count == 0 and loss_count == 0:
        profit_factor = None
    elif sum_losses <= 0:
        profit_factor = 999.0 if sum_wins > 0 else None
    else:
        profit_factor = round(sum_wins / sum_losses, 3)

    # Expectancy: PnL medio per trade chiuso in punti percentuali.
    expectancy = round(float(pnl_series.mean()), 2)

    return {
        "trade_count": total_count,
        "short_trade_count": short_count,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "expectancy_pct": expectancy,
    }


def _build_trades(
    close: pd.Series,
    binary_position: pd.Series,
    sl_tp_mask: pd.Series | None = None,
    eod_mask: pd.Series | None = None,
) -> pd.DataFrame:
    """Estrae la lista trade dalla posizione a verso pieno (-1 / 0 / +1).

    Lavoriamo sulla posizione prima del sizing, così le variazioni di frazione
    introdotte da ``vol_target`` non generano trade fittizi. Un trade dura da
    quando la posizione diventa diversa da zero a quando torna a zero **o
    cambia verso**: un ribaltamento diretto da rialzo a ribasso chiude il primo
    trade e ne apre subito un altro nella stessa barra.

    Il P&L segue il verso: al rialzo si guadagna se il prezzo sale, al ribasso
    se scende.
    """
    verso = binary_position.fillna(0.0).round().clip(lower=-1, upper=1)
    versi = verso.to_numpy(dtype=float)
    prezzi = close.to_numpy(dtype=float)
    indice = verso.index

    sl_tp_set: set = set()
    if sl_tp_mask is not None:
        sl_tp_set = set(sl_tp_mask[sl_tp_mask].index)
    eod_set: set = set()
    if eod_mask is not None:
        eod_set = set(eod_mask[eod_mask].index)

    trades: list[dict[str, object]] = []
    verso_aperto = 0.0
    barra_entrata: int | None = None

    def _chiudi(barra_uscita: int | None) -> None:
        entry_date = indice[barra_entrata]
        entry_price = float(prezzi[barra_entrata])
        chiuso = barra_uscita is not None
        exit_date = indice[barra_uscita] if chiuso else None
        exit_price = float(prezzi[barra_uscita]) if chiuso else None
        pnl_pct = (
            verso_aperto * ((exit_price / entry_price) - 1) * 100 if chiuso else None
        )
        trades.append(
            {
                "entry_date": _format_trade_timestamp(entry_date),
                "entry_price": round(entry_price, 4),
                "exit_date": _format_trade_timestamp(exit_date) if chiuso else "",
                "exit_price": round(exit_price, 4) if chiuso else "",
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else "",
                "holding_days": int((exit_date - entry_date).days) if chiuso else "",
                "exit_reason": _motivo_uscita(exit_date, sl_tp_set, eod_set) if chiuso else "",
                "direction": DIREZIONE_LONG if verso_aperto > 0 else DIREZIONE_SHORT,
            }
        )

    for i in range(len(versi)):
        corrente = versi[i]
        if verso_aperto != 0.0 and corrente != verso_aperto:
            _chiudi(i)
            verso_aperto = 0.0
            barra_entrata = None
        if corrente != 0.0 and verso_aperto == 0.0:
            verso_aperto = corrente
            barra_entrata = i

    if verso_aperto != 0.0:
        _chiudi(None)  # trade ancora aperto a fine serie

    return pd.DataFrame(trades)


def _motivo_uscita(exit_date, sl_tp_set: set, eod_set: set) -> str:
    """Perché l'operazione si è chiusa: soglia, fine giornata o segnale."""
    if exit_date in sl_tp_set:
        return "sl_tp"
    if exit_date in eod_set:
        return "fine_giornata"
    return "segnale"


def _format_trade_timestamp(timestamp: pd.Timestamp) -> str:
    if timestamp.hour == 0 and timestamp.minute == 0 and timestamp.second == 0:
        return timestamp.strftime("%Y-%m-%d")
    return timestamp.strftime("%Y-%m-%d %H:%M")
