"""Strategie che confrontano i mercati fra loro invece di giudicarli uno alla volta.

Tutte le diciotto strategie a catalogo guardano un mercato per volta e
rispondono a "questo qui, si compra o no?". È una domanda legittima, ma non è
quella che si fa chi ha dei soldi da mettere: con venti mercati davanti, la
domanda vera è **quali** — e per rispondere bisogna guardarli tutti insieme,
perché "forte" non vuol dire niente in assoluto, vuol dire più forte degli altri.

Da qui un contratto diverso: una strategia trasversale riceve *tutti* i mercati
e restituisce un segnale per ciascuno, decisi guardando la classifica.

    (dict[str, DataFrame], **parametri) -> DataFrame di segnali

Il contratto delle diciotto strategie esistenti **non cambia di una virgola**.
Non è prudenza: la rete di sicurezza sulle impronte congela i loro segnali su
tutta la griglia, e se il portafoglio avesse richiesto di toccare quella firma
non ci sarebbe più stato modo di distinguere un segnale cambiato per una scelta
da uno cambiato per sbaglio.

**Il futuro non si vede lo stesso.** La classifica di una barra usa solo i dati
fino a quella barra, e il motore applica comunque lo scarto di una barra prima
di eseguire. Un ordinamento fatto sull'intera serie sarebbe la forma più
elegante di lookahead che si possa scrivere, e ``tests/test_trasversali.py``
tronca e stravolge il futuro per verificare che non stia succedendo.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_bot.features import indicatore
from trading_bot.strategies import StrategyParameter


@dataclass(frozen=True)
class SpecTrasversale:
    """Metadati di una strategia che ordina i mercati fra loro."""

    key: str
    label: str
    description: str
    parameters: tuple[StrategyParameter, ...]
    # Come per le strategie a mercato singolo: il ribasso esiste solo se ha una
    # regola sua, scritta apposta, e non come rovescio della condizione d'uscita.
    supports_short: bool = True

    def defaults(self) -> dict[str, int | float]:
        return {parametro.name: parametro.default for parametro in self.parameters}

    def parameter_map(self) -> dict[str, StrategyParameter]:
        return {parametro.name: parametro for parametro in self.parameters}


def forza_relativa(
    mercati: Mapping[str, pd.DataFrame],
    *,
    periodo: int = 120,
    quanti: int = 3,
    solo_se_sale: int = 1,
    consenti_short: bool = False,
) -> pd.DataFrame:
    """Compra i più forti fra quelli in esame, barra per barra.

    A ogni barra si mette in fila ogni mercato per quanto è salito in rapporto a
    quanto è stato scosso nel salirci (il rendimento nudo premierebbe sempre il
    più agitato), e si tengono i primi ``quanti``.

    Con ``solo_se_sale`` si compra solo chi sta effettivamente salendo: essere
    il primo di venti mercati che scendono tutti non è una buona ragione per
    comprarlo, ed è la differenza fra una classifica e una scommessa. Chi resta
    fuori sta in liquidità, che è una posizione e non un errore.

    Al ribasso la regola è esplicita e simmetrica: si vendono allo scoperto gli
    ultimi ``quanti`` della stessa classifica, cioè i più deboli — non l'opposto
    della condizione di uscita, che sarebbe un'altra cosa.

    I mercati su cui non c'è ancora abbastanza storia non entrano in classifica:
    ordinare qualcosa di cui non si sa niente vorrebbe dire sceglierlo a caso.
    """
    if quanti < 1:
        raise ValueError("Bisogna tenerne almeno uno.")
    if not mercati:
        raise ValueError("Serve almeno un mercato.")

    forza = classifica_di_forza(mercati, periodo=periodo)
    nomi = list(forza.columns)
    quanti = min(quanti, len(nomi))

    # Posto in classifica, dal più forte. "first" a parità: due mercati con la
    # stessa identica forza vanno ordinati in modo prevedibile, altrimenti due
    # esecuzioni della stessa ricerca darebbero risultati diversi.
    posto_dal_forte = forza.rank(axis=1, ascending=False, method="first")
    ammessi = forza.notna()

    segnali = pd.DataFrame(0.0, index=forza.index, columns=nomi)
    scelti = ammessi & (posto_dal_forte <= quanti)
    if solo_se_sale:
        scelti &= forza > 0
    segnali = segnali.mask(scelti, 1.0)

    if consenti_short:
        quanti_in_gara = ammessi.sum(axis=1)
        posto_dal_debole = forza.rank(axis=1, ascending=True, method="first")
        deboli = ammessi & (posto_dal_debole <= quanti)
        # Con pochi mercati in gara i primi e gli ultimi sarebbero gli stessi:
        # comprare e vendere la stessa cosa non è una strategia, è un errore.
        deboli &= quanti_in_gara.gt(2 * quanti).to_numpy()[:, None]
        if solo_se_sale:
            deboli &= forza < 0
        segnali = segnali.mask(deboli, -1.0)

    return segnali


def classifica_di_forza(
    mercati: Mapping[str, pd.DataFrame], *, periodo: int = 120
) -> pd.DataFrame:
    """Quanto è forte ciascun mercato, barra per barra, sulle barre comuni.

    Vuoto dove la storia non basta ancora: è quello che tiene fuori dalla
    classifica i mercati su cui non si sa niente.
    """
    indice: pd.Index | None = None
    for dati in mercati.values():
        indice = dati.index if indice is None else indice.intersection(dati.index)
    if indice is None or len(indice) == 0:
        raise ValueError("I mercati indicati non hanno barre in comune.")
    indice = indice.sort_values()

    forze: dict[str, pd.Series] = {}
    for nome, dati in mercati.items():
        ristretto = dati.loc[indice]
        forze[nome] = indicatore(
            "momentum_normalizzato", ristretto, periodo=periodo,
        ).replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame(forze, columns=list(mercati.keys()), index=indice)


SPEC_TRASVERSALI: dict[str, SpecTrasversale] = {
    "forza_relativa": SpecTrasversale(
        key="forza_relativa",
        label="I più forti del gruppo",
        description=(
            "Mette in fila i mercati per quanto stanno salendo rispetto a quanto "
            "sono agitati, e tiene i primi. È la prima strategia che per decidere "
            "su un mercato deve guardare anche tutti gli altri."
        ),
        parameters=(
            StrategyParameter(
                name="periodo", label="Quanta storia guardare (barre)",
                value_type="int", default=120, minimum=20, maximum=500, step=10,
            ),
            StrategyParameter(
                name="quanti", label="Quanti tenerne",
                value_type="int", default=3, minimum=1, maximum=20, step=1,
            ),
            StrategyParameter(
                name="solo_se_sale", label="Solo se sta salendo davvero (0 no, 1 sì)",
                value_type="int", default=1, minimum=0, maximum=1, step=1,
            ),
        ),
    ),
}

FUNZIONI_TRASVERSALI = {
    "forza_relativa": forza_relativa,
}


def costruisci_segnali_trasversali(
    strategy_id: str,
    mercati: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, int | float],
    consenti_short: bool = False,
) -> pd.DataFrame:
    """Costruisce i segnali di una strategia trasversale, uno per mercato."""
    if strategy_id not in FUNZIONI_TRASVERSALI:
        raise ValueError(f"Strategia trasversale non supportata: {strategy_id}.")
    spec = SPEC_TRASVERSALI[strategy_id]
    extra = {"consenti_short": True} if (consenti_short and spec.supports_short) else {}
    # I parametri arrivano dalle griglie e dai form, quindi possono essere
    # stringhe o float: qui tornano al tipo dichiarato una volta sola.
    tipi = spec.parameter_map()
    tarati = {
        nome: tipi[nome].parse(valore)
        for nome, valore in parameters.items()
        if nome in tipi
    }
    return FUNZIONI_TRASVERSALI[strategy_id](mercati, **tarati, **extra)
