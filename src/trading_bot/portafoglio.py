"""Il motore di portafoglio: un capitale solo diviso fra più mercati.

Finora il motore prendeva **una** serie di prezzi e **un** segnale. Con quella
forma non è nemmeno esprimibile la cosa che una persona fa davvero: non compra
un titolo solo, divide i soldi fra le cose che sta guardando. E soprattutto non
è esprimibile "compra i tre più forti fra venti", perché per sceglierne tre
bisogna guardarli tutti insieme.

Qui il motore prende N serie e N segnali e restituisce **una curva sola**.

**La regola dei pesi non è un dettaglio, è la sostanza.** Se ogni mercato
prendesse il segnale pieno, due mercati identici darebbero il doppio del
capitale impiegato: una leva 2× arrivata di nascosto, che farebbe sembrare
geniale qualunque cosa in un mercato che sale. Il capitale è **uno**, quindi la
somma di quanto è impegnato non può superarlo. Da qui le due politiche
esplicite: dividere fra i mercati effettivamente scelti, oppure tenere una quota
fissa per ciascuno e lasciare il resto fermo.

**Perché i conti tornano.** Con un mercato solo questo motore deve dare un
risultato identico a ``run_backtest``, altrimenti non sappiamo quale dei due
credere. Non è affidato all'attenzione: la posizione tenuta la calcola la stessa
``posizione_eseguita()`` che usa il motore singolo, e il riepilogo lo costruisce
la stessa ``_build_summary()``. Con un mercato le due strade sono la stessa
strada, e il test di coerenza lo verifica riga per riga.

Il metro di paragone non è più il comprare-e-tenere di un titolo, ma il
**portafoglio noioso**: dividere in parti uguali fra questi stessi mercati e
stare fermi. Con un mercato solo coincide col comprare-e-tenere di sempre.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from trading_bot.backtest import (
    # Importati apposta invece di riscritti: se il portafoglio ricalcolasse le
    # metriche per conto suo, una correzione al motore singolo non arriverebbe
    # qui e i due direbbero numeri diversi sugli stessi dati.
    _build_summary,
    _build_trades,
    _prima_barra_di_rovina,
    infer_periods_per_year,
    posizione_eseguita,
)

# ── Come si divide il capitale ───────────────────────────────────────────────
# "Compra i tre più forti fra venti" e "tieni un ventesimo su ciascuno dei tre
# che sono forti" sono due strategie diverse, e la differenza è tutta qui.

# Pesi uguali fra i mercati in cui si è davvero a mercato: se ne sono tre, un
# terzo per uno. È quello che si intende dicendo "compra i tre più forti".
QUOTA_FRA_SCELTI = "fra_scelti"
# Una quota fissa per ciascun mercato dell'universo: se sono venti e ne sono
# scelti tre, si impegna il 15% e l'85% resta liquido. Restare in liquidità è
# una posizione, non un errore.
QUOTA_FISSA = "quota_fissa"

POLITICHE = (QUOTA_FRA_SCELTI, QUOTA_FISSA)

# ── Ogni quanto si rimettono a posto le quote ────────────────────────────────
# Stando fermi i pesi si sbilanciano da soli: chi sale occupa una fetta sempre
# più grande. Riportarli in riga è un'operazione vera, che si paga.

# I pesi tornano al bersaglio a ogni barra. È la convenzione del motore a
# mercato singolo, dove "metà del capitale" vuol dire metà del capitale *di
# oggi*: per questo è il default, ed è ciò che rende i due motori confrontabili.
OGNI_BARRA = "barra"
# Non si tocca niente finché un segnale non cambia: i pesi derivano col mercato
# e le quote si rimettono a posto solo quando si entra o si esce da qualcosa.
MAI = "mai"
# In alternativa un calendario: "W" ogni settimana, "M" ogni mese, "Q" ogni
# trimestre, "A" ogni anno.
CALENDARI = ("W", "M", "Q", "A")


@dataclass
class EsitoPortafoglio:
    """Come è andata dividendo un capitale fra più mercati.

    Ha la stessa forma di ``BacktestResult`` — stesse chiavi nel riepilogo,
    stesse colonne nella curva — perché tutto ciò che sa leggere un backtest
    (il verdetto in euro, le schede, i grafici) sappia leggere anche questo
    senza sapere che è un portafoglio.
    """

    summary: dict[str, float | int | str]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    # Quanto capitale stava su ciascun mercato, barra per barra: è la parte che
    # un backtest a mercato singolo non ha e che qui è il cuore della faccenda.
    pesi: pd.DataFrame
    mercati: list[str] = field(default_factory=list)


def esegui_portafoglio(
    mercati: Mapping[str, pd.DataFrame],
    segnali: Mapping[str, pd.Series],
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 0.0,
    allocazione: str = QUOTA_FRA_SCELTI,
    ribilancia_ogni: str = OGNI_BARRA,
    massimo_per_mercato: float = 1.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    flat_at_close: bool = False,
) -> EsitoPortafoglio:
    """Divide un capitale fra N mercati seguendo N segnali e misura come va.

    ``mercati`` sono i dati OHLCV per simbolo, ``segnali`` la serie da -1 a +1
    di ciascuno: il segno è la direzione, il valore assoluto la convinzione.

    Si lavora sulle **barre in cui tutti i mercati erano aperti**: mettere
    insieme calendari diversi riempiendo i buchi inventerebbe prezzi che non
    sono mai esistiti, ed è meglio confrontare meno storia vera che più storia
    finta.

    Stop e target restano una faccenda del singolo mercato — sono l'uscita da
    una posizione, non una scelta di portafoglio — e vengono quindi applicati
    prima di dividere il capitale.

    ``ribilancia_ogni`` dice ogni quanto le quote tornano al bersaglio. Il
    default ``OGNI_BARRA`` riproduce esattamente la convenzione del motore a
    mercato singolo, dove "metà del capitale" significa metà del capitale di
    oggi. ``MAI`` e i calendari (``"W"``, ``"M"``, ``"Q"``, ``"A"``) lasciano
    invece che i pesi derivino col mercato e rimettono le quote in riga solo
    quando serve — pagando ogni spostamento.
    """
    if allocazione not in POLITICHE:
        raise ValueError(
            f"Politica di allocazione sconosciuta: {allocazione}. "
            f"Valori possibili: {', '.join(POLITICHE)}."
        )
    if ribilancia_ogni not in (OGNI_BARRA, MAI, *CALENDARI):
        raise ValueError(
            f"Ribilanciamento sconosciuto: {ribilancia_ogni}. Valori possibili: "
            f"{OGNI_BARRA} (a ogni barra), {MAI} (solo quando cambia un segnale), "
            f"oppure un calendario fra {', '.join(CALENDARI)}."
        )
    if not mercati:
        raise ValueError("Serve almeno un mercato per costruire un portafoglio.")
    if initial_capital <= 0:
        raise ValueError("Il capitale iniziale deve essere positivo.")
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("Commissioni e slippage non possono essere negativi.")
    mancanti = [nome for nome in mercati if nome not in segnali]
    if mancanti:
        raise ValueError(f"Manca il segnale per: {', '.join(sorted(mancanti))}.")

    nomi = list(mercati.keys())
    indice = _indice_comune(mercati)
    if len(indice) < 2:
        raise ValueError(
            "I mercati indicati non hanno abbastanza barre in comune: "
            "controlla che periodo e timeframe coincidano."
        )

    # ── Mercato per mercato: dal segnale alla posizione davvero tenuta ───────
    posizioni: dict[str, pd.Series] = {}
    desiderate: dict[str, pd.Series] = {}
    uscite_soglia: dict[str, pd.Series] = {}
    uscite_giornata: dict[str, pd.Series] = {}
    chiusure: dict[str, pd.Series] = {}

    for nome in nomi:
        dati = mercati[nome]
        if "close" not in dati.columns:
            raise ValueError(f"Il mercato {nome} non ha la colonna 'close'.")
        dati = dati.loc[indice]
        tenuta = posizione_eseguita(
            dati, segnali[nome], sl_pct=sl_pct, tp_pct=tp_pct, flat_at_close=flat_at_close,
        )
        posizioni[nome] = tenuta.eseguita
        desiderate[nome] = tenuta.desiderata
        uscite_soglia[nome] = tenuta.sl_tp
        uscite_giornata[nome] = tenuta.fine_giornata
        chiusure[nome] = dati["close"].astype(float)

    prezzi = pd.DataFrame(chiusure, columns=nomi)
    rendimenti = prezzi.pct_change().fillna(0.0)
    posizioni_frame = pd.DataFrame(posizioni, columns=nomi)

    obiettivo = _pesi_obiettivo(
        posizioni_frame, allocazione=allocazione, massimo_per_mercato=massimo_per_mercato,
    )
    # Lo stesso conto sul segnale prima dello shift: serve solo a mostrare cosa
    # la strategia *voleva*, accanto a quello che ha ottenuto.
    pesi_desiderati = _pesi_obiettivo(
        pd.DataFrame(desiderate, columns=nomi),
        allocazione=allocazione, massimo_per_mercato=massimo_per_mercato,
    )

    pesi, movimento, ribilanciamenti = _pesi_effettivi(
        obiettivo=obiettivo, rendimenti=rendimenti, posizioni=posizioni_frame,
        ribilancia_ogni=ribilancia_ogni,
    )
    conti = _conti_portafoglio(
        pesi=pesi, movimento=movimento, rendimenti=rendimenti,
        initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
    )

    # Rovina: al ribasso la perdita non ha un tetto. Se in una barra il conto
    # scende sotto zero, da lì in poi ogni metrica sarebbe priva di senso: si
    # chiude tutto e il capitale resta a zero. Stessa regola del motore singolo.
    barra_rovina = _prima_barra_di_rovina(conti["netto"])
    if barra_rovina is not None:
        posizioni_frame = posizioni_frame.copy()
        posizioni_frame.iloc[barra_rovina + 1:] = 0.0
        obiettivo = obiettivo.copy()
        obiettivo.iloc[barra_rovina + 1:] = 0.0
        for maschere in (uscite_soglia, uscite_giornata):
            for nome in nomi:
                serie = maschere[nome].copy()
                serie.iloc[barra_rovina + 1:] = False
                maschere[nome] = serie
        pesi, movimento, ribilanciamenti = _pesi_effettivi(
            obiettivo=obiettivo, rendimenti=rendimenti, posizioni=posizioni_frame,
            ribilancia_ogni=ribilancia_ogni,
        )
        conti = _conti_portafoglio(
            pesi=pesi, movimento=movimento, rendimenti=rendimenti,
            initial_capital=initial_capital, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )

    equity = conti["equity"]
    gross_equity = initial_capital * (1 + conti["lordo"]).cumprod()
    if barra_rovina is not None:
        equity = equity.copy()
        equity.iloc[barra_rovina:] = 0.0
        gross_equity.iloc[barra_rovina:] = 0.0

    # Il metro di paragone: dividere in parti uguali fra questi stessi mercati e
    # stare fermi. Con un mercato solo è esattamente il comprare-e-tenere.
    rendimento_noioso = _rendimento_del_noioso(prezzi=prezzi, rendimenti=rendimenti)
    benchmark_equity = initial_capital * (1 + rendimento_noioso).cumprod()

    equity_curve = pd.DataFrame(
        {
            "signal": pesi_desiderati.sum(axis=1),
            "position": pesi.sum(axis=1),
            "binary_position": posizioni_frame.sum(axis=1),
            "sl_tp_exit": pd.DataFrame(uscite_soglia, columns=nomi).sum(axis=1).astype(int),
            "end_of_day_exit": pd.DataFrame(uscite_giornata, columns=nomi).sum(axis=1).astype(int),
            "market_return": rendimento_noioso,
            "gross_strategy_return": conti["lordo"],
            "strategy_return": conti["netto"],
            "transaction_cost_rate": conti["costo"],
            "transaction_cost_amount": equity.shift(1).fillna(initial_capital) * conti["costo"],
            "fee_cost_amount": equity.shift(1).fillna(initial_capital) * conti["commissioni"],
            "slippage_cost_amount": equity.shift(1).fillna(initial_capital) * conti["slippage"],
            "equity": equity,
            "gross_equity": gross_equity,
            "benchmark_equity": benchmark_equity,
            "drawdown": equity / equity.cummax() - 1,
            "benchmark_drawdown": benchmark_equity / benchmark_equity.cummax() - 1,
        }
    )

    trades = _operazioni_per_mercato(prezzi=prezzi, posizioni=posizioni_frame,
                                     uscite_soglia=uscite_soglia, uscite_giornata=uscite_giornata)
    summary = _build_summary(
        equity_curve=equity_curve,
        trades=trades.drop(columns=["symbol"]) if not trades.empty else trades,
        initial_capital=initial_capital,
        periods_per_year=infer_periods_per_year(indice),
        barra_rovina=barra_rovina,
    )
    summary.update(
        _riepilogo_di_portafoglio(
            pesi=pesi, posizioni=posizioni_frame, prezzi=prezzi, nomi=nomi,
            ribilanciamenti=ribilanciamenti,
        )
    )

    return EsitoPortafoglio(
        summary=summary, equity_curve=equity_curve, trades=trades, pesi=pesi, mercati=nomi,
    )


def salva_report_portafoglio(
    esito: EsitoPortafoglio,
    output_dir: str | Path,
    *,
    nome: str = "portafoglio",
    configurazione: dict | None = None,
) -> Path:
    """Scrive su disco un portafoglio, con le stesse convenzioni di un backtest.

    Gli stessi tre file di sempre (``summary.json``, ``equity_curve.csv``,
    ``trades.csv``) con le stesse chiavi, più due che esistono solo qui:
    ``pesi.csv`` dice quanto capitale stava su ogni mercato barra per barra, e
    in ``trades.csv`` compare la colonna ``symbol``. Aggiungere colonne e file
    non rompe niente di già salvato; rinominare sì, e infatti non succede.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cartella = Path(output_dir) / f"{nome}-{timestamp}"
    cartella.mkdir(parents=True, exist_ok=True)

    with (cartella / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(esito.summary, handle, indent=2)
    with (cartella / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "artifact_type": "portafoglio",
                "mercati": esito.mercati,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "report_name": cartella.name,
                **(configurazione or {}),
            },
            handle, indent=2,
        )

    esito.equity_curve.to_csv(cartella / "equity_curve.csv", index_label="date")
    esito.trades.to_csv(cartella / "trades.csv", index=False)
    esito.pesi.to_csv(cartella / "pesi.csv", index_label="date")
    return cartella


