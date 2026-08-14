"""Test del verso al ribasso delle strategie.

Due proprietà valgono per tutte e quindi si controllano in blocco su tutto il
catalogo; le regole specifiche di ogni famiglia hanno il loro test dedicato.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.strategies import (
    STRATEGY_SPECS,
    adx_trend,
    bollinger_reversion,
    build_strategy_signal,
    donchian_breakout,
    parabolic_sar,
    roc_momentum,
    rsi_mean_reversion,
    sma_crossover,
)

TUTTE = sorted(STRATEGY_SPECS)


def _mercato_mosso(n: int = 400, seed: int = 9) -> pd.DataFrame:
    """Mercato che sale e poi crolla, con oscillazioni realistiche.

    Serve una serie con variazioni giornaliere vere (intorno all'1,5%): una
    rampa lineare con poco rumore non rompe mai un minimo a 20 giorni e non
    esce mai dalle bande, quindi metà delle strategie non avrebbe occasione di
    aprire una posizione in nessuno dei due versi.
    """
    rng = np.random.default_rng(seed)
    meta = n // 2
    deriva = np.concatenate([np.full(meta, 0.003), np.full(n - meta, -0.004)])
    volatilita = np.concatenate([np.full(meta, 0.015), np.full(n - meta, 0.020)])
    chiusure = 100.0 * np.exp(np.cumsum(rng.normal(deriva, volatilita)))
    return pd.DataFrame(
        {
            "open": chiusure,
            "high": chiusure * 1.008,
            "low": chiusure * 0.992,
            "close": chiusure,
            "volume": rng.integers(1000, 5000, n).astype(float),
        },
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_senza_consenso_nessuna_strategia_va_al_ribasso(strategy_id: str) -> None:
    """Il comportamento di default non cambia: mai posizioni al ribasso.

    Si guarda il **verso**, non il valore esatto: da quando esiste la
    convinzione una strategia può impegnare una frazione di capitale, e 0,4 è
    una posizione al rialzo tanto quanto 1,0.
    """
    segnale = build_strategy_signal(
        strategy_id=strategy_id,
        data=_mercato_mosso(),
        parameters=STRATEGY_SPECS[strategy_id].defaults(),
    )
    assert (segnale >= 0).all(), "senza consenso non deve mai andare al ribasso"
    assert (segnale <= 1).all(), "nessuna posizione può superare il capitale"


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_col_consenso_il_segnale_resta_nei_limiti(strategy_id: str) -> None:
    """Il verso può essere in entrambe le direzioni, l'importo mai oltre il capitale."""
    segnale = build_strategy_signal(
        strategy_id=strategy_id,
        data=_mercato_mosso(),
        parameters=STRATEGY_SPECS[strategy_id].defaults(),
        consenti_short=True,
    )
    assert segnale.abs().max() <= 1.0
    assert set(np.unique(np.sign(segnale.to_numpy()))).issubset({-1.0, 0.0, 1.0})


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_col_consenso_ogni_strategia_apre_almeno_una_posizione_al_ribasso(
    strategy_id: str,
) -> None:
    """Su un mercato che sale e poi crolla ogni strategia deve trovare almeno
    un momento per stare al ribasso: se non lo fa, la regola non è collegata."""
    segnale = build_strategy_signal(
        strategy_id=strategy_id,
        data=_mercato_mosso(),
        parameters=STRATEGY_SPECS[strategy_id].defaults(),
        consenti_short=True,
    )
    assert (segnale < 0).any(), f"{strategy_id} non va mai al ribasso"


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_il_verso_al_rialzo_non_cambia_col_consenso(strategy_id: str) -> None:
    """Attivare il ribasso non deve spostare le barre in cui si era al rialzo:
    le posizioni long devono restare esattamente dov'erano."""
    data = _mercato_mosso()
    parametri = STRATEGY_SPECS[strategy_id].defaults()
    solo_long = build_strategy_signal(strategy_id=strategy_id, data=data, parameters=parametri)
    con_short = build_strategy_signal(
        strategy_id=strategy_id, data=data, parameters=parametri, consenti_short=True
    )

    if strategy_id in {"parabolic_sar", "sma_cross", "ema_cross", "macd_trend", "obv_trend"}:
        # Strategie sempre a mercato: dove prima stavano ferme ora vanno al
        # ribasso, ma le barre al rialzo sono le stesse.
        assert con_short[solo_long > 0].eq(1.0).all()
        return

    # Strategie con stato: dopo una posizione al ribasso il momento di rientrare
    # al rialzo può cambiare, quindi si verifica solo che il long non si inverta.
    assert not (con_short[solo_long > 0] < 0).any()


# ── Regole specifiche per famiglia ───────────────────────────────────────────

def test_media_mobile_va_al_ribasso_quando_la_veloce_passa_sotto() -> None:
    # Salita continua, poi discesa continua: le due medie non restano mai pari.
    chiusure = [100.0 + i for i in range(15)] + [114.0 - 2 * i for i in range(1, 11)]
    data = pd.DataFrame(
        {"close": chiusure},
        index=pd.date_range("2024-01-01", periods=len(chiusure), freq="D"),
    )

    segnale = sma_crossover(data, fast=2, slow=5, consenti_short=True)

    assert segnale.iloc[10] == 1.0   # veloce sopra la lenta durante la salita
    assert segnale.iloc[-1] == -1.0  # veloce sotto la lenta durante la discesa


def test_rsi_apre_al_ribasso_sull_ipercomprato() -> None:
    """La mean reversion al ribasso è lo specchio: dove chiudeva il long
    (ipercomprato) ora apre lo short."""
    # Salita con ritracciamenti regolari: servono barre davvero negative,
    # altrimenti l'RSI resta indefinito (divisione per zero) e vale 50 fisso.
    salita = list(np.cumsum([100.0] + [3.0, 3.0, 3.0, -1.0] * 8))
    data = pd.DataFrame(
        {"close": salita}, index=pd.date_range("2024-01-01", periods=len(salita), freq="D")
    )

    solo_long = rsi_mean_reversion(data, period=5, lower=30.0, upper=55.0)
    con_short = rsi_mean_reversion(data, period=5, lower=30.0, upper=55.0, consenti_short=True)

    assert (solo_long == 0.0).all()   # non compra mai: il mercato non è mai ipervenduto
    assert (con_short == -1.0).any()  # ma è ipercomprato, quindi vende allo scoperto


def test_bollinger_vende_sulla_banda_superiore() -> None:
    chiusure = [100.0] * 25 + [140.0]
    data = pd.DataFrame(
        {"close": chiusure}, index=pd.date_range("2024-01-01", periods=len(chiusure), freq="D")
    )

    segnale = bollinger_reversion(data, period=20, std_dev=2.0, consenti_short=True)

    assert segnale.iloc[-1] == -1.0


def test_adx_al_ribasso_richiede_trend_forte_non_solo_uscita(ohlc_da_chiusure) -> None:
    """L'uscita dal rialzo comprende "trend spento", che non è un motivo per
    vendere allo scoperto: senza trend forte la posizione deve restare a zero."""
    # Mercato piatto: ADX bassissimo, nessun trend in nessuna direzione.
    data = ohlc_da_chiusure([100.0 + (i % 2) * 0.01 for i in range(80)], spread=0.02)

    segnale = adx_trend(data, period=14, threshold=25.0, consenti_short=True)

    assert (segnale == 0.0).all()


def test_donchian_vende_sulla_rottura_del_minimo(ohlc_da_chiusure) -> None:
    chiusure = [100.0] * 25 + [70.0]
    massimi = [101.0] * 25 + [71.0]
    minimi = [99.0] * 25 + [70.0]
    data = ohlc_da_chiusure(chiusure, massimi=massimi, minimi=minimi)

    segnale = donchian_breakout(data, entry_period=20, exit_period=10, consenti_short=True)

    assert segnale.iloc[-1] == -1.0


def test_roc_vende_sotto_la_soglia_negativa() -> None:
    chiusure = [100.0] * 10 + [80.0] * 5
    data = pd.DataFrame(
        {"close": chiusure}, index=pd.date_range("2024-01-01", periods=len(chiusure), freq="D")
    )

    segnale = roc_momentum(data, period=5, threshold=5.0, consenti_short=True)

    assert segnale.iloc[-1] == -1.0


def test_parabolic_sar_e_sempre_a_mercato_col_consenso(ohlc_da_chiusure) -> None:
    """Il SAR è simmetrico per costruzione: col ribasso attivo non sta mai fermo."""
    data = _mercato_mosso(n=120)

    segnale = parabolic_sar(data, step=0.02, max_step=0.20, consenti_short=True)

    assert not (segnale == 0.0).any()
    assert (segnale == -1.0).any()
    assert (segnale == 1.0).any()


def test_build_strategy_signal_ignora_il_consenso_se_la_strategia_non_lo_supporta(
    monkeypatch, ohlc_da_chiusure
) -> None:
    """Una strategia che dichiara di non avere una regola al ribasso non deve
    riceverla: meglio restare a zero che inventarne una."""
    import dataclasses

    spec = dataclasses.replace(STRATEGY_SPECS["sma_cross"], supports_short=False)
    monkeypatch.setitem(STRATEGY_SPECS, "sma_cross", spec)
    data = _mercato_mosso()

    segnale = build_strategy_signal(
        strategy_id="sma_cross", data=data, parameters={"fast": 5, "slow": 20},
        consenti_short=True,
    )

    assert set(np.unique(segnale.to_numpy())).issubset({0.0, 1.0})
