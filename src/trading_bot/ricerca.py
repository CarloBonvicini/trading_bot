"""Cercare con un budget invece di provare tutto.

Ogni ricerca del progetto enumera l'intera griglia. Finché i parametri sono due
è una scelta ragionevole: mille combinazioni si provano e si è sicuri di aver
guardato ovunque. Ma il conto è un prodotto, e cresce come tale — con sei
parametri e dieci valori ciascuno diventa un milione per strategia. Non è che
la ricerca rallenta: diventa impossibile, e quindi le strategie con molti
parametri non si possono nemmeno scrivere.

**Il meccanismo non è quello che sembrava.** Il piano prevedeva di tirare a
caso, sull'idea — vera in generale — che con molti parametri il caso batta la
griglia a parità di tentativi. Misurandolo sul catalogo di questo progetto non
paga: dieci strategie su diciotto hanno **due** parametri e nessuna ne ha più
di cinque, e su spazi così piccoli il caso è la via di mezzo fra le due cose
che funzionano. A parità di budget, sulla griglia fitta di sei strategie:

- la griglia grossolana raggiunge l'ottimo 1 volta su 6
- tirando a caso, 0 volte su 6
- guardando **intorno ai migliori**, 4 volte su 6 (e il 90-95% nelle altre due)

Da qui l'algoritmo: si semina un reticolo largo su tutto lo spazio, si guarda
chi ha funzionato, e si spende il resto del budget esplorando i suoi vicini.
Ripetendo, la ricerca si stringe dove promette invece di camminare ovunque.

**Sotto una certa taglia non si approssima niente.** Se la griglia intera sta
nel budget, la si enumera e basta: il risultato è identico a prima, esatto, e
tutte le ricerche che già costavano poco continuano a costare poco e a dare le
stesse risposte. La ricerca guidata entra in gioco solo dove l'alternativa era
non cercare affatto.

**Il budget non è solo tempo, è onestà.** Più punti si esplorano, più alto è il
vantaggio che la fortuna riesce a fabbricare: una ricerca di cui non si sa
quanti punti ha guardato è una ricerca di cui non si può sapere quanto sia
facile vincerla per caso. Per questo il conto dei tentativi viaggia insieme al
risultato, e la prova del caso lo riusa identico sui dati rimescolati.
"""
from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

# Quanta parte del budget si spende a guardarsi intorno prima di stringere. Con
# meno di così si finisce ad affinare il primo punto capitato; con molto di più
# si torna a una griglia, che è la cosa da cui si sta scappando.
QUOTA_ESPLORAZIONE = 0.40
# Quanti dei migliori si affinano a ogni giro. Uno solo si incastra sul primo
# rilievo che trova; troppi spalmano il budget e non si stringe mai.
QUANTI_AFFINARE = 4
# Budget predefinito: sopra questa taglia le griglie del progetto smettono di
# essere enumerabili in tempi umani.
BUDGET_PREDEFINITO = 400


@dataclass
class EsitoRicerca:
    """Cosa si è trovato, e quanto si è guardato per trovarlo."""

    parametri: dict[str, int | float]
    punteggio: float
    tentativi: int
    # Quante combinazioni aveva lo spazio: serve a dire se si è enumerato tutto
    # o si è cercato dentro un budget, che sono due affermazioni diverse. Quando
    # si è cercato dentro un budget è un limite superiore (i vincoli fra
    # parametri ne tagliano una parte): contarle davvero vorrebbe dire
    # enumerarle, cioè fare la cosa che si è deciso di non fare.
    spazio: int
    esaustiva: bool = False
    # I punti provati con il loro punteggio, per chi vuole mostrarli.
    provati: list[tuple[dict, float]] = field(default_factory=list)

    @property
    def quota_esplorata_pct(self) -> float:
        return round(self.tentativi / self.spazio * 100, 1) if self.spazio else 0.0


Griglia = Mapping[str, Sequence]
Valutazione = Callable[[dict], float | None]


