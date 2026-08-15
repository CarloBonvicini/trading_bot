"""I conti del portafoglio tornano? Tre domande a cui si deve poter dire di no.

1. Con **un mercato solo** il motore di portafoglio deve dare lo stesso identico
   risultato del motore di sempre. Se non lo dà, non sappiamo quale dei due
   credere e ogni numero successivo è aria.
2. Con **due mercati identici** deve dare lo stesso risultato di uno solo:
   dividere i soldi fra due copie della stessa cosa non è diversificare, e se il
   risultato migliorasse vorrebbe dire che ci siamo messi della leva addosso
   senza accorgercene.
3. Con **due mercati che crollano in momenti diversi** il calo peggiore deve
   essere sensibilmente più contenuto di quello di entrambi. È l'unico motivo
   per cui i portafogli esistono.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest import run_backtest
from trading_bot.portafoglio import (
    MAI,
    OGNI_BARRA,
    QUOTA_FISSA,
    QUOTA_FRA_SCELTI,
    esegui_portafoglio,
    quanto_si_muovono_insieme,
)


# ── Strumenti dei test ───────────────────────────────────────────────────────

def _ohlcv(chiusure: np.ndarray, inizio: str = "2021-01-04") -> pd.DataFrame:
    indice = pd.bdate_range(inizio, periods=len(chiusure))
    return pd.DataFrame(
        {
            "open": chiusure,
            "high": chiusure * 1.01,
            "low": chiusure * 0.99,
            "close": chiusure,
            "volume": np.full(len(chiusure), 1000.0),
        },
        index=indice,
    )


def _cammino(seed: int, n: int = 400, deriva: float = 0.0004, rumore: float = 0.011):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(deriva, rumore, n)))


def _con_crollo(chiusure: np.ndarray, *, da: int, quanto: float = 0.35,
                durata: int = 40) -> np.ndarray:
    """Un crollo che poi rientra: scende di ``quanto`` e risale da dove era.

    Un crollo permanente non serve a questo test. Due mercati che perdono per
    sempre il 35% in momenti diversi fanno un portafoglio che perde comunque il
    35% in due tempi: la discesa è la somma, non il massimo, e la diversificazione
    sembrerebbe non funzionare pur essendo il motore corretto.
    """
    colpite = chiusure.copy()
    meta = durata // 2
    colpite[da:da + meta] *= np.linspace(1.0, 1.0 - quanto, meta)
    colpite[da + meta:da + durata] *= np.linspace(1.0 - quanto, 1.0, durata - meta)
    return colpite


def _segnale_incrocio(dati: pd.DataFrame, veloce: int = 20, lento: int = 50) -> pd.Series:
    chiuse = dati["close"]
    return pd.Series(
        np.where(chiuse.rolling(veloce).mean() > chiuse.rolling(lento).mean(), 1.0, 0.0),
        index=dati.index,
    )


def _calo_peggiore(curva: pd.Series) -> float:
    return float((curva / curva.cummax() - 1).min()) * 100


# ── Criterio 1: un mercato solo ──────────────────────────────────────────────

@pytest.mark.parametrize("allocazione", [QUOTA_FRA_SCELTI, QUOTA_FISSA])
@pytest.mark.parametrize(
    "soglie", [(None, None), (3.0, 6.0)], ids=["senza soglie", "con stop e target"]
)
def test_un_mercato_solo_da_lo_stesso_risultato_del_motore_di_sempre(
    allocazione: str, soglie: tuple[float | None, float | None]
) -> None:
    """Il test di coerenza: se i conti non tornano qui, non tornano da nessuna
    parte. Confronto riga per riga sul riepilogo, non a campione."""
    sl, tp = soglie
    dati = _ohlcv(_cammino(7))
    segnale = _segnale_incrocio(dati)

    singolo = run_backtest(
        dati, segnale, initial_capital=10_000.0, fee_bps=5.0, slippage_bps=2.0,
        sl_pct=sl, tp_pct=tp,
    )
    insieme = esegui_portafoglio(
        {"SOLO": dati}, {"SOLO": segnale}, initial_capital=10_000.0, fee_bps=5.0,
        slippage_bps=2.0, sl_pct=sl, tp_pct=tp, allocazione=allocazione,
    )

    diverse = {
        chiave: (valore, insieme.summary.get(chiave))
        for chiave, valore in singolo.summary.items()
        if insieme.summary.get(chiave) != valore
    }
    assert not diverse, f"il portafoglio a un mercato non coincide col motore singolo: {diverse}"

    # Non basta che coincidano i numeri finali: deve coincidere tutto il percorso.
    for colonna in ("equity", "drawdown", "strategy_return", "benchmark_equity",
                    "transaction_cost_amount"):
        pd.testing.assert_series_equal(
            singolo.equity_curve[colonna], insieme.equity_curve[colonna],
            check_names=False, obj=colonna,
        )

    pd.testing.assert_frame_equal(
        singolo.trades, insieme.trades.drop(columns=["symbol"]), check_like=False,
    )


# ── Criterio 2: due mercati identici ─────────────────────────────────────────

@pytest.mark.parametrize("allocazione", [QUOTA_FRA_SCELTI, QUOTA_FISSA])
def test_due_mercati_identici_danno_lo_stesso_risultato_di_uno(allocazione: str) -> None:
    """Comprare due volte la stessa cosa non è diversificare. Se il risultato
    cambiasse, il capitale impegnato sarebbe il doppio di quello che c'è."""
    dati = _ohlcv(_cammino(7))
    segnale = _segnale_incrocio(dati)

    uno = esegui_portafoglio({"A": dati}, {"A": segnale}, allocazione=allocazione)
    due = esegui_portafoglio(
        {"A": dati, "B": dati.copy()},
        {"A": segnale, "B": segnale.copy()},
        allocazione=allocazione,
    )

    for chiave in ("final_equity", "max_drawdown_pct", "total_return_pct", "sharpe_ratio",
                   "fees_paid", "slippage_paid", "benchmark_return_pct", "excess_return_pct"):
        assert due.summary[chiave] == uno.summary[chiave], chiave

    # E il capitale impegnato deve restare quello di prima, non il doppio.
    assert due.summary["capitale_impegnato_pct"] == uno.summary["capitale_impegnato_pct"]
    # Le operazioni invece raddoppiano: sono davvero due mercati, e su ognuno si
    # è comprato e venduto per davvero.
    assert due.summary["trade_count"] == 2 * uno.summary["trade_count"]


