"""Registro degli indicatori: calcolati una volta, riusati da tutti.

Oggi ogni strategia ricalcola i propri indicatori da zero. Finché una strategia
ne usa uno solo è ininfluente; quando una strategia ne combina cinque, e la
ricerca prova mille combinazioni di parametri su cinque finestre, lo stesso RSI
viene ricalcolato decine di migliaia di volte identico a se stesso.

Il registro risolve questo, ma introduce il rischio opposto — servire il valore
sbagliato — che sarebbe molto peggio: un backtest che gira su dati di un altro
mercato non fallisce, dà semplicemente un risultato falso. Per questo la memoria
non è globale.

**Come è impedita la contaminazione.** La memoria vive dentro un *contesto*
legato a un preciso oggetto di dati. Il contesto serve la cache solo se i dati
richiesti sono *esattamente* quell'oggetto (confronto di identità, non di
contenuto). Chiunque passi dati diversi — un altro mercato, un'altra finestra,
la stessa storia rimescolata — ottiene un calcolo pulito. Non è una convenzione
da rispettare: è la struttura che lo impedisce.

Uso tipico, aperto una volta per mercato dalla ricerca::

    with contesto_indicatori(dati_del_mercato):
        for combinazione in mille_combinazioni:
            build_strategy_signal(...)   # gli indicatori comuni si calcolano una volta

Senza il contesto tutto continua a funzionare esattamente come prima, solo
senza risparmio: è ciò che rende la migrazione delle strategie sicura un pezzo
alla volta.
"""
from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pandas as pd

# nome dell'indicatore -> funzione che lo calcola
INDICATORI: dict[str, Callable[..., pd.Series]] = {}


def registra(nome: str) -> Callable[[Callable[..., pd.Series]], Callable[..., pd.Series]]:
    """Registra una funzione come indicatore riusabile.

    La funzione riceve i dati come primo argomento e i suoi parametri come
    argomenti nominati, e restituisce una serie allineata all'indice dei dati.
    """
    def decoratore(funzione: Callable[..., pd.Series]) -> Callable[..., pd.Series]:
        if nome in INDICATORI:
            raise ValueError(f"Indicatore già registrato: {nome}")
        INDICATORI[nome] = funzione
        return funzione
    return decoratore


@dataclass
class ContestoIndicatori:
    """Memoria degli indicatori calcolati su un preciso insieme di dati."""

    dati: pd.DataFrame
    _memoria: dict[tuple, pd.Series] = field(default_factory=dict)
    calcoli: int = 0      # quante volte si è calcolato davvero
    riusi: int = 0        # quante volte si è riusato un valore già pronto

    def vale_per(self, dati: pd.DataFrame) -> bool:
        """Vero solo se sono *esattamente* i dati di questo contesto.

        Confronto di identità e non di contenuto: due DataFrame con lo stesso
        indice possono contenere prezzi completamente diversi — è il caso della
        storia rimescolata nella prova del caso — e confonderli darebbe un
        risultato falso senza alcun errore visibile.
        """
        return dati is self.dati


_CONTESTO: contextvars.ContextVar[ContestoIndicatori | None] = contextvars.ContextVar(
    "contesto_indicatori", default=None
)


@contextmanager
def contesto_indicatori(dati: pd.DataFrame) -> Iterator[ContestoIndicatori]:
    """Apre una memoria per gli indicatori calcolati su questi dati.

    Se ne è già aperta una **sugli stessi identici dati** si continua a usare
    quella invece di crearne una nuova: la ricerca ne apre una per mercato e la
    walk-forward ne aprirebbe un'altra sulla stessa serie, azzerando la memoria
    a ogni strategia e buttando via proprio il riuso fra strategie diverse.
    """
    in_corso = _CONTESTO.get()
    if in_corso is not None and in_corso.vale_per(dati):
        yield in_corso
        return

    contesto = ContestoIndicatori(dati=dati)
    segnalibro = _CONTESTO.set(contesto)
    try:
        yield contesto
    finally:
        _CONTESTO.reset(segnalibro)


def contesto_attivo() -> ContestoIndicatori | None:
    """Il contesto in corso, se qualcuno ne ha aperto uno."""
    return _CONTESTO.get()


def indicatore(nome: str, dati: pd.DataFrame, **parametri: object) -> pd.Series:
    """Calcola un indicatore, riusando il valore già pronto quando è lecito.

    È lecito solo dentro un contesto aperto su questi *stessi* dati. Fuori da un
    contesto, o su dati diversi, si calcola da capo: più lento, mai sbagliato.
    """
    funzione = INDICATORI.get(nome)
    if funzione is None:
        raise ValueError(f"Indicatore non registrato: {nome}")

    contesto = contesto_attivo()
    if contesto is None or not contesto.vale_per(dati):
        return funzione(dati, **parametri)

    chiave = (nome, tuple(sorted(parametri.items())))
    pronto = contesto._memoria.get(chiave)
    if pronto is not None:
        contesto.riusi += 1
        return pronto

    valore = funzione(dati, **parametri)
    contesto._memoria[chiave] = valore
    contesto.calcoli += 1
    return valore