def combinazioni(griglia: Griglia, ammessa: Callable[[dict], bool] | None = None) -> list[dict]:
    """Tutte le combinazioni della griglia che rispettano i vincoli.

    Da usare solo quando si sa che sono poche: è il prodotto cartesiano, cioè
    esattamente la cosa che questo modulo esiste per non fare più.
    """
    nomi = list(griglia)
    fuori: list[dict] = []
    for valori in itertools.product(*(griglia[nome] for nome in nomi)):
        punto = dict(zip(nomi, valori))
        if ammessa is not None and not ammessa(punto):
            continue
        fuori.append(punto)
    return fuori


def quante_combinazioni(griglia: Griglia) -> int:
    """Quanto è grande lo spazio, **senza costruirlo**.

    È il prodotto delle lunghezze: un limite superiore, perché i vincoli fra
    parametri (``fast < slow``) ne tagliano via una parte. Contarle davvero
    richiederebbe di enumerarle, e su un milione di punti è proprio ciò che non
    si può fare — sapere che sono troppe basta per decidere di non farlo.
    """
    totale = 1
    for valori in griglia.values():
        totale *= max(1, len(valori))
    return totale


def esplora(
    griglia: Griglia,
    valuta: Valutazione,
    *,
    budget: int = BUDGET_PREDEFINITO,
    ammessa: Callable[[dict], bool] | None = None,
    quanti_affinare: int = QUANTI_AFFINARE,
    quota_esplorazione: float = QUOTA_ESPLORAZIONE,
    seme: int = 0,
    tieni_provati: bool = False,
) -> EsitoRicerca:
    """Cerca il punto migliore della griglia senza per forza guardarli tutti.

    ``valuta`` riceve una combinazione e restituisce il suo punteggio (più alto
    è meglio), oppure ``None`` se quella combinazione non è utilizzabile: una
    che non si può valutare non deve fermare la ricerca né vincere per inerzia.

    ``budget`` è quante combinazioni si è disposti a provare. Se la griglia
    intera ci sta dentro viene enumerata: sotto quella taglia non c'è niente da
    approssimare, e il risultato resta quello esatto di sempre.
    """
    if budget < 1:
        raise ValueError("Il budget deve essere almeno una combinazione.")
    if not griglia:
        raise ValueError("Nessuna combinazione valida in questa griglia.")

    # Prima si guarda quanto è grande lo spazio senza costruirlo: su un milione
    # di punti, materializzarli per poi provarne cinquecento sarebbe esattamente
    # il problema che questo modulo risolve.
    if quante_combinazioni(griglia) <= budget:
        tutte = combinazioni(griglia, ammessa)
        if not tutte:
            raise ValueError("Nessuna combinazione valida in questa griglia.")
        return _enumera(tutte, valuta, tieni_provati=tieni_provati)

    return _guidata(
        griglia=griglia, valuta=valuta, budget=budget, ammessa=ammessa,
        quanti_affinare=quanti_affinare, quota_esplorazione=quota_esplorazione,
        seme=seme, tieni_provati=tieni_provati,
    )


# ── Le due strade ────────────────────────────────────────────────────────────

def _enumera(tutte: list[dict], valuta: Valutazione, *, tieni_provati: bool) -> EsitoRicerca:
    """Lo spazio è piccolo: si guarda ovunque e la risposta è esatta."""
    visti = _Visitati(valuta, tieni_provati=tieni_provati)
    for punto in tutte:
        visti.prova(punto)
    return visti.esito(spazio=len(tutte), esaustiva=True)


