"""Cerca il portafoglio migliore, con un budget dichiarato.

La ricerca a mercato singolo enumera tutto: a profondità media sono 18.180
backtest per mercato. Su un portafoglio quel modo di fare non regge, perché
alle combinazioni di parametri si moltiplicano le scelte di portafoglio — come
si divide il capitale, ogni quanto si rimettono in riga le quote — e il conto
esplode.

Qui il numero di configurazioni provate è **dichiarato in partenza** invece di
essere la conseguenza di una moltiplicazione. Non è ancora la ricerca guidata
della fase 5: è una griglia, ma piccola e con un tetto che si vede. Se la
griglia lo supera, la ricerca si ferma e lo dice, invece di girare per un'ora.

**Perché il tetto conta anche per l'onestà, non solo per il tempo.** Più punti
si esplorano, più alta è la soglia che la fortuna raggiunge da sola: una
ricerca senza budget dichiarato è una ricerca di cui non si può sapere quanto
sia facile vincere per caso. Il numero di configurazioni provate viaggia quindi
insieme al risultato, ed è quello che la prova del caso deve replicare sui dati
rimescolati perché il confronto sia alla pari.

**Due numeri, non uno.** Ogni configurazione viene misurata anche sul periodo
di prova, e non solo quella scelta. Serve a mostrare accanto al risultato onesto
— scelto sullo sviluppo, misurato una volta sola sulla prova — anche quello che
avrebbe fatto la configurazione migliore *col senno di poi*. La distanza fra i
due dice quanto spazio c'era per illudersi: su mercati costruiti senza alcuna
struttura, 60 configurazioni su 192 chiudono il periodo di prova in vantaggio e
la migliore arriva a +20 punti, mentre la procedura onesta non ne cava di
positivi. Guardare il primo numero credendo di guardare il secondo è il modo più
facile di raccontarsi una bugia con dati veri.
"""
from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from trading_bot.application.prova_del_caso import (
    EsitoProvaDelCaso,
    mescola_mercati,
    valuta_contro_il_caso,
)
from trading_bot.portafoglio import (
    MAI,
    QUOTA_FISSA,
    QUOTA_FRA_SCELTI,
    esegui_portafoglio,
)
from trading_bot.trasversali import SPEC_TRASVERSALI, costruisci_segnali_trasversali
from trading_bot.walkforward import MIN_TRADE_PER_SCELTA

# Fetta finale riservata alla prova su dati mai visti, come nella ricerca a
# mercato singolo: il confronto fra le due deve restare possibile.
HOLDOUT_RATIO = 0.20
# Sotto questa storia una divisione fra sviluppo e prova non ha senso.
MIN_BARRE = 300
# Quante configurazioni si è disposti a provare. Non è un limite tecnico: è la
# dichiarazione che rende interpretabile il risultato.
BUDGET_PREDEFINITO = 400

GRIGLIE_PORTAFOGLIO: dict[str, dict[str, list]] = {
    "forza_relativa": {
        "periodo": [60, 120, 180, 250],
        "quanti": [1, 2, 3, 5],
        "solo_se_sale": [0, 1],
    },
}

ALLOCAZIONI = (QUOTA_FRA_SCELTI, QUOTA_FISSA)
# "Mai" è comprare e tenere finché il segnale non cambia; gli altri due sono i
# calendari che una persona vera userebbe davvero.
RIBILANCIAMENTI = (MAI, "M", "Q")

ETICHETTE_ALLOCAZIONE = {
    QUOTA_FRA_SCELTI: "in parti uguali fra quelli scelti",
    QUOTA_FISSA: "una quota fissa ciascuno, il resto liquido",
}
ETICHETTE_RIBILANCIAMENTO = {
    MAI: "senza mai rimettere in riga le quote",
    "M": "rimettendo in riga le quote ogni mese",
    "Q": "rimettendo in riga le quote ogni tre mesi",
}