# ── I pezzi ──────────────────────────────────────────────────────────────────

def _indice_comune(mercati: Mapping[str, pd.DataFrame]) -> pd.Index:
    """Le barre in cui tutti i mercati erano aperti."""
    indice: pd.Index | None = None
    for dati in mercati.values():
        indice = dati.index if indice is None else indice.intersection(dati.index)
    return indice.sort_values() if indice is not None else pd.Index([])


def _pesi_obiettivo(
    posizioni: pd.DataFrame, *, allocazione: str, massimo_per_mercato: float,
) -> pd.DataFrame:
    """Quanta parte del capitale tocca a ciascun mercato, barra per barra.

    Il segnale dice *quanto ci credo* (il valore assoluto, da 0 a 1); la quota
    dice *quanta parte del capitale ho a disposizione per questo mercato*. Il
    peso è il prodotto dei due, e la somma dei pesi non può superare il capitale
    — che è uno.
    """
    if posizioni.empty or not len(posizioni.columns):
        return posizioni

    if allocazione == QUOTA_FISSA:
        quota = 1.0 / len(posizioni.columns)
        pesi = posizioni * quota
    else:
        # Con un mercato solo a mercato la quota è 1.0 esatto: è ciò che rende
        # questo motore indistinguibile da quello singolo nel caso a un mercato.
        attivi = (posizioni != 0.0).sum(axis=1)
        quota = 1.0 / attivi.where(attivi > 0, 1)
        pesi = posizioni.mul(quota, axis=0)

    tetto = abs(float(massimo_per_mercato))
    return pesi.clip(lower=-tetto, upper=tetto)


