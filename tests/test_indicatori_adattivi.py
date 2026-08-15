"""Gli indicatori adattivi: la prima famiglia diversa da quelle a catalogo.

Non basta che i numeri escano: devono comportarsi come promesso. Una media
adattiva che non rallenta nel rumore è una media normale con più righe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.features import (
    efficienza_del_movimento,
    fisher,
    kama,
    momentum_normalizzato,
)


def _frame(chiusure: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=len(chiusure))
    close = pd.Series(chiusure, index=idx)
    return pd.DataFrame(
        {"open": close, "high": close * 1.005, "low": close * 0.995, "close": close}, index=idx
    )


def _zigzag(n: int = 120) -> pd.DataFrame:
    """Sale e scende sempre della stessa quantità: tanta strada, nessuna direzione."""
    return _frame([100.0 + (3.0 if i % 2 else -3.0) for i in range(n)])


def _tendenza(n: int = 120) -> pd.DataFrame:
    """Sale sempre della stessa quantità: strada e direzione coincidono."""
    return _frame([100.0 + 0.8 * i for i in range(n)])


# ── L'efficienza del movimento ───────────────────────────────────────────────

def test_efficienza_distingue_direzione_da_agitazione() -> None:
    assert efficienza_del_movimento(_zigzag()).iloc[-1] == pytest.approx(0.0, abs=0.01)
    assert efficienza_del_movimento(_tendenza()).iloc[-1] == pytest.approx(1.0, abs=0.01)


def test_efficienza_resta_fra_zero_e_uno() -> None:
    rng = np.random.default_rng(5)
    chiusure = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 300)))
    valori = efficienza_del_movimento(_frame(list(chiusure)))

    assert valori.min() >= 0.0 and valori.max() <= 1.0


# ── La media adattiva ────────────────────────────────────────────────────────

def test_la_kama_quasi_si_ferma_nel_rumore() -> None:
    """È il motivo per cui esiste: nel movimento senza direzione non insegue."""
    dati = _zigzag()
    linea = kama(dati)

    movimento_prezzo = dati["close"].diff().abs().tail(40).mean()
    movimento_media = linea.diff().abs().tail(40).mean()

    assert movimento_media < movimento_prezzo / 50, "la media insegue il rumore"


def test_la_kama_insegue_la_tendenza() -> None:
    """L'altra metà della promessa: quando il movimento è pulito non resta indietro."""
    dati = _tendenza()
    linea = kama(dati)

    movimento_prezzo = dati["close"].diff().abs().tail(40).mean()
    movimento_media = linea.diff().abs().tail(40).mean()

    assert movimento_media == pytest.approx(movimento_prezzo, rel=0.1)


def test_la_kama_e_piu_ferma_di_una_media_normale_sullo_stesso_periodo() -> None:
    """Il confronto va fatto su un cammino irregolare.

    Su uno zigzag perfettamente regolare anche la media semplice resta
    immobile — la media di cinque alti e cinque bassi non si sposta — e il
    confronto non direbbe niente su nessuna delle due.
    """
    rng = np.random.default_rng(7)
    dati = _frame(list(100 + np.cumsum(rng.normal(0.0, 1.0, 400))))

    adattiva = kama(dati, periodo=10)
    normale = dati["close"].rolling(10).mean()

    assert adattiva.diff().abs().mean() < normale.diff().abs().mean()


def test_la_kama_viene_attraversata_meno_spesso() -> None:
    """La conseguenza pratica: meno attraversamenti, meno operazioni inutili.

    Il confronto è alla pari — prezzo contro media, stesso periodo — perché
    confrontare "prezzo contro media" con "media contro media" misurerebbe
    tutt'altro.
    """
    rng = np.random.default_rng(7)
    dati = _frame(list(100 + np.cumsum(rng.normal(0.0, 1.0, 400))))

    def attraversamenti(linea):
        return int((dati["close"] > linea).astype(int).diff().abs().sum())

    assert attraversamenti(kama(dati, periodo=10)) < attraversamenti(
        dati["close"].rolling(10).mean()
    )


def test_la_kama_rifiuta_costanti_incoerenti() -> None:
    with pytest.raises(ValueError, match="veloce"):
        kama(_tendenza(), veloce=30, lenta=2)
    with pytest.raises(ValueError, match="periodo"):
        kama(_tendenza(), periodo=1)


# ── La trasformazione di Fisher ──────────────────────────────────────────────