@pytest.mark.parametrize("quanti", [2, 5, 12])
@pytest.mark.parametrize("allocazione", [QUOTA_FRA_SCELTI, QUOTA_FISSA])
def test_il_capitale_impegnato_non_supera_mai_il_capitale(
    quanti: int, allocazione: str
) -> None:
    """L'invariante da cui dipende tutto il resto: il capitale è **uno**.

    Se saltasse, ogni mercato in più aggiungerebbe leva di nascosto e i risultati
    migliorerebbero senza che nessuno abbia messo altri soldi. Provato con
    segnali casuali di ogni convinzione e verso, barra per barra: non basta che
    la media stia sotto, deve starci ogni singola barra.
    """
    rng = np.random.default_rng(21)
    mercati, segnali = {}, {}
    for i in range(quanti):
        dati = _ohlcv(_cammino(100 + i, n=200))
        mercati[f"M{i}"] = dati
        segnali[f"M{i}"] = pd.Series(
            rng.choice([-1.0, -0.4, 0.0, 0.3, 1.0], size=len(dati)), index=dati.index
        )

    esito = esegui_portafoglio(mercati, segnali, allocazione=allocazione, fee_bps=0.0)
    impegnato = esito.pesi.abs().sum(axis=1)

    assert float(impegnato.max()) <= 1.0 + 1e-9, (
        f"in almeno una barra il capitale impegnato è {impegnato.max():.3f} volte quello "
        "disponibile: è leva arrivata di nascosto"
    )


# ── Criterio 3: due crolli in momenti diversi ────────────────────────────────

