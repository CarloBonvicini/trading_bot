"""La vittoria trovata vale più di quella che trova la fortuna?"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.application.prova_del_caso import (
    MARGINE_SUL_CASO_MINIMO,
    mescola_serie,
    valuta_contro_il_caso,
)


def _serie_con_tendenza(n: int = 600, seed: int = 2) -> pd.DataFrame:
    """Rendimenti autocorrelati: ogni giorno eredita metà del movimento del
    giorno prima. È la struttura che una strategia di tendenza può sfruttare,
    ed è esattamente quella che il rimescolamento deve distruggere."""
    rng = np.random.default_rng(seed)
    grezzi = rng.normal(0.0002, 0.010, n)
    ret = np.zeros(n)
    for i in range(1, n):
        ret[i] = 0.55 * ret[i - 1] + grezzi[i]
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.bdate_range("2021-01-04", periods=n)
    return pd.DataFrame(
        {"open": close, "high": close * 1.006, "low": close * 0.994, "close": close,
         "volume": np.full(n, 1000.0)},
        index=idx,
    )


# ── Il rimescolamento ────────────────────────────────────────────────────────

def test_mescolare_distrugge_la_struttura_ma_non_la_statistica() -> None:
    originale = _serie_con_tendenza()
    mescolata = mescola_serie(originale, seed=0)

    r_originale = originale["close"].pct_change().dropna()
    r_mescolata = mescolata["close"].pct_change().dropna()

    # La memoria fra un giorno e il successivo deve sparire...
    assert r_originale.autocorr(lag=1) > 0.3
    assert abs(r_mescolata.autocorr(lag=1)) < 0.15
    # ...ma volatilità e ampiezza dei movimenti restano identiche: è la stessa
    # moneta, lanciata in un altro ordine.
    assert r_mescolata.std() == pytest.approx(r_originale.std(), rel=1e-9)
    assert sorted(r_mescolata.round(9)) == sorted(r_originale.round(9))


def test_mescolare_mantiene_indice_colonne_e_forma_delle_barre() -> None:
    originale = _serie_con_tendenza(n=200)
    mescolata = mescola_serie(originale, seed=3)

    assert list(mescolata.index) == list(originale.index)
    assert {"open", "high", "low", "close", "volume"} <= set(mescolata.columns)
    # Massimi sopra le chiusure e minimi sotto: le barre restano plausibili,
    # altrimenti gli indicatori su massimi e minimi lavorerebbero su spazzatura.
    assert (mescolata["high"] >= mescolata["close"]).all()
    assert (mescolata["low"] <= mescolata["close"]).all()


def test_mescolare_e_ripetibile() -> None:
    data = _serie_con_tendenza(n=200)
    pd.testing.assert_frame_equal(mescola_serie(data, seed=7), mescola_serie(data, seed=7))
    assert not mescola_serie(data, seed=7)["close"].equals(mescola_serie(data, seed=8)["close"])


# ── Il confronto col caso ────────────────────────────────────────────────────

def test_non_si_vince_se_la_fortuna_fa_altrettanto() -> None:
    esito = valuta_contro_il_caso(margine_vero_pct=8.0, margini_del_caso_pct=[7.5, 3.0, 9.0])

    assert esito.superato is False
    assert esito.margine_del_caso_pct == 9.0  # conta il meglio che ha fatto il caso
    assert "non c'è niente da cui fidarsi" in esito.verdetto


def test_si_vince_se_si_stacca_dal_caso() -> None:
    esito = valuta_contro_il_caso(margine_vero_pct=18.0, margini_del_caso_pct=[4.0, 2.0])

    assert esito.superato is True
    assert "punti in più di quanto si ottiene per caso" in esito.verdetto


def test_il_margine_deve_staccarsi_di_un_minimo() -> None:
    """Battere il caso per un decimo di punto non è battere il caso."""
    esito = valuta_contro_il_caso(
        margine_vero_pct=5.0 + MARGINE_SUL_CASO_MINIMO / 2, margini_del_caso_pct=[5.0]
    )
    assert esito.superato is False


def test_senza_prove_non_si_pronuncia() -> None:
    esito = valuta_contro_il_caso(margine_vero_pct=30.0, margini_del_caso_pct=[])

    assert esito.superato is False
    assert esito.prove == 0
    assert "non eseguita" in esito.verdetto


# ── Il comportamento nella ricerca vera ──────────────────────────────────────

@pytest.mark.lento
def test_su_un_mercato_senza_struttura_non_si_vince() -> None:
    """Il caso peggiore: rumore puro. Cercando fra migliaia di configurazioni
    qualcosa che sembra funzionare si trova sempre, ed è proprio quello che la
    prova del caso deve smascherare."""
    from trading_bot.application.strategy_search import run_strategy_search

    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, 600)))
    idx = pd.bdate_range("2021-01-04", periods=600)
    rumore = pd.DataFrame(
        {"open": close, "high": close * 1.006, "low": close * 0.994, "close": close,
         "volume": np.full(600, 1000.0)},
        index=idx,
    )

    res = run_strategy_search(
        data=rumore, symbol="RUMORE", fee_bps=0.0,
        strategy_ids=["sma_cross", "ema_cross", "rsi_mean_reversion"],
        prove_del_caso=3, max_workers=1,
    )

    assert res.prova_del_caso is not None
    assert res.prova_del_caso["superato"] is False
    assert res.tipo_vittoria == ""   # nessuna vittoria riconosciuta


@pytest.mark.lento
def test_su_un_mercato_con_tendenze_vere_si_vince() -> None:
    """Il controllo opposto: se la prova bocciasse anche una struttura vera
    sarebbe inutile, perché direbbe sempre di no."""
    from trading_bot.application.strategy_search import run_strategy_search

    res = run_strategy_search(
        data=_serie_con_tendenza(), symbol="TENDENZA", fee_bps=0.0,
        strategy_ids=["sma_cross", "ema_cross", "rsi_mean_reversion"],
        prove_del_caso=3, max_workers=1,
    )

    assert res.prova_del_caso["superato"] is True
    assert res.tipo_vittoria != ""
    assert res.prova_del_caso["margine_vero_pct"] > max(
        res.prova_del_caso["margini_del_caso_pct"]
    )


@pytest.mark.lento
def test_l_esito_arriva_fino_alla_scheda_del_mercato() -> None:
    """Regressione: la prova veniva calcolata ma si perdeva per strada, quindi
    l'utente non la vedeva mai."""
    from trading_bot.application.multi_search import run_multi_market_search

    dati = _serie_con_tendenza(n=500)
    result = run_multi_market_search(
        ["AAA"], interval="1d", fee_bps=0.0,
        strategy_ids=["sma_cross", "ema_cross"],
        prove_del_caso=2, max_workers=1,
        download_data=lambda symbol, start, end, interval: dati,
    )

    scheda = result.markets[0]
    assert scheda.prova_del_caso is not None
    assert "verdetto" in scheda.prova_del_caso
    assert scheda.prova_del_caso["prove"] == 2
