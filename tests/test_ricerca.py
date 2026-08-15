"""Cercare con un budget invece di provare tutto.

Il criterio del piano: su una griglia piccola, dove l'enumerazione totale è
ancora possibile, la ricerca guidata deve trovare lo stesso ottimo (o entro un
margine dichiarato) usando **una frazione** dei tentativi. Qui l'enumerazione
totale c'è davvero, quindi l'ottimo è noto e il confronto è verificabile.
"""
from __future__ import annotations

import numpy as np
import pytest

from trading_bot.ricerca import (
    BUDGET_PREDEFINITO,
    combinazioni,
    esplora,
    vicini,
)


def _griglia(quanti_parametri: int, valori_per_parametro: int) -> dict[str, list]:
    return {
        f"p{i}": list(range(valori_per_parametro))
        for i in range(quanti_parametri)
    }


def _collina(centro: dict) -> callable:
    """Un paesaggio con una cima sola: più ci si avvicina al centro, più si sale.

    Non è il mercato, ed è apposta: serve a verificare il **meccanismo**. Se la
    ricerca non trova la cima quando ce n'è una sola e liscia, non la troverà
    di certo in mezzo al rumore.
    """
    def punteggio(punto: dict) -> float:
        distanza = sum((punto[nome] - centro[nome]) ** 2 for nome in centro)
        return -float(distanza)
    return punteggio


def _accidentato(centro: dict, seme: int = 0) -> callable:
    """Come la collina, ma con dei sassi: cime finte sparse ovunque.

    È il caso che smaschera una ricerca che si incastra sul primo rilievo.
    """
    liscio = _collina(centro)

    def punteggio(punto: dict) -> float:
        rng = np.random.default_rng(abs(hash(tuple(sorted(punto.items())))) % (2**32) + seme)
        return liscio(punto) + float(rng.normal(0.0, 3.0))
    return punteggio


