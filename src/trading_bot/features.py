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
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# nome dell'indicatore -> funzione che lo calcola
INDICATORI: dict[str, Callable[..., pd.Series | pd.DataFrame]] = {}


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


# ── Indicatori adattivi ──────────────────────────────────────────────────────
# La prima famiglia veramente diversa da quelle a catalogo. Una media mobile
# classica ha un periodo fisso: scegli in anticipo se essere pronto o essere
# calmo, e sbagli sempre a metà del tempo. Questi cambiano velocità da soli.


@registra("efficienza")
def efficienza_del_movimento(data: pd.DataFrame, periodo: int = 10) -> pd.Series:
    """Quanto il prezzo si è mosso *verso una direzione* invece che avanti e indietro.

    Si confrontano due misure sulle ultime ``periodo`` barre: quanto il prezzo
    si è spostato da dove era partito (la distanza in linea d'aria) e quanta
    strada ha fatto in tutto (la somma di ogni singolo movimento).

    Se va dritto le due misure coincidono e il valore è vicino a 1; se
    zigzaga tornando al punto di partenza la distanza è quasi zero mentre la
    strada percorsa è tanta, e il valore scende verso 0. In gergo: efficiency
    ratio di Kaufman.
    """
    close = data["close"].astype(float)
    distanza = (close - close.shift(periodo)).abs()
    strada = close.diff().abs().rolling(window=periodo, min_periods=periodo).sum()
    return (distanza / strada.replace(0.0, np.nan)).fillna(0.0).clip(0.0, 1.0)


@registra("kama")
def kama(data: pd.DataFrame, periodo: int = 10, veloce: int = 2, lenta: int = 30) -> pd.Series:
    """Media mobile che accelera nei tratti puliti e rallenta nel rumore.

    Il problema di una media a periodo fisso è che il periodo giusto cambia col
    mercato: corto per stare dietro a una tendenza, lungo per non farsi
    scuotere dalle oscillazioni. Qui il periodo non si sceglie: si lascia
    decidere all'efficienza del movimento, barra per barra.

    Quando il prezzo va dritto la media insegue quasi subito; quando zigzaga
    quasi si ferma, e le oscillazioni non la spostano. È come un'auto che
    accelera in rettilineo e rallenta in curva, invece di andare sempre alla
    stessa velocità. In gergo: KAMA, Kaufman Adaptive Moving Average (1995).
    """
    if periodo <= 1:
        raise ValueError("Il periodo della KAMA deve essere maggiore di 1.")
    if veloce >= lenta:
        raise ValueError("La costante veloce deve essere più piccola di quella lenta.")

    close = data["close"].astype(float)
    efficienza = efficienza_del_movimento(data, periodo=periodo)
    passo_veloce = 2.0 / (veloce + 1.0)
    passo_lento = 2.0 / (lenta + 1.0)
    # Quanto la media si sposta verso il prezzo a ogni barra: fra il passo lento
    # e quello veloce, secondo l'efficienza. Al quadrato per rendere la frenata
    # più decisa quando il movimento è confuso.
    velocita = (efficienza * (passo_veloce - passo_lento) + passo_lento) ** 2

    prezzi = close.to_numpy()
    passi = velocita.to_numpy()
    valori = np.full(len(prezzi), np.nan)
    corrente = prezzi[0]
    for i in range(len(prezzi)):
        if i < periodo:
            corrente = prezzi[i]
            continue
        corrente = corrente + passi[i] * (prezzi[i] - corrente)
        valori[i] = corrente
    return pd.Series(valori, index=close.index, name="kama")


@registra("fisher")
def fisher(data: pd.DataFrame, periodo: int = 10) -> pd.Series:
    """Rende evidenti i punti di svolta, comprimendo il centro e allargando gli estremi.

    I prezzi passano la maggior parte del tempo ammucchiati intorno alla media,
    e un oscillatore normale li schiaccia tutti in mezzo: quando finalmente si
    arriva a un estremo, il grafico lo mostra come una curva dolce e la svolta
    si riconosce tardi.

    Qui si prende la posizione del prezzo dentro il suo intervallo recente (da
    -1 sul minimo a +1 sul massimo) e le si applica una trasformazione che vicino
    allo zero lascia quasi tutto com'è, mentre vicino ai bordi allunga i valori
    verso l'infinito. Il risultato è che gli estremi diventano picchi netti
    invece di curve morbide. È una lente d'ingrandimento sui bordi. In gergo:
    Fisher Transform di John Ehlers (2002).
    """
    if periodo <= 1:
        raise ValueError("Il periodo del Fisher deve essere maggiore di 1.")

    close = data["close"].astype(float)
    massimo = data["high"].astype(float).rolling(window=periodo, min_periods=periodo).max()
    minimo = data["low"].astype(float).rolling(window=periodo, min_periods=periodo).min()
    ampiezza = (massimo - minimo).replace(0.0, np.nan)
    # Posizione dentro l'intervallo, riportata fra -1 e +1.
    posizione = (2.0 * ((close - minimo) / ampiezza - 0.5)).fillna(0.0)

    valori_posizione = posizione.to_numpy()
    risultato = np.full(len(valori_posizione), np.nan)
    lisciata = 0.0
    precedente = 0.0
    for i in range(len(valori_posizione)):
        if np.isnan(valori_posizione[i]):
            continue
        # Un filo di smorzamento: senza, il valore salta a ogni barra e la
        # trasformazione amplifica anche il rumore.
        lisciata = 0.33 * valori_posizione[i] + 0.67 * lisciata
        # Lontano dai bordi per non finire a infinito.
        limitata = min(max(lisciata, -0.999), 0.999)
        trasformata = 0.5 * math.log((1.0 + limitata) / (1.0 - limitata))
        precedente = trasformata + 0.5 * precedente
        risultato[i] = precedente
    return pd.Series(risultato, index=close.index, name="fisher")


