"""Rete di sicurezza per la rifattorizzazione degli indicatori.

Congela il comportamento **attuale** di tutte le strategie: per ognuna si
calcola il segnale su ogni combinazione della griglia, in entrambi i versi, e se
ne salva un'impronta in ``impronte_strategie.json``.

Serve a una cosa sola: permettere di spostare gli indicatori fuori dalle
strategie sapendo che nessun segnale è cambiato. Se dopo la rifattorizzazione
anche una sola barra di una sola combinazione vale un numero diverso,
l'impronta cambia e questo test fallisce indicando quale combinazione.

Va scritto e generato **prima** di toccare il codice, altrimenti congelerebbe
già l'eventuale errore introdotto.

Per rigenerare le impronte dopo una modifica *voluta* del comportamento:

    python tests/test_impronte_strategie.py --rigenera

È un gesto deliberato: se ti trovi a rigenerare per far passare il test, fermati
e chiediti se la modifica era davvero voluta.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.application.autosetting import AUTOSETTING_GRIDS
from trading_bot.strategies import (
    STRATEGY_SPECS,
    build_strategy_signal,
    validate_strategy_parameters,
)

IMPRONTE = Path(__file__).parent / "impronte_strategie.json"
BARRE = 500


def mercato_di_riferimento() -> pd.DataFrame:
    """Mercato costruito con una formula, non con numeri casuali.

    Deve dare esattamente la stessa serie su qualsiasi macchina e con qualsiasi
    versione delle librerie, altrimenti l'impronta cambierebbe da sola: per
    questo niente generatori casuali, solo funzioni chiuse.

    Contiene di proposito i casi che rompono gli indicatori:
    - due cicli sovrapposti, uno lungo e uno corto, per far scattare incroci e
      oscillatori a periodi diversi;
    - un crollo netto a metà, per i canali e le rotture;
    - un tratto quasi fermo, con oscillazioni minime, per i regimi di calma.

    Il tratto fermo è *quasi* fermo di proposito. Con un tratto perfettamente
    piatto la deviazione standard su vent'anni di barre identiche vale zero, e
    un confronto come "prezzo sotto la banda inferiore" diventa un pareggio
    esatto che si ribalta con l'ultimo bit di arrotondamento: l'impronta
    cambierebbe fra una versione di pandas e l'altra senza che nessuno abbia
    toccato il codice. Il caso perfettamente piatto resta coperto dai test su
    ``mercato_piatto``, che verificano che nulla si rompa — la verifica giusta
    per un caso degenere, dove il segnale esatto non è definibile.
    """
    chiusure: list[float] = []
    for t in range(BARRE):
        tendenza = 100.0 * math.exp(0.0004 * t)
        ciclo_lungo = 6.0 * math.sin(2 * math.pi * t / 120.0)
        ciclo_corto = 1.5 * math.sin(2 * math.pi * t / 17.0)
        chiusure.append(tendenza + ciclo_lungo + ciclo_corto)

    # Crollo secco a due terzi della serie.
    for t in range(320, BARRE):
        chiusure[t] *= 0.88
    # Tratto quasi fermo: oscillazioni minime ma mai nulle, così nessun
    # confronto finisce in pareggio esatto (vedi la nota qui sopra).
    for t in range(400, 420):
        chiusure[t] = chiusure[399] * (1.0 + 0.0004 * math.sin(t / 3.0))

    indice = pd.date_range("2020-01-01", periods=BARRE, freq="D")
    close = pd.Series(chiusure, index=indice)
    # Ampiezza della barra variabile ma deterministica; sul tratto piatto anche
    # massimo e minimo collassano sulla chiusura.
    ampiezza = pd.Series(
        [
            0.0004 if 400 <= t < 420 else 0.004 + 0.003 * abs(math.sin(t / 9.0))
            for t in range(BARRE)
        ],
        index=indice,
    )
    volume = pd.Series(
        [1000.0 + 400.0 * math.sin(t / 23.0) + 5.0 * (t % 7) for t in range(BARRE)],
        index=indice,
    )
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * (1.0 + ampiezza),
            "low": close * (1.0 - ampiezza),
            "close": close,
            "volume": volume,
        }
    )


def combinazioni_valide(strategy_id: str) -> list[dict]:
    """Tutte le combinazioni della griglia di base che superano la validazione."""
    griglia = AUTOSETTING_GRIDS.get(strategy_id, {})
    if not griglia:
        return []
    nomi = list(griglia)
    valide = []
    for combo in itertools.product(*(griglia[n] for n in nomi)):
        parametri = dict(zip(nomi, combo))
        try:
            validate_strategy_parameters(strategy_id, parametri)
        except ValueError:
            continue
        valide.append(parametri)
    return valide


def _impronta_segnale(strategy_id: str, data: pd.DataFrame, parametri: dict, short: bool) -> str:
    """Impronta di una singola combinazione.

    Anche gli errori vengono congelati: se oggi una combinazione solleva
    un'eccezione, deve continuare a sollevarla — o il cambiamento va notato.
    """
    try:
        segnale = build_strategy_signal(
            strategy_id=strategy_id, data=data, parameters=parametri, consenti_short=short
        )
    except Exception as errore:
        return f"errore:{type(errore).__name__}"
    valori = segnale.to_numpy(dtype=float).round(10)
    return hashlib.sha1(valori.tobytes()).hexdigest()[:16]


@lru_cache(maxsize=1)
def impronte_correnti() -> dict[str, dict]:
    """Impronta complessiva di ogni strategia in ciascun verso.

    Una sola impronta per strategia invece di una per combinazione: il file
    resta leggibile, e la severità è identica perché basta una barra diversa in
    una combinazione qualsiasi per cambiare l'aggregato.

    Calcolata una volta sola per sessione: i casi parametrizzati sono quindici e
    senza memoria rifarebbero quindici volte lo stesso lavoro.
    """
    data = mercato_di_riferimento()
    risultato: dict[str, dict] = {}
    for strategy_id in sorted(STRATEGY_SPECS):
        combinazioni = combinazioni_valide(strategy_id)
        for short in (False, True):
            pezzi = [
                _impronta_segnale(strategy_id, data, parametri, short)
                for parametri in combinazioni
            ]
            chiave = f"{strategy_id}|{'ribasso' if short else 'rialzo'}"
            risultato[chiave] = {
                "combinazioni": len(combinazioni),
                "impronta": hashlib.sha1("".join(pezzi).encode()).hexdigest()[:16],
            }
    return risultato


def _prima_differenza(strategy_id: str, short: bool) -> str:
    """Su quale combinazione i segnali sono cambiati.

    L'impronta aggregata dice *che* qualcosa è cambiato; questo dice *dove*,
    ricalcolando combinazione per combinazione.
    """
    data = mercato_di_riferimento()
    for parametri in combinazioni_valide(strategy_id):
        impronta = _impronta_segnale(strategy_id, data, parametri, short)
        yield parametri, impronta


# ── Il test ──────────────────────────────────────────────────────────────────

def _attese() -> dict[str, dict]:
    if not IMPRONTE.exists():
        pytest.fail(
            f"Manca il file delle impronte ({IMPRONTE.name}). "
            "Generalo con: python tests/test_impronte_strategie.py --rigenera"
        )
    return json.loads(IMPRONTE.read_text(encoding="utf-8"))


def test_il_mercato_di_riferimento_e_sempre_lo_stesso() -> None:
    """Se cambia il mercato cambiano tutte le impronte, e la rete non protegge
    più niente: questo test lo blocca prima."""
    data = mercato_di_riferimento()
    impronta = hashlib.sha1(
        data[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float).round(10).tobytes()
    ).hexdigest()[:16]

    assert len(data) == BARRE
    assert impronta == _attese()["_mercato"], (
        "Il mercato di riferimento è cambiato: le impronte delle strategie non "
        "sono più confrontabili. Se la modifica è voluta, rigenera tutto."
    )


def test_il_mercato_contiene_i_casi_difficili() -> None:
    """La rete serve solo se il mercato tocca i punti in cui gli indicatori
    faticano: regime di calma, crollo secco, cicli sovrapposti."""
    data = mercato_di_riferimento()

    variazioni = data["close"].pct_change()
    calmo = variazioni.iloc[401:420].abs()
    assert calmo.max() < 0.001, "manca il tratto di calma"
    assert variazioni.min() < -0.10, "manca il crollo secco"
    assert (variazioni.iloc[1:320] > 0).any() and (variazioni.iloc[1:320] < 0).any()


def test_nessun_confronto_finisce_in_pareggio_esatto() -> None:
    """La lezione della prima versione di questa rete.

    Il mercato aveva un tratto perfettamente piatto: lì la deviazione standard
    vale zero, il confronto con la banda di Bollinger diventa un pareggio esatto
    e il risultato dipende dall'ultimo bit di arrotondamento. In locale passava,
    su tre ambienti di CI falliva. Una rete che suona senza motivo è peggio di
    nessuna rete, quindi la condizione va tenuta lontana per costruzione.
    """
    close = mercato_di_riferimento()["close"]
    for periodo in (10, 15, 20, 25, 30):
        deviazione = close.rolling(periodo, min_periods=periodo).std(ddof=0).dropna()
        assert (deviazione > 1e-6).all(), (
            f"con periodo {periodo} la deviazione standard tocca lo zero: "
            "i confronti con le bande diventano pareggi esatti e l'impronta "
            "cambia da sola fra una versione di pandas e l'altra."
        )


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_i_segnali_non_sono_cambiati(strategy_id: str) -> None:
    """Il cuore della rete: nessun segnale può cambiare senza che si sappia."""
    attese = _attese()
    correnti = impronte_correnti()

    for verso, short in (("rialzo", False), ("ribasso", True)):
        chiave = f"{strategy_id}|{verso}"
        assert chiave in attese, (
            f"{chiave} non ha un'impronta salvata: se hai aggiunto una strategia, "
            "rigenera il file delle impronte."
        )
        atteso, corrente = attese[chiave], correnti[chiave]

        assert corrente["combinazioni"] == atteso["combinazioni"], (
            f"{chiave}: la griglia è cambiata "
            f"({atteso['combinazioni']} combinazioni prima, {corrente['combinazioni']} adesso)."
        )

        if corrente["impronta"] != atteso["impronta"]:
            dettaglio = _dove_e_cambiato(strategy_id, short)
            pytest.fail(f"{chiave}: il segnale è cambiato.\n{dettaglio}")


def _dove_e_cambiato(strategy_id: str, short: bool) -> str:
    """Messaggio utile invece di 'due stringhe diverse'."""
    righe = []
    for parametri, impronta in _prima_differenza(strategy_id, short):
        righe.append(f"  {parametri} -> {impronta}")
        if len(righe) >= 5:
            break
    return (
        "Prime combinazioni ricalcolate (confrontale con la versione precedente "
        "del codice per capire quale è cambiata):\n" + "\n".join(righe)
    )


def test_ogni_strategia_del_catalogo_ha_la_sua_impronta() -> None:
    """Aggiungere una strategia senza congelarne il comportamento renderebbe la
    rete piena di buchi senza che nessuno se ne accorga."""
    attese = set(_attese()) - {"_mercato", "_nota"}
    previste = {
        f"{sid}|{verso}" for sid in STRATEGY_SPECS for verso in ("rialzo", "ribasso")
    }

    assert previste == attese, f"impronte mancanti: {previste - attese}"


# ── Rigenerazione deliberata ─────────────────────────────────────────────────

def _rigenera() -> None:
    data = mercato_di_riferimento()
    contenuto = {
        "_nota": (
            "Impronte dei segnali prodotti dalle strategie sul mercato di riferimento. "
            "Rigenerare solo dopo una modifica VOLUTA del comportamento."
        ),
        "_mercato": hashlib.sha1(
            data[["open", "high", "low", "close", "volume"]]
            .to_numpy(dtype=float).round(10).tobytes()
        ).hexdigest()[:16],
        **impronte_correnti(),
    }
    IMPRONTE.write_text(json.dumps(contenuto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    strategie = len(contenuto) - 2
    print(f"Scritte {strategie} impronte in {IMPRONTE}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    if "--rigenera" not in sys.argv:
        print(__doc__)
        raise SystemExit("Aggiungi --rigenera per riscrivere le impronte.")
    _rigenera()
