"""Il registro degli indicatori, e soprattutto: quando NON deve riusare.

Il rischio di una memoria condivisa non è la lentezza, è servire il valore
sbagliato: un backtest che gira sugli indicatori di un altro mercato non
fallisce, restituisce un risultato falso. Questi test descrivono i casi in cui
il riuso deve essere impedito, prima ancora di quelli in cui deve avvenire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot import features
from trading_bot.application.prova_del_caso import mescola_serie
from trading_bot.features import (
    INDICATORI,
    contesto_attivo,
    contesto_indicatori,
    indicatore,
    registra,
)


@pytest.fixture
def registro_pulito():
    """Isola il registro: i test possono aggiungere indicatori finti senza
    lasciarli in giro per gli altri."""
    originale = dict(INDICATORI)
    INDICATORI.clear()
    yield INDICATORI
    INDICATORI.clear()
    INDICATORI.update(originale)


def _mercato(valori: list[float], inizio: str = "2022-01-03") -> pd.DataFrame:
    idx = pd.date_range(inizio, periods=len(valori), freq="D")
    serie = pd.Series(valori, index=idx)
    return pd.DataFrame({"close": serie, "high": serie * 1.01, "low": serie * 0.99}, index=idx)


# ── Quando il riuso deve essere impedito ─────────────────────────────────────

def test_due_mercati_diversi_non_si_contaminano(registro_pulito) -> None:
    """Il caso che rovinerebbe tutto in silenzio."""
    @registra("media")
    def _media(dati, periodo):
        return dati["close"].rolling(periodo).mean()

    uno = _mercato([10.0, 20.0, 30.0, 40.0])
    due = _mercato([100.0, 200.0, 300.0, 400.0])

    with contesto_indicatori(uno):
        primo = indicatore("media", uno, periodo=2)
        secondo = indicatore("media", due, periodo=2)   # dati diversi, stesso nome e parametri

    assert primo.iloc[-1] == pytest.approx(35.0)
    assert secondo.iloc[-1] == pytest.approx(350.0), "ha servito i valori dell'altro mercato"


def test_la_storia_rimescolata_non_eredita_gli_indicatori(registro_pulito) -> None:
    """Il caso più insidioso: stesso indice, stesse date, prezzi diversi.

    La prova del caso rifà la ricerca su una storia rimescolata. Se il registro
    riconoscesse quei dati come "gli stessi" — hanno lo stesso indice — la prova
    userebbe gli indicatori del mercato vero e direbbe sempre che la strategia
    ha superato la prova. Il controllo più importante che abbiamo diventerebbe
    una formalità che passa sempre.
    """
    @registra("media")
    def _media(dati, periodo):
        return dati["close"].rolling(periodo).mean()

    rng = np.random.default_rng(4)
    chiusure = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 120)))
    vero = _mercato(list(chiusure))
    rimescolato = mescola_serie(vero, seed=1)

    assert list(rimescolato.index) == list(vero.index), "premessa: l'indice è identico"

    with contesto_indicatori(vero):
        su_vero = indicatore("media", vero, periodo=10)
        su_rimescolato = indicatore("media", rimescolato, periodo=10)

    assert not su_vero.equals(su_rimescolato), "la storia rimescolata ha ereditato la memoria"


def test_parametri_diversi_sono_valori_diversi(registro_pulito) -> None:
    @registra("media")
    def _media(dati, periodo):
        return dati["close"].rolling(periodo).mean()

    dati = _mercato([10.0, 20.0, 30.0, 40.0])
    with contesto_indicatori(dati) as contesto:
        due = indicatore("media", dati, periodo=2)
        tre = indicatore("media", dati, periodo=3)

    assert due.iloc[-1] != tre.iloc[-1]
    assert contesto.calcoli == 2


def test_senza_contesto_si_calcola_sempre(registro_pulito) -> None:
    """Fuori da un contesto niente memoria: è ciò che rende sicura la
    migrazione delle strategie una alla volta."""
    chiamate = []

    @registra("media")
    def _media(dati, periodo):
        chiamate.append(periodo)
        return dati["close"].rolling(periodo).mean()

    dati = _mercato([10.0, 20.0, 30.0, 40.0])
    indicatore("media", dati, periodo=2)
    indicatore("media", dati, periodo=2)

    assert chiamate == [2, 2]
    assert contesto_attivo() is None


# ── Quando il riuso deve avvenire ────────────────────────────────────────────

def test_dentro_il_contesto_si_calcola_una_volta_sola(registro_pulito) -> None:
    chiamate = []

    @registra("media")
    def _media(dati, periodo):
        chiamate.append(periodo)
        return dati["close"].rolling(periodo).mean()

    dati = _mercato([10.0, 20.0, 30.0, 40.0])
    with contesto_indicatori(dati) as contesto:
        for _ in range(50):
            indicatore("media", dati, periodo=2)

    assert chiamate == [2], "l'indicatore è stato ricalcolato"
    assert contesto.calcoli == 1
    assert contesto.riusi == 49


def test_il_valore_riusato_e_identico(registro_pulito) -> None:
    @registra("media")
    def _media(dati, periodo):
        return dati["close"].rolling(periodo).mean()

    dati = _mercato([10.0, 20.0, 30.0, 40.0, 50.0])
    with contesto_indicatori(dati):
        primo = indicatore("media", dati, periodo=3)
        secondo = indicatore("media", dati, periodo=3)

    pd.testing.assert_series_equal(primo, secondo)


def test_i_contesti_si_annidano_e_si_richiudono(registro_pulito) -> None:
    """Aprire un contesto dentro un altro non deve lasciare il contesto sbagliato
    attivo all'uscita: la ricerca ne apre uno per mercato, dentro un ciclo."""
    @registra("media")
    def _media(dati, periodo):
        return dati["close"].rolling(periodo).mean()

    uno = _mercato([10.0, 20.0, 30.0])
    due = _mercato([1.0, 2.0, 3.0])

    with contesto_indicatori(uno) as esterno:
        with contesto_indicatori(due) as interno:
            assert contesto_attivo() is interno
        assert contesto_attivo() is esterno
    assert contesto_attivo() is None


# ── Il registro in sé ────────────────────────────────────────────────────────

def test_un_nome_non_si_registra_due_volte(registro_pulito) -> None:
    """Due indicatori con lo stesso nome sarebbero un errore silenzioso: chi
    chiama otterrebbe quello sbagliato senza accorgersene."""
    @registra("media")
    def _prima(dati):
        return dati["close"]

    with pytest.raises(ValueError, match="già registrato"):
        @registra("media")
        def _seconda(dati):
            return dati["close"] * 2


def test_un_indicatore_sconosciuto_lo_dice(registro_pulito) -> None:
    with pytest.raises(ValueError, match="non registrato"):
        indicatore("inesistente", _mercato([1.0, 2.0]))


def test_gli_indicatori_del_catalogo_sono_registrati() -> None:
    """Man mano che le strategie migrano, gli indicatori compaiono qui."""
    assert "rsi" in features.INDICATORI