def _quando_si_ribilancia(
    posizioni: pd.DataFrame, ribilancia_ogni: str,
) -> np.ndarray:
    """In quali barre si mettono davvero le mani sul portafoglio.

    Due motivi, e il primo non è negoziabile: se un mercato entra o esce, il
    capitale va spostato comunque, calendario o no. Un segnale non è un peso e
    non può aspettare la fine del mese. Il secondo è il calendario scelto.
    """
    cambia = (posizioni != posizioni.shift(1)).any(axis=1)
    cambia.iloc[0] = True   # la prima barra è sempre un acquisto

    if ribilancia_ogni != MAI:
        indice = posizioni.index
        if not isinstance(indice, pd.DatetimeIndex):
            raise ValueError(
                "Per ribilanciare a calendario serve un indice di date: "
                "questi mercati non ne hanno uno."
            )
        periodi = indice.to_period(ribilancia_ogni)
        nuovo_periodo = np.empty(len(periodi), dtype=bool)
        nuovo_periodo[0] = True
        nuovo_periodo[1:] = periodi[1:] != periodi[:-1]
        cambia = cambia | pd.Series(nuovo_periodo, index=indice)

    return cambia.to_numpy(dtype=bool)


def _pesi_effettivi(
    *, obiettivo: pd.DataFrame, rendimenti: pd.DataFrame, posizioni: pd.DataFrame,
    ribilancia_ogni: str,
) -> tuple[pd.DataFrame, pd.Series, int]:
    """I pesi davvero tenuti, e quanto capitale si è dovuto spostare per averli.

    Con ``OGNI_BARRA`` i pesi coincidono col bersaglio a ogni barra: è la
    convenzione del motore a mercato singolo, dove una posizione al 40% resta
    al 40% del capitale corrente senza che il conto delle commissioni se ne
    accorga. Tenerla identica qui è ciò che permette al criterio di coerenza di
    essere una verifica vera e non un'approssimazione.

    Negli altri casi i pesi **derivano**: chi sale occupa una fetta sempre più
    grande, esattamente come succede a chi compra e non tocca più niente. Solo
    nelle barre di ribilanciamento si torna al bersaglio, e lì si paga la
    differenza fra dove i pesi erano arrivati e dove li si rimette.
    """
    if ribilancia_ogni == OGNI_BARRA:
        movimento = obiettivo.diff().abs()
        movimento.iloc[0] = obiettivo.iloc[0].abs()
        return obiettivo, movimento.sum(axis=1), int(len(obiettivo))

    quando = _quando_si_ribilancia(posizioni, ribilancia_ogni)
    bersagli = obiettivo.to_numpy(dtype=float)
    variazioni = rendimenti.to_numpy(dtype=float)
    pesi = np.zeros_like(bersagli)
    spostato = np.zeros(len(bersagli))
    corrente = np.zeros(bersagli.shape[1])

    for t in range(len(bersagli)):
        if t > 0:
            # Deriva: la parte investita cresce (o cala) col mercato, la
            # liquidità resta ferma, e le quote si ricalcolano sul totale.
            crescita = corrente * (1.0 + variazioni[t - 1])
            totale = 1.0 + float(corrente @ variazioni[t - 1])
            corrente = crescita / totale if totale != 0.0 else crescita
        if quando[t]:
            spostato[t] = float(np.abs(bersagli[t] - corrente).sum())
            corrente = bersagli[t].copy()
        pesi[t] = corrente

    return (
        pd.DataFrame(pesi, index=obiettivo.index, columns=obiettivo.columns),
        pd.Series(spostato, index=obiettivo.index),
        int(quando.sum()),
    )