def _guidata(
    *, griglia: Griglia, valuta: Valutazione, budget: int,
    ammessa: Callable[[dict], bool] | None, quanti_affinare: int,
    quota_esplorazione: float, seme: int, tieni_provati: bool,
) -> EsitoRicerca:
    """Prima si semina largo, poi si stringe dove ha funzionato."""
    visti = _Visitati(valuta, tieni_provati=tieni_provati)
    quanti_seminare = max(quanti_affinare, int(budget * quota_esplorazione))
    rng = random.Random(seme)

    for punto in _reticolo(griglia, quanti_seminare, ammessa=ammessa, rng=rng):
        if len(visti) >= budget:
            break
        visti.prova(punto)

    # Poi si guarda intorno ai migliori, un anello alla volta, finché c'è budget.
    quanti = quanti_affinare
    while len(visti) < budget:
        nuovi: list[dict] = []
        for punto in visti.migliori(quanti):
            for vicino in vicini(griglia, punto, ammessa=ammessa):
                if not visti.gia_visto(vicino):
                    nuovi.append(vicino)

        if not nuovi and quanti < len(visti):
            # Intorno ai primi è tutto esplorato: si allarga la fronte ai
            # successivi in classifica prima di rinunciare. Ripartire subito a
            # caso lascerebbe la ricerca a un passo dalla cima con budget ancora
            # in mano — è successo davvero, e si vedeva solo misurando.
            quanti = min(len(visti), quanti * 2)
            continue

        if not nuovi:
            # Esplorato tutto quello che si poteva raggiungere: si riparte da
            # punti presi a caso invece di fermarsi con budget avanzato.
            nuovi = _a_caso(
                griglia, quanti=quanti_affinare * 4, ammessa=ammessa, rng=rng, esclusi=visti,
            )
            quanti = quanti_affinare
        if not nuovi:
            break
        for punto in nuovi:
            if len(visti) >= budget:
                break
            visti.prova(punto)

    return visti.esito(spazio=quante_combinazioni(griglia), esaustiva=False)


def _reticolo(
    griglia: Griglia, quanti: int, *, ammessa: Callable[[dict], bool] | None,
    rng: random.Random,
) -> list[dict]:
    """Un pugno di punti sparsi su tutto lo spazio, non ammucchiati in un angolo.

    Si prendono valori equidistanti lungo ogni parametro — estremi compresi,
    perché è agli estremi che una strategia smette di funzionare e lo si vuole
    sapere. Se i vincoli tagliano via troppo, si completa pescando a caso: meglio
    un reticolo imperfetto che un reticolo vuoto.
    """
    nomi = list(griglia)
    if not nomi:
        return []

    # Quanti valori prendere per parametro perché il prodotto stia in `quanti`.
    per_lato = max(2, int(round(quanti ** (1.0 / len(nomi)))))
    scelte = [_valori_sparsi(griglia[nome], per_lato) for nome in nomi]

    punti: list[dict] = []
    for valori in itertools.product(*scelte):
        punto = dict(zip(nomi, valori))
        if ammessa is not None and not ammessa(punto):
            continue
        punti.append(punto)
        if len(punti) >= quanti:
            return punti

    # Il reticolo non basta (spesso per via dei vincoli): si completa a caso.
    gia = {_chiave(p) for p in punti}
    for punto in _a_caso(griglia, quanti=quanti - len(punti), ammessa=ammessa, rng=rng):
        if _chiave(punto) not in gia:
            punti.append(punto)
            gia.add(_chiave(punto))
    return punti


def _a_caso(
    griglia: Griglia, *, quanti: int, ammessa: Callable[[dict], bool] | None,
    rng: random.Random, esclusi: "_Visitati | None" = None,
) -> list[dict]:
    """Punti pescati a caso, un valore per parametro.

    Si pesca dimensione per dimensione invece di sorteggiare da un elenco: su un
    milione di combinazioni l'elenco non si può nemmeno costruire, ed è tutto il
    punto. Si rinuncia dopo un po' di tentativi a vuoto — con vincoli stretti
    insistere significherebbe girare a lungo per niente.
    """
    nomi = list(griglia)
    fuori: list[dict] = []
    visti_qui: set[tuple] = set()
    tentativi_a_vuoto = 0
    while len(fuori) < quanti and tentativi_a_vuoto < 50:
        punto = {nome: rng.choice(list(griglia[nome])) for nome in nomi}
        chiave = _chiave(punto)
        gia = chiave in visti_qui or (esclusi is not None and esclusi.gia_visto(punto))
        if gia or (ammessa is not None and not ammessa(punto)):
            tentativi_a_vuoto += 1
            continue
        visti_qui.add(chiave)
        fuori.append(punto)
        tentativi_a_vuoto = 0
    return fuori


