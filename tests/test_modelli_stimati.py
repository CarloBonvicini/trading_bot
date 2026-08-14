"""Modelli che ricavano i propri numeri dai dati, invece di riceverli.

La differenza con tutto il resto del catalogo: qui la strategia non dà per
scontato che il prezzo rientri verso la media — lo misura, e se il mercato non
sta rientrando resta fuori. Il rischio, altrettanto nuovo, è che il modello
"riconosca" struttura anche dove non ce n'è.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.application.prova_del_caso import mescola_serie
from trading_bot.features import mezza_vita, zscore
from trading_bot.strategies import build_strategy_signal, ritorno_media_stimato


def _frame(chiusure: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2021-01-04", periods=len(chiusure))
    close = pd.Series(chiusure, index=idx)
    return pd.DataFrame(
        {"open": close, "high": close * 1.006, "low": close * 0.994, "close": close,
         "volume": pd.Series(1000.0, index=idx)}
    )


def _serie_che_rientra(n: int = 500, forza: float = 0.15, seed: int = 3) -> pd.DataFrame:
    """Serie costruita per rientrare: ogni giorno recupera parte dello scarto."""
    rng = np.random.default_rng(seed)
    scarto = np.zeros(n)
    for i in range(1, n):
        scarto[i] = scarto[i - 1] - forza * scarto[i - 1] + rng.normal(0, 1)
    return _frame(list(100 + scarto))


def _cammino_casuale(n: int = 500, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _frame(list(100 + np.cumsum(rng.normal(0, 1, n))))


# ── La misura ────────────────────────────────────────────────────────────────

def test_la_mezza_vita_riconosce_un_rientro_vero() -> None:
    """Con un recupero del 15% al giorno la metà della strada si copre in circa
    quattro barre: la stima deve avvicinarsi a quel numero."""
    stimata = mezza_vita(_serie_che_rientra(forza=0.15)).replace(np.inf, np.nan).dropna()

    atteso = -np.log(2) / np.log(1 - 0.15)   # ≈ 4,3 barre
    assert stimata.median() == pytest.approx(atteso, rel=0.4)


def test_un_rientro_piu_lento_da_una_mezza_vita_piu_lunga() -> None:
    lento = mezza_vita(_serie_che_rientra(forza=0.05)).replace(np.inf, np.nan).dropna()
    rapido = mezza_vita(_serie_che_rientra(forza=0.30)).replace(np.inf, np.nan).dropna()

    assert lento.median() > rapido.median()


def test_su_un_cammino_casuale_spesso_non_c_e_rientro() -> None:
    """Un cammino casuale non rientra da nessuna parte. La stima su finestra
    corta ne trova comunque qualcuno per caso — ed è la ragione per cui la
    strategia pretende un rientro *rapido*, non un rientro qualsiasi."""
    stimata = mezza_vita(_cammino_casuale())

    assert np.isinf(stimata.dropna()).mean() > 0.05
    veri = mezza_vita(_serie_che_rientra())
    assert np.isinf(stimata.dropna()).mean() > np.isinf(veri.dropna()).mean()


def test_la_finestra_di_stima_non_puo_essere_ridicola() -> None:
    with pytest.raises(ValueError, match="almeno 20 barre"):
        mezza_vita(_cammino_casuale(), finestra=10)


def test_lo_scostamento_e_in_deviazioni_standard() -> None:
    """Due deviazioni sopra la media devono valere 2, su qualsiasi mercato."""
    dati = _serie_che_rientra()
    valori = zscore(dati, finestra=20).dropna()

    assert valori.abs().max() > 2.0
    assert valori.std() == pytest.approx(1.0, rel=0.35)


# ── La strategia ─────────────────────────────────────────────────────────────

def test_opera_dove_il_prezzo_rientra_davvero() -> None:
    segnale = ritorno_media_stimato(_serie_che_rientra(), mezza_vita_massima=10)

    assert (segnale != 0).any(), "non ha mai operato dove il rientro è evidente"


def test_resta_fuori_dove_non_c_e_rientro_da_aspettarsi() -> None:
    """Il punto della strategia: una mean reversion normale comprerebbe ogni
    scostamento, anche in un mercato che scende e basta."""
    discesa = _frame([100.0 - 0.4 * i for i in range(400)])

    stimata = ritorno_media_stimato(discesa, mezza_vita_massima=5)
    classica = build_strategy_signal(
        strategy_id="rsi_mean_reversion", data=discesa,
        parameters={"period": 14, "lower": 30.0, "upper": 55.0},
    )

    assert stimata.abs().mean() < classica.abs().mean(), (
        "su una discesa continua opera quanto una mean reversion cieca"
    )


def test_piu_il_rientro_e_rapido_piu_capitale_impegna() -> None:
    rapido = ritorno_media_stimato(_serie_che_rientra(forza=0.35), mezza_vita_massima=10)
    lento = ritorno_media_stimato(_serie_che_rientra(forza=0.05), mezza_vita_massima=10)

    assert rapido.abs().mean() > lento.abs().mean()


def test_pretendere_un_rientro_piu_rapido_rende_piu_selettivi() -> None:
    dati = _cammino_casuale()

    esigente = ritorno_media_stimato(dati, mezza_vita_massima=2)
    permissiva = ritorno_media_stimato(dati, mezza_vita_massima=30)

    assert (esigente != 0).sum() < (permissiva != 0).sum()


def test_rifiuta_parametri_senza_senso() -> None:
    dati = _cammino_casuale()
    with pytest.raises(ValueError, match="soglia"):
        ritorno_media_stimato(dati, soglia=0)
    with pytest.raises(ValueError, match="mezza vita"):
        ritorno_media_stimato(dati, mezza_vita_massima=0)


# ── La prova che conta ───────────────────────────────────────────────────────

def test_sui_dati_rimescolati_il_modello_non_trova_struttura() -> None:
    """Il controllo decisivo per un modello che si stima.

    Rimescolando i rendimenti la struttura temporale sparisce: il rientro alla
    media non esiste più, mentre volatilità e ampiezza dei movimenti restano
    identiche. Un modello che continuasse a "riconoscere" rientri con la stessa
    frequenza starebbe descrivendo il proprio rumore, non il mercato.
    """
    vera = _serie_che_rientra(forza=0.25)
    rimescolata = mescola_serie(vera, seed=1)

    operativita_vera = (ritorno_media_stimato(vera, mezza_vita_massima=5) != 0).mean()
    operativita_finta = (
        ritorno_media_stimato(rimescolata, mezza_vita_massima=5) != 0
    ).mean()

    assert operativita_vera > operativita_finta * 1.5, (
        f"opera quasi uguale sul rumore ({operativita_finta:.1%}) e sulla struttura "
        f"vera ({operativita_vera:.1%}): il modello non sta misurando niente"
    )