# ── Modelli stimati dai dati ─────────────────────────────────────────────────
# Fin qui ogni indicatore riceveva i suoi numeri dall'esterno: "RSI a 14",
# "banda a 2 deviazioni". Questi invece li ricavano dal mercato.
#
# Il pericolo è uno solo, e non si vede: stimare su dati che comprendono il
# futuro. Un modello che calcola la sua soglia usando anche le barre di domani
# produce un backtest splendido e inservibile.
#
# Qui è impedito per costruzione, non per attenzione: la stima è **mobile**, e
# a ogni barra guarda solo le barre precedenti. Non esiste un momento in cui il
# modello vede la serie intera, quindi non esiste il modo di sbagliare.


@registra("mezza_vita")
def mezza_vita(data: pd.DataFrame, finestra: int = 60) -> pd.Series:
    """Quanto ci mette il prezzo a ricoprire metà della distanza dalla sua media.

    È la domanda che sta sotto ogni strategia di ritorno alla media: quando il
    prezzo si allontana, poi torna indietro — e in quanto tempo? Invece di
    deciderlo a priori ("RSI sotto 30 rientra"), qui lo si misura.

    Si guarda se le variazioni tendono a **contraddire** il livello precedente:
    quando il prezzo è sopra la sua media tende a scendere, e viceversa. Più
    questa tendenza è marcata, più il rientro è rapido. Se invece le variazioni
    non hanno relazione col livello — un cammino casuale — non c'è nessun
    rientro da aspettarsi, e il valore restituito è infinito.

    In gergo: half-life di un processo di Ornstein-Uhlenbeck, stimata su finestra
    mobile. Ogni valore usa solo le ``finestra`` barre che lo precedono.
    """
    if finestra < 20:
        raise ValueError("La finestra per stimare la mezza vita deve essere almeno 20 barre.")

    close = data["close"].astype(float)
    livello = close.shift(1)
    variazione = close.diff()

    # Quanto la variazione segue il livello precedente: negativo = rientro.
    media_livello = livello.rolling(finestra, min_periods=finestra).mean()
    media_variazione = variazione.rolling(finestra, min_periods=finestra).mean()
    covarianza = (
        (livello * variazione).rolling(finestra, min_periods=finestra).mean()
        - media_livello * media_variazione
    )
    varianza = (
        (livello**2).rolling(finestra, min_periods=finestra).mean() - media_livello**2
    )
    pendenza = covarianza / varianza.replace(0.0, np.nan)

    # Solo una pendenza negativa descrive un rientro; il resto è cammino casuale
    # o addirittura tendenza che si autoalimenta, e non c'è mezza vita da dare.
    rientra = pendenza < 0
    fattore = (1.0 + pendenza).where(rientra)
    valida = rientra & (fattore > 0)
    vita = pd.Series(np.inf, index=close.index)
    vita[valida] = -np.log(2.0) / np.log(fattore[valida])
    return vita.rename("mezza_vita")


@registra("zscore")
def zscore(data: pd.DataFrame, finestra: int = 20) -> pd.Series:
    """Di quante deviazioni standard il prezzo è lontano dalla sua media recente.

    Serve a rendere confrontabili scostamenti su mercati diversi: "tre euro
    sopra la media" non dice niente, "due deviazioni sopra" sì.
    """
    close = data["close"].astype(float)
    media = close.rolling(finestra, min_periods=finestra).mean()
    scarto = close.rolling(finestra, min_periods=finestra).std(ddof=0)
    return ((close - media) / scarto.replace(0.0, np.nan)).fillna(0.0).rename("zscore")