def test_il_fisher_allarga_gli_estremi() -> None:
    """La posizione grezza sta schiacciata fra 0 e 1; dopo la trasformazione i
    bordi si allontanano e una svolta si distingue da un movimento qualsiasi."""
    rng = np.random.default_rng(3)
    chiusure = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 300)))
    dati = _frame(list(chiusure))

    trasformato = fisher(dati).dropna()

    assert trasformato.abs().max() > 1.5, "gli estremi non sono stati allargati"
    # Il grosso dei valori resta vicino allo zero: è compressione al centro e
    # allargamento ai bordi, non un ingrandimento uniforme.
    assert trasformato.abs().median() < trasformato.abs().quantile(0.95) / 2


def test_il_fisher_non_esplode_mai() -> None:
    """La trasformazione tende all'infinito ai bordi: senza il limite, un prezzo
    esattamente sul massimo della finestra produrrebbe infinito e da lì in poi
    ogni conto successivo sarebbe spazzatura."""
    salita = _frame([100.0 + i for i in range(200)])   # ogni barra è il nuovo massimo

    trasformato = fisher(salita).dropna()

    assert np.isfinite(trasformato).all()
    assert trasformato.abs().max() < 100


def test_il_fisher_rifiuta_un_periodo_inutile() -> None:
    with pytest.raises(ValueError, match="periodo"):
        fisher(_tendenza(), periodo=1)


# ── Il momentum normalizzato ─────────────────────────────────────────────────

def test_a_parita_di_salita_vince_chi_e_salito_piu_tranquillo() -> None:
    """È tutta la ragione di questo indicatore. Il rendimento nudo darebbe lo
    stesso voto ai due; qui il secondo deve valere di meno, perché per arrivare
    allo stesso punto ha fatto sudare chi lo teneva."""
    n = 200
    dritto = _frame([100.0 * (1.0 + 0.002) ** i for i in range(n)])
    scosso = _frame(
        [100.0 * (1.0 + 0.002) ** i * (1.06 if i % 2 else 0.94) for i in range(n)]
    )

    calmo = momentum_normalizzato(dritto, periodo=60).iloc[-1]
    agitato = momentum_normalizzato(scosso, periodo=60).iloc[-1]

    assert calmo > agitato * 3, (
        "due mercati arrivati allo stesso punto prendono voti simili: la "
        "normalizzazione non sta facendo niente"
    )


def test_durante_l_avvio_dice_non_lo_so_e_non_zero() -> None:
    """"Non c'è ancora abbastanza storia" e "è fermo" sono cose diverse: se
    l'avvio valesse zero, un mercato di cui non si sa niente entrerebbe in
    classifica a metà gruppo invece di restarne fuori."""
    dati = _frame([100.0 + 0.5 * i for i in range(200)])

    valori = momentum_normalizzato(dati, periodo=60, finestra_scosse=60)

    assert valori.iloc[:60].isna().all()
    assert valori.iloc[-1] == valori.iloc[-1]  # non è NaN


def test_il_momentum_rifiuta_finestre_senza_senso() -> None:
    dati = _tendenza()
    with pytest.raises(ValueError, match="periodo"):
        momentum_normalizzato(dati, periodo=1)
    with pytest.raises(ValueError, match="scosse"):
        momentum_normalizzato(dati, finestra_scosse=1)


# ── Le strategie che li usano ────────────────────────────────────────────────

def test_la_strategia_adattiva_produce_un_segnale_valido() -> None:
    """La strategia nuova deve stare nelle regole di tutte le altre."""
    from trading_bot.strategies import build_strategy_signal

    rng = np.random.default_rng(7)
    dati = _frame(list(100 + np.cumsum(rng.normal(0.0, 1.0, 400))))

    solo_rialzo = build_strategy_signal(
        strategy_id="kama_trend", data=dati, parameters={"periodo": 10, "veloce": 2, "lenta": 30}
    )
    con_ribasso = build_strategy_signal(
        strategy_id="kama_trend", data=dati, parameters={"periodo": 10, "veloce": 2, "lenta": 30},
        consenti_short=True,
    )

    assert set(np.unique(solo_rialzo.to_numpy())) <= {0.0, 1.0}
    assert set(np.unique(con_ribasso.to_numpy())) <= {-1.0, 0.0, 1.0}
    assert (con_ribasso < 0).any(), "col consenso non va mai al ribasso"
