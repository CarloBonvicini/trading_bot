"""Walk-forward validation.

Divide il periodo storico in finestre IS/OOS sovrapposte:
per ogni finestra in-sample ottimizza i parametri tramite sweep,
poi applica i parametri migliori alla finestra out-of-sample.
Concatena i risultati OOS per produrre la curva walk-forward.

**Warm-up degli indicatori.** Il segnale di ogni combinazione viene calcolato
una sola volta sull'intera serie e poi ritagliato sulla finestra: un indicatore
a 200 barre su una finestra da 125 partirebbe altrimenti "a freddo" e resterebbe
piatto a zero per tutta la finestra, facendo sembrare inattive un terzo delle
combinazioni della griglia. Non introduce lookahead — gli indicatori guardano
solo indietro — e come effetto collaterale evita di ricalcolare lo stesso
segnale una volta per finestra.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS, AUTOSETTING_GRIDS_BY_MODE
from trading_bot.backtest import SIZING_FULL, run_backtest
from trading_bot.strategies import STRATEGY_SPECS, build_strategy_signal, validate_strategy_parameters

TRADING_DAYS_PER_YEAR = 252

# Una combinazione che non apre nemmeno un'operazione ha rendimenti tutti nulli
# e quindi Sharpe esattamente 0: senza questa guardia batterebbe ogni strategia
# in perdita e verrebbe scelta proprio perché non fa niente.
MIN_TRADE_PER_SCELTA = 1


@dataclass
class WalkForwardWindow:
    window_index: int
    is_start: str          # data inizio IS (YYYY-MM-DD)
    is_end: str
    oos_start: str
    oos_end: str
    best_params: dict[str, int | float]
    is_sharpe: float
    oos_sharpe: float
    oos_return_pct: float
    oos_max_drawdown_pct: float
    oos_trades: int
    # Come e' andato il comprare-e-tenere nello stesso tratto: serve per dire
    # se la strategia ha battuto il mercato o se saliva e basta.
    oos_benchmark_return_pct: float = 0.0
    oos_benchmark_max_drawdown_pct: float = 0.0


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    oos_equity_curve: pd.DataFrame        # curva equity OOS concatenata
    wf_efficiency: float                  # OOS Sharpe medio / IS Sharpe medio
    avg_is_sharpe: float
    avg_oos_sharpe: float
    avg_oos_return_pct: float
    strategy_id: str
    optimize_by: str
    # In quanti tratti di collaudo ha fatto meglio del comprare-e-tenere: una
    # vittoria su un tratto solo e' un aneddoto, quattro su cinque un curriculum.
    finestre_vinte: int = 0


def run_walk_forward(
    data: pd.DataFrame,
    strategy_id: str,
    is_days: int = 252,
    oos_days: int = 63,
    optimize_by: str = "sharpe_ratio",
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    sizing_method: str = SIZING_FULL,
    sizing_param: float = 100.0,
    initial_capital: float = 10_000.0,
    scan_mode: str = "rapida",
    consenti_short: bool = False,
    flat_at_close: bool = False,
    on_combination: "Callable[[], None] | None" = None,
) -> WalkForwardResult:
    """Esegue la walk-forward validation su ``data`` per la strategia indicata.

    ``scan_mode`` seleziona la densità della griglia parametri (rapida → xl):
    profondità maggiori provano molte più combinazioni ma sono più lente.
    """
    spec = STRATEGY_SPECS.get(strategy_id)
    if spec is None:
        raise ValueError(f"Strategia non trovata: {strategy_id}")

    # La walk-forward richiede una griglia di parametri candidati. Non serve che
    # la strategia sia marcata ``supports_sweep`` (limite legato al form a due
    # box fast/slow): basta che esista una griglia autosetting, disponibile per
    # tutte le strategie. Così la validazione severa copre l'intero catalogo.
    param_grid = _build_param_grid(spec, scan_mode=scan_mode)
    if not param_grid:
        raise ValueError(
            f"Nessuna griglia di parametri disponibile per '{spec.label}': "
            "walk-forward non applicabile."
        )

    n = len(data)
    min_required = is_days + oos_days
    if n < min_required:
        raise ValueError(
            f"Dati insufficienti per walk-forward: servono almeno {min_required} barre, "
            f"disponibili {n}."
        )

    # Confini delle finestre: calcolati una volta sola, così il ciclo pesante
    # può girare per combinazione (segnale calcolato una volta) invece che per
    # finestra (segnale ricalcolato ogni volta).
    limiti = _window_bounds(n=n, is_days=is_days, oos_days=oos_days)
    if not limiti:
        raise ValueError("Nessuna finestra walk-forward completata — periodo troppo breve.")

    selezioni = [_SelezioneFinestra(param_grid[0]) for _ in limiti]

    for params in param_grid:
        try:
            # Warm-up: il segnale nasce sull'intera serie e viene poi ritagliato.
            signal_full = build_strategy_signal(
                strategy_id=strategy_id, data=data, parameters=params,
                consenti_short=consenti_short,
            )
        except Exception:
            # La combinazione è inutilizzabile: conta comunque come provata su
            # ogni finestra, altrimenti l'avanzamento mostrato non tornerebbe.
            if on_combination is not None:
                for _ in limiti:
                    on_combination()
            continue

        for selezione, (start_i, split_i, end_i) in zip(selezioni, limiti):
            is_data = data.iloc[start_i:split_i]
            try:
                result = run_backtest(
                    data=is_data,
                    signal=signal_full.iloc[start_i:split_i],
                    initial_capital=initial_capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    sl_pct=sl_pct,
                    tp_pct=tp_pct,
                    sizing_method=sizing_method,
                    sizing_param=sizing_param,
                    flat_at_close=flat_at_close,
                )
            except Exception:
                continue
            finally:
                if on_combination is not None:
                    on_combination()

            selezione.considera(
                params=params,
                summary=result.summary,
                optimize_by=optimize_by,
                oos_signal=signal_full.iloc[split_i:end_i],
            )

    windows: list[WalkForwardWindow] = []
    oos_curves: list[pd.DataFrame] = []

    for window_idx, (selezione, (start_i, split_i, end_i)) in enumerate(zip(selezioni, limiti)):
        is_data = data.iloc[start_i:split_i]
        oos_data = data.iloc[split_i:end_i]
        oos_signal = selezione.oos_signal
        if oos_signal is None:
            oos_signal = build_strategy_signal(
                strategy_id=strategy_id, data=data, parameters=selezione.params,
                consenti_short=consenti_short,
            ).iloc[split_i:end_i]

        oos_result = run_backtest(
            data=oos_data,
            signal=oos_signal,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            sizing_method=sizing_method,
            sizing_param=sizing_param,
            flat_at_close=flat_at_close,
        )

        oos_curves.append(oos_result.equity_curve)
        windows.append(
            WalkForwardWindow(
                window_index=window_idx + 1,
                is_start=_fmt_date(is_data.index[0]),
                is_end=_fmt_date(is_data.index[-1]),
                oos_start=_fmt_date(oos_data.index[0]),
                oos_end=_fmt_date(oos_data.index[-1]),
                best_params=selezione.params,
                is_sharpe=round(selezione.sharpe, 3),
                oos_sharpe=round(float(oos_result.summary.get("sharpe_ratio", 0.0)), 3),
                oos_return_pct=round(float(oos_result.summary.get("total_return_pct", 0.0)), 2),
                oos_benchmark_return_pct=round(
                    float(oos_result.summary.get("benchmark_return_pct", 0.0)), 2
                ),
                oos_benchmark_max_drawdown_pct=round(
                    float(oos_result.summary.get("benchmark_max_drawdown_pct", 0.0)), 2
                ),
                oos_max_drawdown_pct=round(float(oos_result.summary.get("max_drawdown_pct", 0.0)), 2),
                oos_trades=int(oos_result.summary.get("trade_count", 0)),
            )
        )

    # Concatena le equity curve OOS e ri-calcola la sequenza di equity continua
    oos_equity_curve = _stitch_oos_curves(oos_curves, initial_capital)

    avg_is = float(np.mean([w.is_sharpe for w in windows]))
    avg_oos = float(np.mean([w.oos_sharpe for w in windows]))
    wf_efficiency = (avg_oos / avg_is) if avg_is != 0 else 0.0
    avg_ret = float(np.mean([w.oos_return_pct for w in windows]))

    return WalkForwardResult(
        windows=windows,
        oos_equity_curve=oos_equity_curve,
        wf_efficiency=round(wf_efficiency, 3),
        avg_is_sharpe=round(avg_is, 3),
        avg_oos_sharpe=round(avg_oos, 3),
        avg_oos_return_pct=round(avg_ret, 2),
        strategy_id=strategy_id,
        optimize_by=optimize_by,
        finestre_vinte=sum(
            1 for w in windows if w.oos_return_pct > w.oos_benchmark_return_pct
        ),
    )


# ── Helpers interni ──────────────────────────────────────────────────────────

def _build_param_grid(spec, scan_mode: str = "rapida") -> list[dict[str, int | float]]:
    """Costruisce la griglia di parametri da testare per la strategia.

    Usa le griglie del modulo ``autosetting`` alla densità ``scan_mode``
    (rapida/media/lunga/xl), così walk-forward e autosetting condividono la
    fonte di verità sui parametri candidati. Filtra le combinazioni che violano
    i vincoli di validazione (es. fast < slow, exit < entry).
    """
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    grid = grids.get(spec.key)
    if not grid:
        return []

    param_names = list(grid.keys())
    param_values = [grid[name] for name in param_names]

    combos: list[dict[str, int | float]] = []
    for combo in itertools.product(*param_values):
        params = dict(zip(param_names, combo))
        try:
            validate_strategy_parameters(spec.key, params)
        except ValueError:
            continue
        combos.append(params)
    return combos


def _window_bounds(*, n: int, is_days: int, oos_days: int) -> list[tuple[int, int, int]]:
    """Confini ``(inizio IS, inizio OOS, fine OOS)`` di ogni finestra."""
    limiti: list[tuple[int, int, int]] = []
    start_i = 0
    while start_i + is_days + oos_days <= n:
        limiti.append((start_i, start_i + is_days, start_i + is_days + oos_days))
        start_i += oos_days  # avanza di un passo OOS (walk forward)
    return limiti


class _SelezioneFinestra:
    """Tiene la combinazione migliore per una singola finestra in-sample.

    Fra due combinazioni preferisce sempre quella che ha davvero operato: una
    che non apre nessuna operazione ha punteggio 0 secco e vincerebbe su ogni
    combinazione in perdita, facendo scegliere i parametri proprio perché
    inerti (vedi ``MIN_TRADE_PER_SCELTA``).
    """

    def __init__(self, params_default: dict[str, int | float]) -> None:
        self.params = params_default
        self.sharpe = 0.0
        self.oos_signal: pd.Series | None = None
        self._score = float("-inf")
        self._attiva = False

    def considera(
        self,
        *,
        params: dict[str, int | float],
        summary: dict,
        optimize_by: str,
        oos_signal: pd.Series,
    ) -> None:
        ascending = optimize_by == "max_drawdown_pct"  # drawdown: vogliamo il meno negativo
        raw = float(summary.get(optimize_by, 0.0))
        score = -raw if ascending else raw
        attiva = int(summary.get("trade_count", 0)) >= MIN_TRADE_PER_SCELTA

        if attiva and not self._attiva:
            migliore = True          # la prima combinazione che opera vince comunque
        elif attiva == self._attiva:
            migliore = score > self._score
        else:
            migliore = False         # inerte contro una che opera: mai

        if migliore:
            self.params = params
            self.sharpe = float(summary.get("sharpe_ratio", 0.0))
            self.oos_signal = oos_signal
            self._score = score
            self._attiva = attiva


def _stitch_oos_curves(curves: list[pd.DataFrame], initial_capital: float) -> pd.DataFrame:
    """Concatena le equity curve OOS riscalando ogni segmento in continuità."""
    if not curves:
        return pd.DataFrame()

    segments = []
    running_capital = initial_capital

    for curve in curves:
        if curve.empty:
            continue
        first_eq = float(curve["equity"].iloc[0])
        if first_eq <= 0:
            segments.append(curve)
            continue
        scale = running_capital / first_eq
        scaled = curve.copy()
        for col in ("equity", "gross_equity", "benchmark_equity"):
            if col in scaled.columns:
                scaled[col] = scaled[col] * scale
        running_capital = float(scaled["equity"].iloc[-1])
        segments.append(scaled)

    if not segments:
        return pd.DataFrame()

    combined = pd.concat(segments)
    combined["drawdown"] = combined["equity"] / combined["equity"].cummax() - 1
    return combined


def _fmt_date(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]
