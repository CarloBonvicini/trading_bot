"""La prova del caso su un portafoglio, e il budget della ricerca.

Con più mercati ci sono due strutture da distruggere — quella nel tempo e
quella *fra* i mercati — e mescolare ognuno per conto suo le distrugge tutte e
due. Sarebbe l'errore comodo: una strategia che ordina i mercati fra loro vive
della struttura trasversale, e misurarla contro un mondo dove quella struttura
non esiste vorrebbe dire darle un avversario che non ha mai incontrato.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.application.prova_del_caso import mescola_mercati, mescola_serie
from trading_bot.application.ricerca_portafoglio import (
    BUDGET_PREDEFINITO,
    cerca_portafoglio,
    elenca_configurazioni,
)
from trading_bot.trasversali import classifica_di_forza


def _mercati(quanti: int = 6, n: int = 800, seed: int = 0, insieme: float = 0.6) -> dict:
    """``insieme`` da 0 a 1: quanta parte del movimento è comune a tutti."""
    rng = np.random.default_rng(seed)
    comune = rng.normal(0.0003, 0.011, n)
    idx = pd.bdate_range("2018-01-02", periods=n)
    fuori = {}
    for i in range(quanti):
        r = insieme * comune + (1 - insieme) * rng.normal(0.0003, 0.011, n)
        close = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
        fuori[f"M{i}"] = pd.DataFrame(
            {"open": close, "high": close * 1.008, "low": close * 0.992,
             "close": close, "volume": pd.Series(1000.0, index=idx)}
        )
    return fuori


def _quanto_insieme(mercati: dict) -> float:
    prezzi = pd.DataFrame({n: d["close"] for n, d in mercati.items()})
    matrice = prezzi.pct_change().corr().to_numpy(dtype=float)
    return float(matrice[np.triu_indices_from(matrice, k=1)].mean())


# ── Il mescolamento giusto ───────────────────────────────────────────────────

def test_mescolare_insieme_conserva_chi_si_muove_con_chi() -> None:
    """È la ragione per cui la permutazione è unica per tutti i mercati.

    Se sparisse anche la struttura fra i mercati, una classifica di forza si
    ritroverebbe a competere contro un mondo che non ha mai incontrato, e
    qualunque risultato passerebbe la prova."""
    veri = _mercati(insieme=0.7)

    insieme = mescola_mercati(veri, seed=0)
    ognuno_per_conto_suo = {
        nome: mescola_serie(dati, seed=i) for i, (nome, dati) in enumerate(veri.items())
    }

    assert _quanto_insieme(insieme) == pytest.approx(_quanto_insieme(veri), abs=0.05)
    assert _quanto_insieme(ognuno_per_conto_suo) < _quanto_insieme(veri) / 2


def test_mescolare_insieme_distrugge_il_tempo() -> None:
    """L'altra metà: la forza non deve più durare da una barra all'altra,
    altrimenti non abbiamo tolto niente."""
    veri = _mercati(n=1000, insieme=0.3)
    mescolati = mescola_mercati(veri, seed=1)

    def quanto_dura(mercati: dict) -> float:
        forza = classifica_di_forza(mercati, periodo=120).dropna()
        # Quanto la classifica di oggi somiglia a quella di venti barre fa.
        return float(
            forza.rank(axis=1).corrwith(forza.rank(axis=1).shift(20), axis=1).mean()
        )

    assert quanto_dura(veri) > 0.5
    assert quanto_dura(mescolati) < quanto_dura(veri)


def test_mescolare_conserva_la_volatilita_di_ciascuno() -> None:
    veri = _mercati()
    mescolati = mescola_mercati(veri, seed=2)

    for nome in veri:
        vera = veri[nome]["close"].pct_change().std()
        finta = mescolati[nome]["close"].pct_change().std()
        assert finta == pytest.approx(vera, rel=0.001)
        assert mescolati[nome].index.equals(veri[nome].index)


def test_mescolare_e_ripetibile() -> None:
    veri = _mercati()
    assert mescola_mercati(veri, seed=5)["M0"]["close"].equals(
        mescola_mercati(veri, seed=5)["M0"]["close"]
    )


def test_mercati_di_lunghezze_diverse_non_si_mescolano_insieme() -> None:
    veri = _mercati(quanti=2)
    veri["M1"] = veri["M1"].iloc[:-10]

    with pytest.raises(ValueError, match="stesso numero di barre"):
        mescola_mercati(veri, seed=0)


# ── Il budget dichiarato ─────────────────────────────────────────────────────

def test_la_griglia_e_piccola_e_dichiarata() -> None:
    assert len(elenca_configurazioni()) <= BUDGET_PREDEFINITO
    # Col ribasso il lavoro raddoppia, come nella ricerca a mercato singolo.
    assert len(elenca_configurazioni(consenti_short=True)) == 2 * len(elenca_configurazioni())


@pytest.mark.lento
def test_una_griglia_oltre_il_budget_ne_prova_un_campione_e_lo_dice() -> None:
    """Il budget non fa più fallire la ricerca: la fa scegliere dove guardare.

    Ma chi legge il risultato deve sapere che è stata una scelta, perché una
    ricerca che ha guardato 20 punti su 192 e una che li ha guardati tutti non
    dicono la stessa cosa sulla facilità di vincere per caso."""
    mercati = _mercati(quanti=4, n=900)

    esito = cerca_portafoglio(mercati, budget=20)

    assert esito.configurazioni_provate == 20
    assert esito.configurazioni_possibili == len(elenca_configurazioni())
    assert "delle 192 possibili" in esito.verdetto


def test_il_campione_e_sparso_e_ripetibile() -> None:
    """Prendere le prime N darebbe tutte configurazioni con lo stesso periodo:
    l'elenco nasce da un prodotto, quindi il suo inizio è un angolo dello
    spazio, non un campione."""
    from trading_bot.application.ricerca_portafoglio import _sottoinsieme_sparso

    tutte = elenca_configurazioni()
    campione = _sottoinsieme_sparso(tutte, 12)

    assert len(campione) == 12
    assert campione == _sottoinsieme_sparso(tutte, 12)
    # Attraversa lo spazio invece di fermarsi in un angolo.
    assert len({tuple(c.parametri) for c in campione}) > 1
    assert len({c.ribilancia_ogni for c in campione}) > 1


def test_un_portafoglio_ha_senso_da_due_mercati_in_su() -> None:
    with pytest.raises(ValueError, match="due mercati"):
        cerca_portafoglio(_mercati(quanti=1, n=400))


def test_serve_abbastanza_storia_per_separare_sviluppo_e_prova() -> None:
    with pytest.raises(ValueError, match="barre in comune"):
        cerca_portafoglio(_mercati(quanti=3, n=200))


# ── La ricerca vera ──────────────────────────────────────────────────────────

@pytest.mark.lento
def test_la_ricerca_sceglie_sullo_sviluppo_e_misura_sulla_prova() -> None:
    mercati = _mercati(quanti=8, n=900, seed=3)

    esito = cerca_portafoglio(mercati, fee_bps=5.0)

    assert esito.barre_sviluppo + esito.barre_prova == esito.barre
    assert esito.configurazioni_provate == len(elenca_configurazioni())
    assert esito.migliore is not None
    assert esito.riepilogo_prova["mercati_count"] == 8
    # Il numero onesto e quello col senno di poi sono due cose diverse, e il
    # secondo non può essere più basso del primo.
    assert esito.margine_col_senno_di_poi_pct >= esito.margine_pct
    assert str(esito.configurazioni_provate) in esito.verdetto


@pytest.mark.lento
def test_su_mercati_senza_struttura_la_procedura_onesta_non_trova_niente() -> None:
    """Il test negativo, che è quello che conta.

    Su storie rimescolate insieme non c'è niente da trovare per costruzione. Se
    la procedura onesta ci cavasse un vantaggio, vorrebbe dire che sta
    misurando se stessa e non il mercato.

    Il numero col senno di poi invece resta alto anche lì — misurato: fino a
    +20 punti — ed è esattamente la ragione per cui i due non vanno confusi.
    """
    mercati = _mercati(quanti=8, n=900, seed=7)
    finti = mescola_mercati(mercati, seed=0)

    esito = cerca_portafoglio(finti, fee_bps=5.0)

    assert esito.margine_pct < 5.0, (
        f"su dati senza struttura la procedura onesta trova {esito.margine_pct:+.1f} "
        "punti di vantaggio: sta misurando se stessa"
    )


@pytest.mark.lento
def test_la_prova_del_caso_arriva_fino_al_verdetto() -> None:
    mercati = _mercati(quanti=6, n=900, seed=5)

    esito = cerca_portafoglio(mercati, fee_bps=5.0, prove_del_caso=1)

    assert esito.prova_del_caso is not None
    assert esito.prova_del_caso["prove"] == 1
    assert esito.prova_del_caso["verdetto"] in esito.verdetto
