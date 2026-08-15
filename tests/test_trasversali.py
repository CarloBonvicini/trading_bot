"""Le strategie che ordinano i mercati fra loro.

Una classifica è il posto più comodo dove nascondere il futuro: basta ordinare
sull'intera serie invece che barra per barra e il risultato diventa splendido e
falso, senza che nessun errore venga sollevato. Qui si tronca e si stravolge il
futuro, come per le strategie a mercato singolo, ma su tutti i mercati insieme.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.portafoglio import esegui_portafoglio
from trading_bot.trasversali import (
    FUNZIONI_TRASVERSALI,
    SPEC_TRASVERSALI,
    classifica_di_forza,
    costruisci_segnali_trasversali,
    forza_relativa,
)

TUTTE = sorted(SPEC_TRASVERSALI)
TAGLIO = 320


def _mercato(n: int = 500, seed: int = 11, deriva: float = 0.0004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    chiusure = 100 * np.exp(np.cumsum(rng.normal(deriva, 0.014, n)))
    idx = pd.bdate_range("2021-01-04", periods=n)
    close = pd.Series(chiusure, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "volume": pd.Series(rng.integers(1000, 5000, n).astype(float), index=idx),
        }
    )


def _gruppo(quanti: int = 6, n: int = 500, derive: list[float] | None = None) -> dict:
    derive = derive or [0.0004] * quanti
    return {
        f"M{i}": _mercato(n=n, seed=40 + i, deriva=derive[i % len(derive)])
        for i in range(quanti)
    }


# ── Il futuro non si vede ────────────────────────────────────────────────────

@pytest.mark.parametrize("strategy_id", TUTTE)
@pytest.mark.parametrize("consenti_short", [False, True])
def test_il_passato_non_cambia_se_cambia_il_futuro(
    strategy_id: str, consenti_short: bool
) -> None:
    completi = _gruppo()
    troncati = {nome: dati.iloc[:TAGLIO] for nome, dati in completi.items()}
    parametri = SPEC_TRASVERSALI[strategy_id].defaults()

    intero = costruisci_segnali_trasversali(
        strategy_id, completi, parametri, consenti_short=consenti_short
    ).iloc[:TAGLIO]
    parziale = costruisci_segnali_trasversali(
        strategy_id, troncati, parametri, consenti_short=consenti_short
    )

    differenze = int((intero.to_numpy() != parziale.to_numpy()).sum())
    assert differenze == 0, (
        f"{strategy_id}: {differenze} valori cambiano quando si aggiunge il futuro. "
        "La classifica sta usando dati che a quel momento non esistevano."
    )


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_stravolgere_il_futuro_non_tocca_il_passato(strategy_id: str) -> None:
    """Più severo del troncamento: il futuro c'è, ma è un altro. Una classifica
    calcolata sull'intera serie si sposterebbe, e con essa tutto il passato."""
    completi = _gruppo()
    stravolti = {}
    for posto, (nome, dati) in enumerate(completi.items()):
        copia = dati.copy()
        coda = copia.index[TAGLIO:]
        # Ogni mercato viene stravolto in modo diverso: così cambia anche
        # l'ordine relativo, che è quello che questa famiglia guarda.
        fattore = pd.Series(np.linspace(1.0, 1.0 + posto, len(coda)), index=coda)
        for colonna in ("open", "high", "low", "close"):
            copia.loc[coda, colonna] = copia.loc[coda, colonna] * fattore
        stravolti[nome] = copia

    parametri = SPEC_TRASVERSALI[strategy_id].defaults()
    originale = costruisci_segnali_trasversali(strategy_id, completi, parametri).iloc[:TAGLIO]
    con_altro_futuro = costruisci_segnali_trasversali(
        strategy_id, stravolti, parametri
    ).iloc[:TAGLIO]

    differenze = int((originale.to_numpy() != con_altro_futuro.to_numpy()).sum())
    assert differenze == 0, (
        f"{strategy_id}: {differenze} valori del passato cambiano se si stravolge il "
        "futuro. Da qualche parte la classifica guarda avanti."
    )


def test_il_controllo_riconosce_una_classifica_che_bara() -> None:
    """Un test che non fallisce mai non protegge niente: qui una classifica
    costruita di proposito sull'intera serie deve essere smascherata."""
    completi = _gruppo()

    def classifica_che_bara(mercati: dict) -> pd.DataFrame:
        # L'errore elegante: la forza di ogni mercato viene riportata su una
        # scala comune usando media e dispersione dell'INTERA serie. Sembra una
        # normalizzazione innocua, e invece ogni valore del passato dipende da
        # com'e' andato il futuro.
        forze = {}
        for nome, dati in mercati.items():
            grezza = dati["close"].pct_change(60)
            forze[nome] = (grezza - grezza.mean()) / (grezza.std(ddof=0) or 1.0)
        frame = pd.DataFrame(forze)
        return (frame.rank(axis=1, ascending=False, method="first") <= 1).astype(float)

    troncati = {nome: dati.iloc[:TAGLIO] for nome, dati in completi.items()}
    intero = classifica_che_bara(completi).iloc[:TAGLIO]
    parziale = classifica_che_bara(troncati)

    assert int((intero.to_numpy() != parziale.to_numpy()).sum()) > 0, (
        "il controllo non si accorge nemmeno di una classifica costruita sul futuro"
    )