def _conti_portafoglio(
    *, pesi: pd.DataFrame, movimento: pd.Series, rendimenti: pd.DataFrame,
    initial_capital: float, fee_bps: float, slippage_bps: float,
) -> dict[str, pd.Series]:
    """Dai pesi ai rendimenti, ai costi, all'equity.

    Ogni spostamento si paga: entrare, uscire, e anche solo cambiare la fetta di
    capitale su un mercato che si continua a tenere. Un portafoglio che
    ribilancia senza pagare sarebbe un portafoglio che non esiste — e siccome
    ribilanciare è proprio la cosa che fa sembrare buona la diversificazione,
    sarebbe anche l'errore più comodo da lasciarsi sfuggire.
    """
    movimento_totale = movimento

    commissioni = movimento_totale * (fee_bps / 10_000.0)
    slippage = movimento_totale * (slippage_bps / 10_000.0)
    costo = commissioni + slippage
    lordo = (pesi * rendimenti).sum(axis=1)
    netto = lordo - costo
    return {
        "movimento": movimento_totale,
        "commissioni": commissioni,
        "slippage": slippage,
        "costo": costo,
        "lordo": lordo,
        "netto": netto,
        "equity": initial_capital * (1 + netto).cumprod(),
    }


def _rendimento_del_noioso(*, prezzi: pd.DataFrame, rendimenti: pd.DataFrame) -> pd.Series:
    """Il rendimento, barra per barra, di chi divide in parti uguali e sta fermo.

    Stando fermi i pesi si sbilanciano da soli: chi sale pesa sempre di più.
    Per questo la media è pesata sui **valori della barra precedente** e non
    sulle quote di partenza. Con un mercato solo il peso vale esattamente 1 e il
    risultato coincide, cifra per cifra, col comprare-e-tenere di sempre.
    """
    quota = 1.0 / len(prezzi.columns)
    valore = prezzi.div(prezzi.iloc[0], axis=1) * quota
    peso_precedente = valore.shift(1)
    totale = peso_precedente.sum(axis=1)
    peso_precedente = peso_precedente.div(totale.where(totale != 0.0, 1.0), axis=0)
    return (peso_precedente * rendimenti).sum(axis=1).fillna(0.0)