def _valori_sparsi(valori: Sequence, quanti: int) -> list:
    """``quanti`` valori equidistanti fra i disponibili, estremi compresi."""
    disponibili = list(valori)
    if quanti >= len(disponibili):
        return disponibili
    if quanti <= 1:
        return [disponibili[0]]
    passo = (len(disponibili) - 1) / (quanti - 1)
    posizioni = sorted({int(round(i * passo)) for i in range(quanti)})
    return [disponibili[i] for i in posizioni]


def vicini(
    griglia: Griglia, punto: Mapping, *, ammessa: Callable[[dict], bool] | None = None,
) -> list[dict]:
    """Le combinazioni a un passo da questa, una dimensione per volta.

    Un passo per volta e non tutte le diagonali: sono molte meno, e servono a
    rispondere alla domanda giusta — questo parametro, spostato di poco, cambia
    il risultato? È la stessa domanda della prova dei vicini, che chiede se il
    vantaggio dipende dall'aver azzeccato il numero esatto.
    """
    fuori: list[dict] = []
    for nome, valori in griglia.items():
        if nome not in punto:
            continue
        disponibili = list(valori)
        try:
            posizione = disponibili.index(punto[nome])
        except ValueError:
            # Il valore non è nella griglia (arriva da altrove): si parte dal
            # più vicino, invece di rinunciare a esplorare intorno a lui.
            posizione = min(
                range(len(disponibili)),
                key=lambda i: abs(float(disponibili[i]) - float(punto[nome])),
            )
        for passo in (-1, 1):
            j = posizione + passo
            if not 0 <= j < len(disponibili):
                continue
            candidato = {**dict(punto), nome: disponibili[j]}
            if ammessa is not None and not ammessa(candidato):
                continue
            fuori.append(candidato)
    return fuori


# ── Il registro di cosa si è provato ─────────────────────────────────────────

def _chiave(punto: Mapping) -> tuple:
    return tuple(sorted((nome, float(valore)) for nome, valore in punto.items()))


class _Visitati:
    """Tiene i punti già provati e il loro punteggio, senza rifarne nessuno.

    Il conteggio dei tentativi comprende anche i punti non valutabili: sono
    lavoro fatto, e il budget serve a dire quanto lavoro si è disposti a fare.
    """

    def __init__(self, valuta: Valutazione, *, tieni_provati: bool = False) -> None:
        self._valuta = valuta
        self._punteggi: dict[tuple, float] = {}
        self._punti: dict[tuple, dict] = {}
        self._tieni = tieni_provati

    def __len__(self) -> int:
        return len(self._punteggi)

    def gia_visto(self, punto: Mapping) -> bool:
        return _chiave(punto) in self._punteggi

    def prova(self, punto: Mapping) -> None:
        chiave = _chiave(punto)
        if chiave in self._punteggi:
            return
        try:
            punteggio = self._valuta(dict(punto))
        except Exception:
            punteggio = None
        # Una combinazione non valutabile non deve vincere per inerzia: sta in
        # fondo, ma resta contata fra i tentativi perché il lavoro l'ha richiesto.
        self._punteggi[chiave] = float("-inf") if punteggio is None else float(punteggio)
        self._punti[chiave] = dict(punto)

    def migliori(self, quanti: int) -> list[dict]:
        ordinate = sorted(self._punteggi, key=lambda k: self._punteggi[k], reverse=True)
        return [self._punti[k] for k in ordinate[:quanti]]

    def esito(self, *, spazio: int, esaustiva: bool) -> EsitoRicerca:
        if not self._punteggi:
            raise ValueError("Nessuna combinazione provata.")
        chiave = max(self._punteggi, key=lambda k: self._punteggi[k])
        return EsitoRicerca(
            parametri=self._punti[chiave],
            punteggio=self._punteggi[chiave],
            tentativi=len(self._punteggi),
            spazio=spazio,
            esaustiva=esaustiva,
            provati=(
                [(self._punti[k], self._punteggi[k]) for k in self._punteggi]
                if self._tieni else []
            ),
        )