# ── Il criterio del piano ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "parametri,valori,budget,quota_massima_pct",
    [
        # I budget sono misurati, non scelti a occhio: sono il minimo che trova
        # la cima, con un po' di margine. Il punto da leggere è l'ultima
        # colonna — più lo spazio cresce, più sottile è la fetta che basta
        # guardare. Su 400 combinazioni serve un decimo dello spazio; su
        # 390.625 ne basta un millesimo. È la proprietà per cui questo modulo
        # esiste: rende possibili le strategie con sei, otto, dieci parametri,
        # che con l'enumerazione non si potevano nemmeno scrivere.
        (2, 20, 60, 15.0),        # 400 combinazioni
        (3, 12, 150, 9.0),        # 1.728
        (4, 8, 250, 6.5),         # 4.096
        (6, 6, 350, 1.0),         # 46.656
        (8, 5, 600, 0.2),         # 390.625
    ],
)
def test_trova_l_ottimo_guardando_una_frazione_dello_spazio(
    parametri: int, valori: int, budget: int, quota_massima_pct: float
) -> None:
    griglia = _griglia(parametri, valori)
    centro = {nome: valori // 3 for nome in griglia}
    valuta = _collina(centro)
    spazio = valori ** parametri

    esito = esplora(griglia, valuta, budget=budget)

    assert esito.parametri == centro, (
        f"su {spazio} combinazioni con {parametri} parametri la ricerca si è fermata a "
        f"{esito.parametri} invece che a {centro}"
    )
    assert esito.tentativi <= budget
    assert esito.spazio == spazio
    assert esito.quota_esplorata_pct <= quota_massima_pct
    assert not esito.esaustiva


def test_batte_la_griglia_grossolana_a_parita_di_tentativi() -> None:
    """Il confronto che giustifica l'esistenza di questo modulo: con lo stesso
    numero di tentativi, guardare intorno ai migliori arriva più in alto che
    spargere gli stessi punti in un reticolo e fermarsi lì."""
    griglia = _griglia(3, 15)
    centro = {"p0": 4, "p1": 11, "p2": 7}
    valuta = _accidentato(centro)
    budget = 120   # su 3375 combinazioni

    guidata = esplora(griglia, valuta, budget=budget)
    # La griglia grossolana: gli stessi punti, ma senza affinare.
    grossolana = esplora(
        griglia, valuta, budget=budget, quota_esplorazione=1.0,
    )

    assert guidata.punteggio > grossolana.punteggio


# ── Sotto una certa taglia non si approssima niente ──────────────────────────

def test_una_griglia_che_sta_nel_budget_viene_enumerata() -> None:
    """È ciò che tiene invariate tutte le ricerche che già costavano poco: se
    ci si sta, si guarda ovunque e la risposta è quella esatta di sempre."""
    griglia = _griglia(2, 8)     # 64 combinazioni
    centro = {"p0": 5, "p1": 2}

    esito = esplora(griglia, _collina(centro), budget=BUDGET_PREDEFINITO)

    assert esito.esaustiva
    assert esito.tentativi == 64
    assert esito.parametri == centro
    assert esito.quota_esplorata_pct == 100.0


# ── I vincoli fra parametri ──────────────────────────────────────────────────

def test_le_combinazioni_vietate_non_vengono_mai_provate() -> None:
    """Come `fast < slow`: una combinazione impossibile non deve costare un
    backtest, né comparire fra i tentativi."""
    griglia = {"veloce": list(range(10)), "lento": list(range(10))}
    ammessa = lambda p: p["veloce"] < p["lento"]  # noqa: E731
    provati: list[dict] = []

    def valuta(punto: dict) -> float:
        provati.append(punto)
        return float(punto["lento"] - punto["veloce"])

    esito = esplora(griglia, valuta, budget=30, ammessa=ammessa)

    assert all(p["veloce"] < p["lento"] for p in provati)
    assert esito.parametri["veloce"] < esito.parametri["lento"]


def test_una_griglia_tutta_vietata_lo_dice() -> None:
    griglia = {"a": [1, 2], "b": [1, 2]}
    with pytest.raises(ValueError, match="Nessuna combinazione valida"):
        esplora(griglia, lambda p: 1.0, ammessa=lambda p: False)


# ── Le combinazioni che non si possono valutare ──────────────────────────────

def test_una_combinazione_che_esplode_non_ferma_la_ricerca() -> None:
    griglia = _griglia(2, 10)
    centro = {"p0": 3, "p1": 6}
    liscio = _collina(centro)

    def valuta(punto: dict) -> float:
        if punto["p0"] == 7:
            raise RuntimeError("questa combinazione non si può calcolare")
        return liscio(punto)

    esito = esplora(griglia, valuta, budget=100)
    assert esito.parametri == centro


def test_una_combinazione_inerte_non_vince_per_inerzia() -> None:
    """Chi restituisce None non è "a punteggio zero": è non valutabile, e non
    deve scavalcare chi ha davvero fatto qualcosa, anche in perdita."""
    griglia = {"p0": list(range(10))}

    def valuta(punto: dict) -> float | None:
        return None if punto["p0"] < 9 else -50.0

    esito = esplora(griglia, valuta, budget=100)
    assert esito.parametri == {"p0": 9}
    assert esito.punteggio == -50.0


# ── Ripetibilità: due ricerche uguali danno lo stesso risultato ──────────────

def test_due_ricerche_uguali_danno_lo_stesso_risultato() -> None:
    """Senza questo, due lanci della stessa ricerca darebbero campioni diversi
    e nessun confronto — compreso quello con la fortuna — vorrebbe dire niente."""
    griglia = _griglia(3, 12)
    valuta = _accidentato({"p0": 2, "p1": 9, "p2": 5})

    primo = esplora(griglia, valuta, budget=100, seme=7)
    secondo = esplora(griglia, valuta, budget=100, seme=7)

    assert primo.parametri == secondo.parametri
    assert primo.punteggio == secondo.punteggio
    assert primo.tentativi == secondo.tentativi


def test_il_budget_viene_rispettato() -> None:
    griglia = _griglia(4, 10)   # 10.000 combinazioni
    contati: list[int] = []

    def valuta(punto: dict) -> float:
        contati.append(1)
        return float(-sum(punto.values()))

    for budget in (10, 50, 250):
        contati.clear()
        esito = esplora(griglia, valuta, budget=budget)
        assert len(contati) <= budget
        assert esito.tentativi <= budget
        assert esito.spazio == 10_000


def test_un_budget_impossibile_lo_dice() -> None:
    with pytest.raises(ValueError, match="almeno una combinazione"):
        esplora(_griglia(2, 3), lambda p: 1.0, budget=0)


# ── I pezzi ──────────────────────────────────────────────────────────────────

def test_i_vicini_sono_a_un_passo_e_una_dimensione_per_volta() -> None:
    griglia = {"a": [1, 2, 3], "b": [10, 20, 30]}

    intorno = vicini(griglia, {"a": 2, "b": 20})

    assert {tuple(sorted(v.items())) for v in intorno} == {
        (("a", 1), ("b", 20)), (("a", 3), ("b", 20)),
        (("a", 2), ("b", 10)), (("a", 2), ("b", 30)),
    }


def test_i_vicini_di_un_bordo_non_escono_dalla_griglia() -> None:
    griglia = {"a": [1, 2, 3]}
    assert vicini(griglia, {"a": 1}) == [{"a": 2}]
    assert vicini(griglia, {"a": 3}) == [{"a": 2}]


def test_i_vicini_di_un_valore_fuori_griglia_partono_dal_piu_simile() -> None:
    """Un parametro salvato da una ricerca vecchia può non stare nella griglia
    di oggi: meglio esplorare intorno al valore più vicino che rinunciare."""
    griglia = {"a": [10, 20, 30]}
    assert vicini(griglia, {"a": 21}) == [{"a": 10}, {"a": 30}]


def test_combinazioni_rispetta_i_vincoli() -> None:
    griglia = {"veloce": [1, 2, 3], "lento": [1, 2, 3]}
    tutte = combinazioni(griglia, ammessa=lambda p: p["veloce"] < p["lento"])
    assert len(tutte) == 3