def _operazioni_per_mercato(
    *, prezzi: pd.DataFrame, posizioni: pd.DataFrame,
    uscite_soglia: Mapping[str, pd.Series], uscite_giornata: Mapping[str, pd.Series],
) -> pd.DataFrame:
    """Il registro delle operazioni, con la colonna che dice su quale mercato.

    Si riusa lo stesso estrattore del motore singolo, una volta per mercato: le
    operazioni si contano sul verso, e una variazione di peso dovuta al fatto
    che è entrato un altro mercato non è un'operazione nuova su questo.
    """
    registri = []
    for nome in posizioni.columns:
        operazioni = _build_trades(
            close=prezzi[nome],
            binary_position=posizioni[nome],
            sl_tp_mask=uscite_soglia[nome],
            eod_mask=uscite_giornata[nome],
        )
        if operazioni.empty:
            continue
        operazioni.insert(0, "symbol", nome)
        registri.append(operazioni)

    if not registri:
        return pd.DataFrame(columns=["symbol"])
    return pd.concat(registri, ignore_index=True).sort_values(
        by=["entry_date", "symbol"], kind="stable"
    ).reset_index(drop=True)


def _riepilogo_di_portafoglio(
    *, pesi: pd.DataFrame, posizioni: pd.DataFrame, prezzi: pd.DataFrame, nomi: list[str],
    ribilanciamenti: int,
) -> dict[str, float | int | str]:
    """Le voci che esistono solo perché i mercati sono più di uno.

    ``capitale_impegnato_pct`` è la somma dei valori assoluti, non la somma
    netta: chi tiene metà al rialzo e metà al ribasso ha tutto il capitale a
    rischio, mentre la somma netta direbbe zero.
    """
    lordo = pesi.abs().sum(axis=1)
    a_mercato = (posizioni != 0.0).sum(axis=1)
    return {
        "mercati_count": int(len(nomi)),
        "mercati_elenco": ", ".join(nomi),
        "capitale_impegnato_pct": round(float(lordo.mean()) * 100, 2),
        "capitale_impegnato_massimo_pct": (
            round(float(lordo.max()) * 100, 2) if len(lordo) else 0.0
        ),
        "mercati_medi_a_mercato": round(float(a_mercato.mean()), 2) if len(a_mercato) else 0.0,
        "mercati_insieme_massimo": int(a_mercato.max()) if len(a_mercato) else 0,
        "quanto_si_muovono_insieme": quanto_si_muovono_insieme(prezzi),
        "ribilanciamenti": int(ribilanciamenti),
    }


def quanto_si_muovono_insieme(prezzi: pd.DataFrame) -> float:
    """Quanto i mercati si muovono insieme, in media, da -1 a +1.

    È il numero che dice se la divisione fra mercati è vera o apparente: venti
    titoli che salgono e scendono negli stessi giorni sono un titolo solo
    comprato venti volte, e il calo peggiore non si riduce di niente. Vicino a
    +1 la diversificazione è una parola; vicino a 0 è reale.

    In gergo: correlazione media a coppie dei rendimenti.
    """
    if prezzi.shape[1] < 2:
        return 0.0
    valori = prezzi.pct_change().corr().to_numpy(dtype=float)
    sopra = valori[np.triu_indices_from(valori, k=1)]
    sopra = sopra[np.isfinite(sopra)]
    return round(float(sopra.mean()), 3) if len(sopra) else 0.0