# ── Compra i più forti fra tanti ─────────────────────────────────────────────

@pytest.mark.parametrize("quanti", [1, 3, 5])
def test_ne_tiene_esattamente_quanti_gliene_hai_chiesti(quanti: int) -> None:
    """"Compra i tre più forti fra venti" deve voler dire tre, non due né
    quattro — a parte l'avvio, quando la storia non basta ancora."""
    mercati = _gruppo(quanti=8)
    segnali = forza_relativa(mercati, periodo=60, quanti=quanti, solo_se_sale=0)

    tenuti = (segnali != 0).sum(axis=1)
    a_regime = tenuti.iloc[200:]
    assert set(a_regime.unique()) == {quanti}
    # Prima che ci sia storia a sufficienza non si compra niente.
    assert int(tenuti.iloc[0]) == 0


def test_sceglie_davvero_il_piu_forte() -> None:
    """Il test che dice se la classifica sta ordinando o mescolando: con un
    mercato che sale molto più degli altri, deve essere quello scelto.

    La soglia è misurata, non scelta a occhio. Con sei mercati, tirando a caso
    si prenderebbe quello giusto nel 17% delle barre; guardando 120 barre di
    storia si arriva al 96%. A 60 barre si ferma al 78%, e non è un difetto del
    codice: su finestre corte il rumore di cinque mercati supera spesso la
    tendenza vera del sesto. È il motivo per cui il valore predefinito è 120.
    """
    mercati = _gruppo(quanti=5, derive=[0.0001])
    mercati["VINCE"] = _mercato(n=500, seed=99, deriva=0.004)

    segnali = forza_relativa(mercati, periodo=120, quanti=1, solo_se_sale=0)
    scelte = segnali.iloc[240:].idxmax(axis=1)

    quota_vincente = float((scelte == "VINCE").mean())
    assert quota_vincente > 0.9, (
        f"il mercato che sale quaranta volte più degli altri è scelto solo nel "
        f"{quota_vincente:.0%} delle barre: la classifica non sta ordinando"
    )


def test_essere_il_meno_peggio_non_e_un_motivo_per_comprare() -> None:
    """Il primo di venti mercati che scendono tutti sta comunque scendendo:
    con "solo se sale" si resta in liquidità, che è una posizione.

    Misurato: senza il filtro si tengono sempre 2 mercati su 5, col filtro si
    scende a 0,17 — cioè quasi sempre fuori."""
    in_discesa = _gruppo(quanti=5, derive=[-0.002])

    con_filtro = forza_relativa(in_discesa, periodo=120, quanti=2, solo_se_sale=1)
    senza_filtro = forza_relativa(in_discesa, periodo=120, quanti=2, solo_se_sale=0)

    assert float((con_filtro != 0).sum(axis=1).iloc[240:].mean()) < 0.5
    assert float((senza_filtro != 0).sum(axis=1).iloc[240:].mean()) == 2.0


def test_al_ribasso_vende_i_piu_deboli_non_l_opposto_dell_uscita() -> None:
    """La regola al ribasso è scritta apposta: si vendono gli ultimi della
    classifica. Comprare i forti e vendere i deboli è una cosa sola coerente."""
    mercati = _gruppo(quanti=8, derive=[0.003, 0.002, 0.0005, 0.0, -0.0005, -0.002, -0.003, 0.001])

    segnali = forza_relativa(mercati, periodo=60, quanti=2, solo_se_sale=0, consenti_short=True)
    a_regime = segnali.iloc[200:]

    assert (a_regime == 1.0).sum(axis=1).eq(2).all()
    assert (a_regime == -1.0).sum(axis=1).eq(2).all()
    # Nessun mercato può essere comprato e venduto nella stessa barra.
    assert not ((a_regime == 1.0) & (a_regime == -1.0)).any().any()


def test_con_pochi_mercati_non_si_compra_e_vende_la_stessa_cosa() -> None:
    """Con quattro mercati e "i due più forti", i due più deboli sarebbero gli
    stessi due: il ribasso deve tacere invece di contraddirsi."""
    mercati = _gruppo(quanti=4)

    segnali = forza_relativa(mercati, periodo=60, quanti=2, solo_se_sale=0, consenti_short=True)

    assert (segnali == -1.0).sum().sum() == 0


