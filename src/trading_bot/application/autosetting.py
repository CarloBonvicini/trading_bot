from __future__ import annotations

import itertools
import math

import pandas as pd

from trading_bot.backtest import run_backtest
from trading_bot.strategies import STRATEGY_SPECS, build_strategy_signal, validate_strategy_parameters

TRAIN_RATIO = 0.70
OVERFIT_SOGLIA = 0.40      # calo Sharpe OOS > 40% rispetto IS → warning
PESO_PROPRIO = 0.60        # peso Sharpe della combinazione stessa nel robustness score
PESO_VICINI = 0.40         # peso media Sharpe dei vicini immediati nella griglia

def _dense(values: list, factor: int) -> list:
    """Densifica una lista inserendo valori intermedi equidistanti.
    factor=1 → nessuna modifica; factor=2 → 1 punto intermedio per gap;
    factor=4 → 3 punti intermedi per gap."""
    if factor <= 1 or len(values) < 2:
        return list(values)
    is_float = any(isinstance(v, float) for v in values)
    result = []
    for i in range(len(values) - 1):
        a, b = values[i], values[i + 1]
        result.append(a)
        for j in range(1, factor):
            interp = a + (b - a) * j / factor
            result.append(round(interp, 2) if is_float else int(round(interp)))
    result.append(values[-1])
    seen: set = set()
    return [v for v in result if not (v in seen or seen.add(v))]  # type: ignore[func-returns-value]


AUTOSETTING_GRIDS: dict[str, dict[str, list]] = {
    "sma_cross": {
        "fast": list(range(5, 55, 5)),     # [5, 10, ..., 50]
        "slow": list(range(20, 220, 20)),  # [20, 40, ..., 200]
    },
    "ema_cross": {
        "fast": list(range(5, 55, 5)),
        "slow": list(range(20, 220, 20)),
    },
    "rsi_mean_reversion": {
        "period": list(range(7, 22, 2)),           # [7, 9, ..., 21]
        "lower": [25.0, 30.0, 35.0, 40.0],
        "upper": [55.0, 60.0, 65.0, 70.0],
    },
    "macd_trend": {
        "fast": [8, 12, 16],
        "slow": [21, 26, 34],
        "signal": [7, 9, 12],
    },
    "bollinger_reversion": {
        "period": [10, 15, 20, 25, 30],
        "std_dev": [1.5, 2.0, 2.5, 3.0],
    },
    "stochastic_reversion": {
        "k_period": [9, 14, 21],
        "d_period": [3],
        "smooth": [3],
        "lower": [15.0, 20.0, 25.0],
        "upper": [75.0, 80.0, 85.0],
    },
    "cci_reversion": {
        "period": [14, 20, 28],
        "lower": [-150.0, -100.0, -80.0],
        "upper": [80.0, 100.0, 150.0],
    },
    "williams_r_reversion": {
        "period": [10, 14, 21],
        "lower": [-85.0, -80.0, -75.0],
        "upper": [-25.0, -20.0, -15.0],
    },
    "adx_trend": {
        "period": [10, 14, 21],
        "threshold": [20.0, 25.0, 30.0, 35.0],
    },
    "obv_trend": {
        "fast": [5, 10, 15, 20],
        "slow": [20, 30, 40, 50],
    },
    "donchian_breakout": {
        "entry_period": [10, 20, 40, 60],
        "exit_period": [5, 10, 20],
    },
    "roc_momentum": {
        "period": [5, 10, 15, 20, 30],
        "threshold": [2.0, 5.0, 8.0, 12.0, 18.0],
    },
    "keltner_reversion": {
        "period": [10, 15, 20, 25, 30],
        "multiplier": [1.5, 2.0, 2.5, 3.0],
    },
    "mfi_reversion": {
        "period": [10, 14, 20, 28],
        "lower": [15.0, 20.0, 25.0, 30.0],
        "upper": [70.0, 75.0, 80.0, 85.0],
    },
    "parabolic_sar": {
        "step": [0.01, 0.02, 0.03, 0.05],
        "max_step": [0.10, 0.20, 0.30],
    },
    "kama_trend": {
        "periodo": [5, 10, 15, 20, 30],
        "veloce": [2, 3, 5],
        "lenta": [20, 30, 40],
        # 0 = dentro con tutto, 1 = importo proporzionale alla convinzione.
        "dosa": [0, 1],
    },
    "ritorno_media_stimato": {
        "finestra": [10, 20, 30],
        "finestra_stima": [40, 60, 90],
        "mezza_vita_massima": [5, 10, 20],
        "soglia": [1.5, 2.0, 2.5],
    },
    "fisher_reversion": {
        "periodo": [5, 9, 14, 20, 30],
        "soglia": [1.0, 1.5, 2.0, 2.5],
    },
}