def test_due_crolli_sfasati_fanno_meno_male_di_ciascuno_dei_due() -> None:
    """Il motivo per cui i portafogli esistono.

    Il criterio chiede solo "meno di entrambi", ma una disuguaglianza rispettata
    per un centesimo di punto sarebbe un test verde che non dimostra niente: con
    due mercati molto correlati passa comunque. Qui si pretende un margine
    dichiarato, su mercati indipendenti.
    """
    a, b = _ohlcv(_con_crollo(_cammino(11, deriva=0.0004, rumore=0.006), da=80)), _ohlcv(
        _con_crollo(_cammino(23, deriva=0.0004, rumore=0.006), da=240)
    )
    sempre_dentro = pd.Series(1.0, index=a.index)

    solo_a = esegui_portafoglio({"A": a}, {"A": sempre_dentro}, fee_bps=0.0)
    solo_b = esegui_portafoglio({"B": b}, {"B": sempre_dentro}, fee_bps=0.0)
    insieme = esegui_portafoglio(
        {"A": a, "B": b}, {"A": sempre_dentro, "B": sempre_dentro.copy()}, fee_bps=0.0,
    )

    peggiore_da_solo = max(
        solo_a.summary["max_drawdown_pct"], solo_b.summary["max_drawdown_pct"]
    )
    margine = insieme.summary["max_drawdown_pct"] - peggiore_da_solo

    # Soglia scelta misurando: su cinque coppie di mercati indipendenti il
    # margine sta fra +12,9 e +15,6 punti. Otto lascia spazio senza permettere
    # a una riduzione simbolica di far passare il test.
    assert margine > 8.0, (
        f"il portafoglio scende {insieme.summary['max_drawdown_pct']}%, il meno peggio "
        f"dei due {peggiore_da_solo}%: margine {margine:+.2f} punti, troppo poco per "
        "dire che dividere è servito"
    )
    # E il numero che spiega perché ha funzionato deve essere riportato.
    assert abs(insieme.summary["quanto_si_muovono_insieme"]) < 0.3


def test_mercati_che_si_muovono_insieme_non_riducono_il_dolore() -> None:
    """Il rovescio della medaglia, che rende il test precedente non banale:
    venti titoli che si muovono insieme sono un titolo solo comprato venti
    volte, e il calo peggiore resta quello."""
    base = _cammino(5)
    a, b = _ohlcv(base), _ohlcv(base * 1.5)
    sempre_dentro = pd.Series(1.0, index=a.index)

    solo_a = esegui_portafoglio({"A": a}, {"A": sempre_dentro}, fee_bps=0.0)
    insieme = esegui_portafoglio(
        {"A": a, "B": b}, {"A": sempre_dentro, "B": sempre_dentro.copy()}, fee_bps=0.0,
    )

    assert insieme.summary["quanto_si_muovono_insieme"] == pytest.approx(1.0, abs=0.001)
    assert insieme.summary["max_drawdown_pct"] == pytest.approx(
        solo_a.summary["max_drawdown_pct"], abs=0.01
    )


# ── I costi non si perdono per strada ────────────────────────────────────────

def test_ogni_spostamento_di_peso_si_paga() -> None:
    """Entrare su un secondo mercato riduce la fetta del primo: quella riduzione
    è una vendita, e va pagata come tale."""
    dati_a = _ohlcv(_cammino(2))
    dati_b = _ohlcv(_cammino(3))
    # A sempre dentro; B entra a metà strada e costringe A a farsi da parte.
    sempre = pd.Series(1.0, index=dati_a.index)
    a_meta = pd.Series(0.0, index=dati_b.index)
    a_meta.iloc[200:] = 1.0

    insieme = esegui_portafoglio(
        {"A": dati_a, "B": dati_b}, {"A": sempre, "B": a_meta},
        fee_bps=10.0, slippage_bps=5.0,
    )

    assert insieme.summary["fees_paid"] > 0
    assert insieme.summary["slippage_paid"] > 0
    # Commissioni e slippage restano voci distinte e in rapporto ai loro bps.
    assert insieme.summary["fees_paid"] == pytest.approx(
        insieme.summary["slippage_paid"] * 2, rel=0.01
    )
    assert insieme.summary["trading_costs_paid"] == pytest.approx(
        insieme.summary["fees_paid"] + insieme.summary["slippage_paid"], abs=0.02
    )