def test_il_ribasso_resta_una_scelta_esplicita() -> None:
    mercati = _gruppo(quanti=8)
    senza = costruisci_segnali_trasversali(
        "forza_relativa", mercati, SPEC_TRASVERSALI["forza_relativa"].defaults()
    )
    assert (senza < 0).sum().sum() == 0


def test_a_parita_di_forza_la_scelta_e_sempre_la_stessa() -> None:
    """Due mercati identici hanno la stessa forza: senza una regola sulle parità
    due esecuzioni della stessa ricerca darebbero risultati diversi."""
    base = _mercato(n=300, seed=7)
    mercati = {"A": base, "B": base.copy(), "C": _mercato(n=300, seed=8)}

    primo = forza_relativa(mercati, periodo=60, quanti=1, solo_se_sale=0)
    secondo = forza_relativa(mercati, periodo=60, quanti=1, solo_se_sale=0)

    pd.testing.assert_frame_equal(primo, secondo)


# ── Sul motore di portafoglio ────────────────────────────────────────────────

def test_i_tre_piu_forti_fra_venti_stanno_dentro_un_capitale_solo() -> None:
    """La frase che tutta la fase 4 esiste per rendere esprimibile — e il
    capitale resta uno."""
    mercati = _gruppo(quanti=20, n=600)
    segnali = forza_relativa(mercati, periodo=120, quanti=3, solo_se_sale=1)

    esito = esegui_portafoglio(
        mercati, {nome: segnali[nome] for nome in mercati},
        fee_bps=5.0, ribilancia_ogni="M",
    )

    assert float(esito.pesi.abs().sum(axis=1).max()) <= 1.0 + 1e-9
    assert esito.summary["mercati_count"] == 20
    assert esito.summary["mercati_insieme_massimo"] <= 3
    assert esito.summary["trade_count"] > 0


def test_la_classifica_puo_riusare_gli_indicatori_gia_calcolati() -> None:
    """Ritagliare i dati quando non serve darebbe un oggetto nuovo a ogni
    chiamata, e il registro — che riconosce i dati per identità — non potrebbe
    mai riusare niente. Nessuna contaminazione: il riuso resta possibile solo
    dentro un contesto aperto su quegli stessi identici dati."""
    from trading_bot.features import contesto_indicatori

    mercati = _gruppo(quanti=3, n=400)
    primo = next(iter(mercati.values()))

    with contesto_indicatori(primo) as contesto:
        for _ in range(4):
            classifica_di_forza(mercati, periodo=120)

    assert contesto.riusi > 0, "la classifica ricalcola ogni volta lo stesso indicatore"
    # Un solo mercato è quello del contesto: gli altri due devono restare fuori
    # dalla memoria, altrimenti si starebbero servendo valori di un altro mercato.
    assert contesto.calcoli == 1


def test_la_storia_rimescolata_non_eredita_la_forza_di_quella_vera() -> None:
    """L'invariante che rende la prova del caso una prova.

    La storia rimescolata ha lo **stesso identico indice** del mercato vero e le
    stesse colonne: se il registro riconoscesse i dati per indice o per forma
    invece che per identità, la classifica sui dati finti riceverebbe i valori
    di quelli veri e la prova del caso passerebbe sempre, senza mai fallire e
    senza mai segnalare niente.
    """
    from trading_bot.application.prova_del_caso import mescola_mercati
    from trading_bot.features import contesto_indicatori

    veri = _gruppo(quanti=3, n=400)
    finti = mescola_mercati(veri, seed=0)
    assert finti["M0"].index.equals(veri["M0"].index)   # l'inganno è possibile

    with contesto_indicatori(veri["M0"]):
        forza_vera = classifica_di_forza(veri, periodo=120)
        forza_finta = classifica_di_forza(finti, periodo=120)

    diverse = (
        forza_vera["M0"].dropna().to_numpy() != forza_finta["M0"].dropna().to_numpy()
    ).sum()
    assert diverse > 0, (
        "la classifica sulla storia rimescolata coincide con quella vera: da qualche "
        "parte si stanno riusando valori di un altro mercato"
    )


def test_la_classifica_lascia_fuori_chi_non_ha_abbastanza_storia() -> None:
    mercati = _gruppo(quanti=3, n=200)
    forza = classifica_di_forza(mercati, periodo=120)

    assert forza.iloc[:100].isna().all().all()
    assert forza.iloc[-1].notna().all()


def test_ogni_strategia_trasversale_ha_la_sua_funzione() -> None:
    assert set(SPEC_TRASVERSALI) == set(FUNZIONI_TRASVERSALI)


def test_chiedere_zero_mercati_non_passa() -> None:
    with pytest.raises(ValueError, match="almeno uno"):
        forza_relativa(_gruppo(quanti=3), quanti=0)
    with pytest.raises(ValueError, match="almeno un mercato"):
        forza_relativa({}, quanti=1)