AUTOSETTING_GRIDS_BY_MODE: dict[str, dict[str, dict[str, list]]] = {
    "rapida": AUTOSETTING_GRIDS,
    "media": {
        sid: {param: _dense(vals, 2) for param, vals in grid.items()}
        for sid, grid in AUTOSETTING_GRIDS.items()
    },
    "lunga": {
        sid: {param: _dense(vals, 4) for param, vals in grid.items()}
        for sid, grid in AUTOSETTING_GRIDS.items()
    },
    "xl": {
        sid: {param: _dense(vals, 8) for param, vals in grid.items()}
        for sid, grid in AUTOSETTING_GRIDS.items()
    },
}


def run_autosetting(
    strategy_id: str,
    data: pd.DataFrame,
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    scan_mode: str = "rapida",
) -> dict[str, object]:
    """Cerca la combinazione di parametri più robusta sul training set (70%)
    e la valida sull'out-of-sample (30%) per verificare l'assenza di overfitting.

    scan_mode: "rapida" (griglia base), "media" (2× più densa), "lunga" (4× più densa).

    Returns:
        dict con best_params, sharpe_in_sample, sharpe_out_of_sample,
        robustness_score, combinations_tested, overfitting_warning.
    """
    grids = AUTOSETTING_GRIDS_BY_MODE.get(scan_mode, AUTOSETTING_GRIDS)
    if strategy_id not in grids:
        raise ValueError(f"Autosetting non disponibile per la strategia '{strategy_id}'.")

    grid = grids[strategy_id]
    param_names = list(grid.keys())
    param_values = [grid[name] for name in param_names]

    split_index = int(len(data) * TRAIN_RATIO)
    if split_index < 30:
        raise ValueError(
            "Dati insufficienti per l'Autosetting: servono almeno 43 barre totali."
        )
    if len(data) - split_index < 10:
        raise ValueError(
            "Il set di test è troppo corto: aggiungi più dati storici."
        )

    train_data = data.iloc[:split_index]
    test_data = data.iloc[split_index:]

    # --- Grid search: raccoglie Sharpe e rendimento per ogni combinazione valida ---
    # Qui l'enumerazione totale resta, e non per dimenticanza: il risultato di
    # questa funzione È la mappa completa (`all_scores` alimenta la heatmap e il
    # punteggio di robustezza confronta ogni combinazione coi suoi vicini). Una
    # ricerca a budget restituirebbe una mappa con dei buchi, cioè un'altra
    # cosa. Se un giorno la griglia diventasse troppo grande per essere
    # disegnata, il problema da risolvere sarebbe il disegno, non la ricerca.
    # scores_map: tuple di valori parametro → sharpe
    scores_map: dict[tuple, float] = {}
    return_map: dict[tuple, float] = {}
    combinations_invalid = 0

    for combo in itertools.product(*param_values):
        params: dict[str, int | float] = dict(zip(param_names, combo))

        try:
            validate_strategy_parameters(strategy_id, params)
        except ValueError:
            combinations_invalid += 1
            continue

        try:
            signal = build_strategy_signal(
                strategy_id=strategy_id,
                data=train_data,
                parameters=params,
            )
            result = run_backtest(
                data=train_data,
                signal=signal,
                initial_capital=initial_capital,
                fee_bps=fee_bps,
            )
        except Exception:
            combinations_invalid += 1
            continue

        sharpe = float(result.summary.get("sharpe_ratio", 0.0))
        scores_map[combo] = sharpe
        return_map[combo] = float(result.summary.get("total_return_pct", 0.0))

    # Indice posizione in griglia per calcolo vicini
    grid_index: dict[str, dict[object, int]] = {
        name: {val: idx for idx, val in enumerate(values)}
        for name, values in zip(param_names, param_values)
    }

    if not scores_map:
        raise ValueError(
            "Nessuna combinazione valida trovata. "
            "Prova con più dati storici o cambia strategia."
        )

    # --- Robustness score: per ogni combinazione, media con i vicini ---
    # I vicini sono le combinazioni che differiscono di ±1 passo in una sola dimensione.
    best_params: dict[str, int | float] = {}
    best_robustness = float("-inf")
    best_own_sharpe = float("-inf")
    best_own_return = 0.0
    all_robustness: dict[tuple, float] = {}

    for combo, own_sharpe in scores_map.items():
        neighbor_sharpes: list[float] = []

        for dim_idx, name in enumerate(param_names):
            current_pos = grid_index[name].get(combo[dim_idx], -1)
            dim_values = param_values[dim_idx]

            for delta in (-1, 1):
                neighbor_pos = current_pos + delta
                if 0 <= neighbor_pos < len(dim_values):
                    neighbor_combo = list(combo)
                    neighbor_combo[dim_idx] = dim_values[neighbor_pos]
                    neighbor_key = tuple(neighbor_combo)
                    if neighbor_key in scores_map:
                        neighbor_sharpes.append(scores_map[neighbor_key])

        if neighbor_sharpes:
            media_vicini = sum(neighbor_sharpes) / len(neighbor_sharpes)
            robustness = PESO_PROPRIO * own_sharpe + PESO_VICINI * media_vicini
        else:
            # Combinazione senza vicini validi: usa solo lo Sharpe proprio
            robustness = own_sharpe

        all_robustness[combo] = robustness

        if robustness > best_robustness:
            best_robustness = robustness
            best_own_sharpe = own_sharpe
            best_own_return = return_map.get(combo, 0.0)
            best_params = dict(zip(param_names, combo))

    # --- Valutazione out-of-sample con buffer warm-up ---
    oos_result = None
    spec = STRATEGY_SPECS[strategy_id]
    int_param_names = [p.name for p in spec.parameters if p.value_type == "int"]
    warmup = max(
        (int(best_params[name]) for name in int_param_names if name in best_params),
        default=30,
    )
    warmup = min(warmup, split_index)

    context_start = max(0, split_index - warmup)
    context_data = data.iloc[context_start:]

    try:
        signal_ctx = build_strategy_signal(
            strategy_id=strategy_id,
            data=context_data,
            parameters=best_params,
        )
        signal_test = signal_ctx.loc[test_data.index]
        oos_result = run_backtest(
            data=test_data,
            signal=signal_test,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
        )
        oos_score = float(oos_result.summary.get("sharpe_ratio", 0.0))
    except Exception:
        oos_score = float("nan")

    # --- Curve equity IS e OOS per visualizzazione ---
    equity_is: dict | None = None
    equity_oos: dict | None = None

    try:
        signal_is = build_strategy_signal(
            strategy_id=strategy_id, data=train_data, parameters=best_params
        )
        is_result = run_backtest(
            data=train_data, signal=signal_is,
            initial_capital=initial_capital, fee_bps=fee_bps,
        )
        equity_is = _equity_to_payload(is_result.equity_curve)
    except Exception:
        pass

    if oos_result is not None:
        try:
            equity_oos = _equity_to_payload(oos_result.equity_curve)
        except Exception:
            pass

    overfitting_warning = _calcola_warning_overfitting(best_own_sharpe, oos_score)

    # Costruisce lista di tutti i risultati per la visualizzazione heatmap
    all_scores = [
        {
            "params": dict(zip(param_names, combo)),
            "sharpe": round(sharpe, 3),
            "robustness": round(all_robustness.get(combo, sharpe), 3),
        }
        for combo, sharpe in scores_map.items()
    ]

    return {
        "best_params": best_params,
        "sharpe_in_sample": round(best_own_sharpe, 3),
        "sharpe_out_of_sample": round(oos_score, 3) if not _is_nan(oos_score) else None,
        "total_return_pct": round(best_own_return, 2),
        "robustness_score": round(best_robustness, 3),
        "combinations_tested": len(scores_map),
        "combinations_invalid": combinations_invalid,
        "train_bars": int(split_index),
        "test_bars": int(len(test_data)),
        "overfitting_warning": overfitting_warning,
        "param_names": param_names,
        "all_scores": all_scores,
        "equity_is": equity_is,
        "equity_oos": equity_oos,
    }


def _calcola_warning_overfitting(is_score: float, oos_score: float) -> str | None:
    if _is_nan(oos_score) or _is_nan(is_score) or is_score <= 0:
        return None
    calo = (is_score - oos_score) / abs(is_score)
    if calo > OVERFIT_SOGLIA:
        return (
            f"Possibile overfitting: Sharpe in-sample {is_score:.2f}, "
            f"out-of-sample {oos_score:.2f} (calo {calo * 100:.0f}%)."
        )
    return None


def _is_nan(value: float) -> bool:
    return math.isnan(value) or math.isinf(value)


def _equity_to_payload(equity_curve: "pd.DataFrame") -> dict:
    """Converte equity_curve in {dates, values} normalizzati a 100 all'inizio."""
    eq = equity_curve["equity"].values
    initial = float(eq[0]) if len(eq) > 0 and float(eq[0]) > 0 else 1.0
    dates = equity_curve.index.strftime("%Y-%m-%d").tolist()
    values = [round(float(v) / initial * 100.0, 2) for v in eq]
    return {"dates": dates, "values": values}