@dataclass(frozen=True)
class ConfigurazionePortafoglio:
    """Una risposta completa a "cosa compro e come divido i soldi"."""

    strategy_id: str
    parametri: tuple[tuple[str, int | float], ...]
    allocazione: str
    ribilancia_ogni: str
    consenti_short: bool = False

    @property
    def valori(self) -> dict[str, int | float]:
        return dict(self.parametri)

    @property
    def descrizione(self) -> str:
        spec = SPEC_TRASVERSALI[self.strategy_id]
        pezzi = ", ".join(
            f"{parametro.label.lower()}: {self.valori[parametro.name]}"
            for parametro in spec.parameters
            if parametro.name in self.valori
        )
        verso = " · anche al ribasso" if self.consenti_short else ""
        return (
            f"{spec.label} ({pezzi}), "
            f"{ETICHETTE_ALLOCAZIONE[self.allocazione]}, "
            f"{ETICHETTE_RIBILANCIAMENTO[self.ribilancia_ogni]}{verso}"
        )


@dataclass
class EsitoRicercaPortafoglio:
    """Cosa ha trovato la ricerca, e quanto era facile trovarlo per caso."""

    mercati: list[str]
    barre: int
    barre_sviluppo: int
    barre_prova: int
    configurazioni_provate: int
    budget: int
    migliore: str | None = None
    parametri: dict = field(default_factory=dict)
    riepilogo_prova: dict = field(default_factory=dict)
    # Il numero onesto: scelto sullo sviluppo, misurato una volta sola sulla prova.
    margine_pct: float = 0.0
    # Quanto avrebbe fatto la configurazione migliore col senno di poi, e quante
    # erano in vantaggio. Non è un risultato: è la misura di quanto spazio c'era
    # per illudersi guardando la classifica invece della procedura.
    margine_col_senno_di_poi_pct: float = 0.0
    configurazioni_in_vantaggio: int = 0
    prova_del_caso: dict | None = None
    verdetto: str = ""


def elenca_configurazioni(
    *, strategy_ids: list[str] | None = None, consenti_short: bool = False,
) -> list[ConfigurazionePortafoglio]:
    """Tutte le configurazioni di portafoglio in gara."""
    ids = [s for s in (strategy_ids or list(GRIGLIE_PORTAFOGLIO)) if s in GRIGLIE_PORTAFOGLIO]
    versi = (False, True) if consenti_short else (False,)

    configurazioni: list[ConfigurazionePortafoglio] = []
    for strategy_id in ids:
        griglia = GRIGLIE_PORTAFOGLIO[strategy_id]
        nomi = list(griglia)
        for valori in itertools.product(*(griglia[nome] for nome in nomi)):
            for allocazione, ribilancia, verso in itertools.product(
                ALLOCAZIONI, RIBILANCIAMENTI, versi
            ):
                configurazioni.append(
                    ConfigurazionePortafoglio(
                        strategy_id=strategy_id,
                        parametri=tuple(zip(nomi, valori)),
                        allocazione=allocazione,
                        ribilancia_ogni=ribilancia,
                        consenti_short=verso,
                    )
                )
    return configurazioni