def test_la_convinzione_arriva_fino_ai_pesi() -> None:
    """Il segno è la direzione, il valore assoluto è quanto capitale impegnare:
    la fase 2 non deve fermarsi alla porta del portafoglio."""
    dati_a = _ohlcv(_cammino(2))
    dati_b = _ohlcv(_cammino(3))
    convinto = pd.Series(1.0, index=dati_a.index)
    tiepido = pd.Series(0.4, index=dati_b.index)

    esito = esegui_portafoglio(
        {"A": dati_a, "B": dati_b}, {"A": convinto, "B": tiepido}, fee_bps=0.0,
    )

    # Due mercati a mercato: mezzo capitale per uno, ma B ne usa solo il 40%.
    assert esito.pesi["A"].iloc[-1] == pytest.approx(0.5)
    assert esito.pesi["B"].iloc[-1] == pytest.approx(0.2)
    # Restare a metà convinzione è comunque un'operazione: non sparisce dal conto.
    assert esito.summary["trade_count"] == 2


def test_il_ribasso_su_un_mercato_non_annulla_il_rialzo_sull_altro() -> None:
    """Metà al rialzo e metà al ribasso è capitale tutto impegnato, non zero: la
    somma netta direbbe zero e nasconderebbe il rischio vero."""
    dati_a = _ohlcv(_cammino(2))
    dati_b = _ohlcv(_cammino(3))
    su = pd.Series(1.0, index=dati_a.index)
    giu = pd.Series(-1.0, index=dati_b.index)

    esito = esegui_portafoglio({"A": dati_a, "B": dati_b}, {"A": su, "B": giu}, fee_bps=0.0)

    assert esito.summary["capitale_impegnato_pct"] == pytest.approx(100.0, abs=0.5)
    assert esito.summary["exposure_pct"] == pytest.approx(0.0, abs=0.5)


# ── Il metro di paragone ─────────────────────────────────────────────────────

def test_il_confronto_e_il_portafoglio_noioso_non_un_titolo_solo() -> None:
    """Con più mercati il paragone deve essere "li divido tutti e sto fermo",
    non il comprare-e-tenere del singolo titolo: quello farebbe sembrare la
    strategia migliore o peggiore di quanto sia."""
    sale = _ohlcv(_cammino(4, deriva=0.0012))
    scende = _ohlcv(_cammino(9, deriva=-0.0008))
    sempre = pd.Series(1.0, index=sale.index)

    esito = esegui_portafoglio(
        {"SU": sale, "GIU": scende}, {"SU": sempre, "GIU": sempre.copy()},
        fee_bps=0.0, ribilancia_ogni=MAI,
    )

    resa_su = float(sale["close"].iloc[-1] / sale["close"].iloc[0] - 1) * 100
    resa_giu = float(scende["close"].iloc[-1] / scende["close"].iloc[0] - 1) * 100
    assert resa_giu < esito.summary["benchmark_return_pct"] < resa_su
    # Comprare i due all'inizio e non toccarli più *è* il portafoglio noioso:
    # se il margine non fosse zero, uno dei due conti sarebbe sbagliato.
    assert esito.summary["excess_return_pct"] == pytest.approx(0.0, abs=0.01)


# ── Ribilanciare è una scelta, e si paga ─────────────────────────────────────

def test_ricalcolare_i_pesi_a_ogni_barra_e_gia_un_ribilanciamento() -> None:
    """La differenza fra "sto fermo" e "rimetto in riga le quote ogni giorno"
    non è un dettaglio di implementazione: sono due strategie diverse e danno
    risultati diversi. Se coincidessero, il ribilanciamento non starebbe
    avvenendo davvero da nessuna delle due parti."""
    sale = _ohlcv(_cammino(4, deriva=0.0012))
    scende = _ohlcv(_cammino(9, deriva=-0.0008))
    sempre = pd.Series(1.0, index=sale.index)
    mercati = {"SU": sale, "GIU": scende}
    segnali = {"SU": sempre, "GIU": sempre.copy()}

    fermo = esegui_portafoglio(mercati, segnali, fee_bps=0.0, ribilancia_ogni=MAI)
    ogni_mese = esegui_portafoglio(mercati, segnali, fee_bps=0.0, ribilancia_ogni="M")
    ogni_barra = esegui_portafoglio(mercati, segnali, fee_bps=0.0, ribilancia_ogni=OGNI_BARRA)

    assert fermo.summary["total_return_pct"] != ogni_mese.summary["total_return_pct"]
    assert fermo.summary["ribilanciamenti"] < ogni_mese.summary["ribilanciamenti"]
    assert ogni_mese.summary["ribilanciamenti"] < ogni_barra.summary["ribilanciamenti"]
    # Un mese di borsa sono circa 21 barre: su ~400 barre fanno una ventina di
    # ribilanciamenti, non uno né quattrocento.
    assert 15 <= ogni_mese.summary["ribilanciamenti"] <= 25


