"""Il segnale graduato: non solo "da che parte", ma "quanto ci credo".

Il motore accettava già valori fra -1 e +1, ma li trattava male: le operazioni
venivano contate arrotondando la posizione, quindi entrare convinti al 40%
risultava "nessuna operazione" mentre il capitale era davvero a rischio.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest import run_backtest
from trading_bot.strategies import CONVINZIONE_MINIMA, applica_convinzione, kama_trend


def _mercato(chiusure: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(chiusure), freq="D")
    close = pd.Series(chiusure, index=idx)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)


# ── Il motore ────────────────────────────────────────────────────────────────

def test_meta_convinzione_meta_risultato() -> None:
    """La proprietà che rende sensato il canale: mettere metà capitale espone a
    metà del movimento, in guadagno come in perdita."""
    dati = _mercato([100.0, 110.0, 121.0])

    intera = run_backtest(
        data=dati, signal=pd.Series(1.0, index=dati.index), initial_capital=1000.0, fee_bps=0.0
    )
    meta = run_backtest(
        data=dati, signal=pd.Series(0.5, index=dati.index), initial_capital=1000.0, fee_bps=0.0
    )

    guadagno_intero = intera.summary["final_equity"] - 1000.0
    guadagno_meta = meta.summary["final_equity"] - 1000.0
    # Non esattamente la metà per via della capitalizzazione composta, ma vicino.
    assert guadagno_meta == pytest.approx(guadagno_intero / 2, rel=0.06)
    assert guadagno_meta < guadagno_intero


def test_una_posizione_parziale_e_comunque_un_operazione() -> None:
    """Regressione: il conteggio arrotondava la posizione, quindi 0,4 diventava
    zero. Il registro diceva "nessuna operazione" mentre l'equity si muoveva, e
    la ricerca scartava la strategia credendola inerte."""
    dati = _mercato([100.0, 110.0, 121.0, 110.0])

    for convinzione in (0.4, 0.5, 0.9):
        risultato = run_backtest(
            data=dati, signal=pd.Series(convinzione, index=dati.index), fee_bps=0.0
        )
        assert risultato.summary["trade_count"] == 1, f"convinzione {convinzione} non conta"
        assert risultato.summary["exposure_pct"] > 0


def test_cambiare_convinzione_non_apre_una_nuova_operazione() -> None:
    """Aumentare l'importo restando dalla stessa parte non è una nuova
    operazione: è la stessa posizione, più grande."""
    dati = _mercato([100.0, 105.0, 110.0, 115.0, 120.0, 125.0])
    graduale = pd.Series([0.3, 0.5, 0.8, 0.8, 0.4, 0.4], index=dati.index)

    risultato = run_backtest(data=dati, signal=graduale, fee_bps=0.0)

    assert risultato.summary["trade_count"] == 1


def test_il_ribaltamento_conta_anche_con_importi_parziali() -> None:
    dati = _mercato([100.0, 105.0, 110.0, 105.0, 100.0, 95.0])
    segnale = pd.Series([0.4, 0.4, -0.3, -0.3, -0.3, -0.3], index=dati.index)

    risultato = run_backtest(data=dati, signal=segnale, fee_bps=0.0)

    assert risultato.summary["trade_count"] == 2
    assert risultato.summary["short_trade_count"] == 1


# ── Il canale nelle strategie ────────────────────────────────────────────────

def test_senza_convinzione_il_verso_resta_intatto() -> None:
    """È la garanzia che rende sicura l'aggiunta: chi non la usa non cambia."""
    verso = pd.Series([1.0, 0.0, -1.0, 1.0])

    pd.testing.assert_series_equal(applica_convinzione(verso, None), verso)


def test_la_convinzione_scala_il_verso() -> None:
    verso = pd.Series([1.0, -1.0, 1.0])
    convinzione = pd.Series([1.0, 0.5, 0.25])

    dosato = applica_convinzione(verso, convinzione)

    assert list(dosato) == [1.0, -0.5, 0.25]


def test_sotto_la_soglia_si_resta_fuori() -> None:
    """Entrare con una frazione irrisoria significa pagare commissioni e scarto
    di prezzo per intero su un capitale che non può ripagarli."""
    verso = pd.Series([1.0, 1.0, 1.0])
    convinzione = pd.Series([CONVINZIONE_MINIMA / 2, CONVINZIONE_MINIMA, 1.0])

    dosato = applica_convinzione(verso, convinzione)

    assert dosato.iloc[0] == 0.0
    assert dosato.iloc[1] > 0
    assert dosato.iloc[2] == 1.0


def test_la_convinzione_resta_nei_limiti() -> None:
    verso = pd.Series([1.0, -1.0])
    esagerata = pd.Series([5.0, -3.0])   # fuori scala per errore

    dosato = applica_convinzione(verso, esagerata)

    assert dosato.abs().max() <= 1.0


# ── La strategia che la usa ──────────────────────────────────────────────────

def test_la_kama_dosata_impegna_meno_capitale_nel_rumore() -> None:
    """La promessa: nei tratti confusi resta quasi fuori invece di entrare con
    tutto, perché la stessa misura che rallenta la media riduce l'importo."""
    rng = np.random.default_rng(7)
    dati = _mercato(list(100 + np.cumsum(rng.normal(0.0, 1.0, 400))))

    dosata = kama_trend(dati, periodo=10, dosa=1)
    piena = kama_trend(dati, periodo=10, dosa=0)

    assert dosata.abs().mean() < piena.abs().mean()
    # E dove la piena è dentro, la dosata non può essere dalla parte opposta.
    assert not ((piena > 0) & (dosata < 0)).any()


def test_la_kama_dosata_produce_importi_graduati() -> None:
    rng = np.random.default_rng(7)
    dati = _mercato(list(100 + np.cumsum(rng.normal(0.0, 1.0, 400))))

    dosata = kama_trend(dati, periodo=10, dosa=1)
    valori = set(np.unique(dosata.round(2).to_numpy()))

    assert len(valori) > 5, "gli importi non sono graduati"
    assert valori <= {0.0} | {round(v, 2) for v in np.arange(0.15, 1.01, 0.01)}