def cerca_portafoglio(
    mercati: dict[str, pd.DataFrame],
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    consenti_short: bool = False,
    holdout_ratio: float = HOLDOUT_RATIO,
    budget: int = BUDGET_PREDEFINITO,
    strategy_ids: list[str] | None = None,
    prove_del_caso: int = 0,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> EsitoRicercaPortafoglio:
    """Prova le configurazioni di portafoglio e misura la migliore su dati nuovi.

    La scelta avviene **solo** sullo sviluppo; l'ultima fetta di storia non
    partecipa e serve a misurare cosa resta quando la selezione non può più
    aiutare. È la stessa disciplina della ricerca a mercato singolo, perché i
    due risultati devono restare confrontabili.
    """
    if len(mercati) < 2:
        raise ValueError("Un portafoglio ha senso da due mercati in su.")

    indice = _indice_comune(mercati)
    n = len(indice)
    if n < MIN_BARRE:
        raise ValueError(
            f"Servono almeno {MIN_BARRE} barre in comune fra i mercati per separare "
            f"sviluppo e prova (disponibili {n})."
        )

    allineati = {nome: dati.loc[indice] for nome, dati in mercati.items()}
    barre_prova = max(1, int(round(n * holdout_ratio)))
    barre_sviluppo = n - barre_prova
    indice_sviluppo = indice[:barre_sviluppo]
    indice_prova = indice[barre_sviluppo:]
    sviluppo = {nome: dati.iloc[:barre_sviluppo] for nome, dati in allineati.items()}

    configurazioni = elenca_configurazioni(
        strategy_ids=strategy_ids, consenti_short=consenti_short
    )
    if len(configurazioni) > budget:
        raise ValueError(
            f"La griglia contiene {len(configurazioni)} configurazioni ma il budget è "
            f"{budget}. Alzalo di proposito, o riduci la griglia: una ricerca senza "
            "tetto dichiarato è una ricerca di cui non si può sapere quanto sia facile "
            "vincere per caso."
        )

    costi = dict(
        initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
    )

    migliore: ConfigurazionePortafoglio | None = None
    miglior_punteggio = float("-inf")
    riepilogo_prova: dict | None = None
    margini_di_prova: list[float] = []

    for fatte, configurazione in enumerate(configurazioni, start=1):
        riepilogo = _prova_configurazione(sviluppo, configurazione, costi)
        # Ogni configurazione viene misurata anche sulla prova, non solo quella
        # scelta: e' l'unico modo per sapere quanto era facile sembrare bravi.
        sulla_prova = _prova_configurazione(
            allineati, configurazione, costi, solo_indice=indice_prova,
        )
        if sulla_prova is not None:
            margini_di_prova.append(float(sulla_prova.get("excess_return_pct", 0.0)))
        if progress_callback is not None:
            progress_callback(fatte, len(configurazioni), configurazione.descrizione)
        if riepilogo is None:
            continue
        # Una configurazione che non apre operazioni ha punteggio 0 secco e
        # batterebbe ogni configurazione in perdita senza aver fatto niente.
        if int(riepilogo.get("trade_count", 0)) < MIN_TRADE_PER_SCELTA:
            continue
        punteggio = float(riepilogo.get("sharpe_ratio", 0.0))
        if punteggio > miglior_punteggio:
            miglior_punteggio = punteggio
            migliore = configurazione
            riepilogo_prova = sulla_prova

    esito = EsitoRicercaPortafoglio(
        mercati=list(mercati),
        barre=int(n),
        barre_sviluppo=int(barre_sviluppo),
        barre_prova=int(barre_prova),
        configurazioni_provate=len(configurazioni),
        budget=int(budget),
        margine_col_senno_di_poi_pct=round(max(margini_di_prova), 2) if margini_di_prova else 0.0,
        configurazioni_in_vantaggio=sum(1 for m in margini_di_prova if m > 0),
    )
    if migliore is None:
        esito.verdetto = (
            "Nessuna configurazione ha aperto operazioni sullo sviluppo: con questi "
            "mercati e questa storia non c'è niente da misurare."
        )
        return esito
    if riepilogo_prova is None:
        esito.verdetto = "La configurazione migliore non è valutabile sul periodo di prova."
        return esito

    esito.migliore = migliore.descrizione
    esito.parametri = {
        "strategy_id": migliore.strategy_id,
        **migliore.valori,
        "allocazione": migliore.allocazione,
        "ribilancia_ogni": migliore.ribilancia_ogni,
        "consenti_short": migliore.consenti_short,
    }
    esito.riepilogo_prova = riepilogo_prova
    esito.margine_pct = round(float(riepilogo_prova.get("excess_return_pct", 0.0)), 2)

    if prove_del_caso > 0:
        caso = _prova_del_caso_portafoglio(
            mercati=allineati, margine_vero=esito.margine_pct, prove=prove_del_caso,
            argomenti=dict(
                initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
                consenti_short=consenti_short, holdout_ratio=holdout_ratio, budget=budget,
                strategy_ids=strategy_ids,
            ),
        )
        esito.prova_del_caso = dataclasses.asdict(caso) if caso else None

    esito.verdetto = _verdetto(esito)
    return esito


# ── I pezzi ──────────────────────────────────────────────────────────────────

def _indice_comune(mercati: dict[str, pd.DataFrame]) -> pd.Index:
    indice: pd.Index | None = None
    for dati in mercati.values():
        indice = dati.index if indice is None else indice.intersection(dati.index)
    if indice is None or len(indice) == 0:
        raise ValueError("I mercati indicati non hanno barre in comune.")
    return indice.sort_values()


def _prova_configurazione(
    mercati: dict[str, pd.DataFrame],
    configurazione: ConfigurazionePortafoglio,
    costi: dict,
    *,
    solo_indice: pd.Index | None = None,
) -> dict | None:
    """Esegue una configurazione e restituisce il riepilogo, o None se non regge.

    Con ``solo_indice`` i segnali nascono sull'intera storia e vengono poi
    ritagliati sul tratto richiesto: serve a far scaldare la classifica sulla
    storia precedente, senza la quale nel periodo di prova resterebbe vuota per
    tutta la sua prima parte. Non introduce lookahead — la classifica guarda
    solo indietro — ed è lo stesso accorgimento della ricerca a mercato singolo.
    """
    try:
        segnali = costruisci_segnali_trasversali(
            configurazione.strategy_id, mercati, configurazione.valori,
            consenti_short=configurazione.consenti_short,
        )
        if solo_indice is not None:
            mercati = {nome: dati.loc[solo_indice] for nome, dati in mercati.items()}
            segnali = segnali.loc[solo_indice]
        esito = esegui_portafoglio(
            mercati, {nome: segnali[nome] for nome in mercati},
            allocazione=configurazione.allocazione,
            ribilancia_ogni=configurazione.ribilancia_ogni,
            **costi,
        )
    except Exception:
        return None
    return esito.summary


def _prova_del_caso_portafoglio(
    *, mercati: dict[str, pd.DataFrame], margine_vero: float, prove: int, argomenti: dict,
) -> EsitoProvaDelCaso | None:
    """Rifà la stessa ricerca su storie rimescolate insieme e guarda cosa trova.

    Il rimescolamento è sincrono: chi si muoveva insieme continua a muoversi
    insieme, e a sparire è solo il tempo. Mescolare ogni mercato per conto suo
    distruggerebbe anche la struttura fra i mercati — cioè proprio la materia
    prima di una classifica — e regalerebbe la prova a chiunque.

    Il confronto è fra **la stessa procedura** applicata alle due situazioni: da
    una parte e dall'altra si sceglie sullo sviluppo e si misura una volta sola
    sulla prova. Confrontare il risultato onesto dei dati veri col migliore col
    senno di poi dei dati rimescolati sarebbe un paragone fra due domande
    diverse: sui dati finti quel numero arriva a +20 punti, e nessuna vittoria
    verrebbe mai riconosciuta — il che non è prudenza, è un metro rotto in
    un'unica direzione.
    """
    margini: list[float] = []
    for tentativo in range(prove):
        try:
            finta = cerca_portafoglio(
                mescola_mercati(mercati, seed=tentativo),
                prove_del_caso=0,   # nessuna ricorsione
                **argomenti,
            )
        except Exception:
            continue
        margini.append(finta.margine_pct)
    return valuta_contro_il_caso(margine_vero, margini)


def _verdetto(esito: EsitoRicercaPortafoglio) -> str:
    """La frase che dice com'è andata, senza gergo."""
    capitale = float(esito.riepilogo_prova.get("initial_capital", 0.0))
    finale = float(esito.riepilogo_prova.get("final_equity", 0.0))
    noioso = float(esito.riepilogo_prova.get("benchmark_final_equity", 0.0))
    differenza = finale - noioso

    apertura = (
        f"Su un periodo mai visto durante la ricerca, {capitale:,.0f} € sarebbero "
        f"diventati {finale:,.0f} €. Dividendo gli stessi soldi in parti uguali fra "
        f"gli stessi mercati e stando fermi: {noioso:,.0f} €"
    ).replace(",", ".")
    apertura += (
        f", cioè {abs(differenza):,.0f} € {'in più' if differenza >= 0 else 'in meno'}."
    ).replace(",", ".")

    quante = (
        f" La ricerca ha provato {esito.configurazioni_provate} configurazioni: "
        "più se ne provano, più è facile che la migliore sembri buona per caso."
    )
    if esito.configurazioni_in_vantaggio:
        quante += (
            f" Guardando col senno di poi, {esito.configurazioni_in_vantaggio} di quelle "
            f"configurazioni avrebbero chiuso il periodo di prova in vantaggio, e la "
            f"più fortunata di {esito.margine_col_senno_di_poi_pct:+.1f} punti: è quanto "
            "si può sembrare bravi scegliendo dopo aver visto il risultato."
        )

    caso = esito.prova_del_caso
    if caso and caso.get("prove"):
        return apertura + quante + " " + str(caso.get("verdetto", ""))
    return (
        apertura + quante +
        " La prova del caso non è stata eseguita: senza, non si può dire se questo "
        "risultato valga più di quello che salta fuori comunque provando tante "
        "combinazioni."
    )