def test_il_ribilanciamento_paga_le_commissioni() -> None:
    """Vendere un po' di quello che è salito per ricomprare quello che è sceso
    costa. È proprio il costo che rende la diversificazione meno gratuita di
    come appare, quindi è quello che sarebbe più comodo perdere per strada."""
    sale = _ohlcv(_cammino(4, deriva=0.0012))
    scende = _ohlcv(_cammino(9, deriva=-0.0008))
    sempre = pd.Series(1.0, index=sale.index)
    mercati = {"SU": sale, "GIU": scende}
    segnali = {"SU": sempre, "GIU": sempre.copy()}

    fermo = esegui_portafoglio(mercati, segnali, fee_bps=10.0, ribilancia_ogni=MAI)
    ogni_mese = esegui_portafoglio(mercati, segnali, fee_bps=10.0, ribilancia_ogni="M")

    # Chi sta fermo paga solo l'acquisto iniziale.
    assert ogni_mese.summary["fees_paid"] > fermo.summary["fees_paid"] * 1.5
    assert fermo.summary["fees_paid"] > 0


def test_ribilanciare_non_puo_far_sparire_le_uscite() -> None:
    """Se un segnale dice di uscire, si esce: il calendario vale per rimettere
    in riga le quote, non per restare dentro qualcosa che si voleva chiudere."""
    dati_a = _ohlcv(_cammino(2))
    dati_b = _ohlcv(_cammino(3))
    sempre = pd.Series(1.0, index=dati_a.index)
    esce_a_meta = pd.Series(1.0, index=dati_b.index)
    esce_a_meta.iloc[200:] = 0.0

    esito = esegui_portafoglio(
        {"A": dati_a, "B": dati_b}, {"A": sempre, "B": esce_a_meta},
        fee_bps=0.0, ribilancia_ogni="Q",   # ribilanciamento raro, di proposito
    )

    # Dalla barra dell'uscita in poi su B non c'è più un euro.
    assert float(esito.pesi["B"].iloc[210:].abs().max()) == 0.0


def test_un_calendario_inventato_non_passa() -> None:
    dati = _ohlcv(_cammino(2, n=100))
    with pytest.raises(ValueError, match="Ribilanciamento sconosciuto"):
        esegui_portafoglio(
            {"A": dati}, {"A": pd.Series(1.0, index=dati.index)}, ribilancia_ogni="ogni_tanto",
        )


# ── Le richieste impossibili si fermano subito ───────────────────────────────

def test_i_calendari_che_non_si_incontrano_non_passano_in_silenzio() -> None:
    """Due mercati senza barre in comune darebbero un portafoglio vuoto e un
    risultato inventato: meglio un errore."""
    a = _ohlcv(_cammino(2, n=100), inizio="2021-01-04")
    b = _ohlcv(_cammino(3, n=100), inizio="2023-01-02")

    with pytest.raises(ValueError, match="barre in comune"):
        esegui_portafoglio(
            {"A": a, "B": b},
            {"A": pd.Series(1.0, index=a.index), "B": pd.Series(1.0, index=b.index)},
        )


def test_un_segnale_mancante_non_diventa_zero_di_nascosto() -> None:
    dati = _ohlcv(_cammino(2, n=100))
    with pytest.raises(ValueError, match="Manca il segnale"):
        esegui_portafoglio({"A": dati, "B": dati.copy()}, {"A": pd.Series(1.0, index=dati.index)})


def test_una_politica_inventata_non_passa() -> None:
    dati = _ohlcv(_cammino(2, n=100))
    with pytest.raises(ValueError, match="allocazione sconosciuta"):
        esegui_portafoglio(
            {"A": dati}, {"A": pd.Series(1.0, index=dati.index)}, allocazione="a_caso",
        )


def test_quanto_si_muovono_insieme_con_un_mercato_solo() -> None:
    dati = _ohlcv(_cammino(2, n=100))
    assert quanto_si_muovono_insieme(dati[["close"]]) == 0.0
