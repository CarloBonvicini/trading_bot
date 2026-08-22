"""Il test del caso: la vittoria trovata vale più di quella che trova la fortuna?

Una ricerca a profondità media prova oltre cinquemila configurazioni per
mercato. Il "vincitore" è il migliore fra cinquemila: se lanci cinquemila
monetine, la migliore fa dodici teste di fila — e non è truccata, è solo la
migliore di cinquemila.

L'unico modo onesto di rispondere è rifare **la stessa identica ricerca** su
dati in cui ogni struttura temporale è stata distrutta, e guardare quanto
riesce a spremere la fortuna da sola. Se sui dati veri il campione batte il
mercato di 8 punti e sui dati mescolati la fortuna ne tira fuori 7, non abbiamo
trovato niente. Se la fortuna si ferma a 2, lì c'è qualcosa.

Il confronto è sul **margine rispetto al comprare-e-tenere**, non sul
rendimento: mescolando i rendimenti anche il mercato di riferimento cambia, e
solo il margine resta paragonabile fra le due situazioni.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Quante volte rimescolare la storia. Ogni prova costa quanto una ricerca
# intera, quindi la tentazione di farne poche è forte — ed è esattamente la
# tentazione che va tolta di mezzo (vedi PROVE_MINIME_PER_VITTORIA).
PROVE_PREDEFINITE = 5
# Sotto questo margine di vantaggio sul caso non c'è niente da festeggiare.
MARGINE_SUL_CASO_MINIMO = 2.0

# Quante prove servono **come minimo** per poter dire di sì.
#
# Misurato, e la misura è il motivo per cui questo numero esiste: su un mercato
# costruito senza alcuna struttura, cercando a fondo, i margini che la fortuna
# produce su otto rimescolamenti andavano da −2 a +21, con uno scarto di **nove
# punti** — contro un margine minimo di due. Il massimo di due estrazioni così
# sparse non è un metro, è un sorteggio: nel caso misurato le prime due prove
# avevano dato −2,2 e la vittoria sarebbe stata riconosciuta, mentre il soffitto
# vero della fortuna era +20,8 e batteva il campione in metà dei rimescolamenti.
#
# Con meno prove di così non si dice "no": si dice **non lo so**, che è una
# risposta diversa e onesta.
PROVE_MINIME_PER_VITTORIA = 5
# Quanto pesa la dispersione dei margini della fortuna nel fissare l'asticella.
# Con margini molto sparsi il massimo osservato dice poco su quello possibile, e
# battere il massimo di qualche estrazione non basta più.
PESO_DISPERSIONE = 1.0


@dataclass
class EsitoProvaDelCaso:
    """Quanto avrebbe ottenuto la fortuna cercando fra le stesse opzioni."""

    prove: int
    margine_vero_pct: float          # margine del campione sui dati veri
    margini_del_caso_pct: list[float] = field(default_factory=list)
    verdetto: str = ""
    superato: bool = False

    @property
    def margine_del_caso_pct(self) -> float:
        """Il meglio che la fortuna è riuscita a fare in queste prove."""
        return max(self.margini_del_caso_pct) if self.margini_del_caso_pct else 0.0

    @property
    def dispersione_pct(self) -> float:
        """Quanto sono sparsi fra loro i margini che la fortuna ha prodotto.

        È il numero che dice quanto fidarsi del massimo osservato: se da un
        rimescolamento all'altro la fortuna passa da −2 a +21, il massimo di
        poche prove non descrive il suo soffitto, lo sfiora per caso.
        """
        if len(self.margini_del_caso_pct) < 2:
            return 0.0
        media = sum(self.margini_del_caso_pct) / len(self.margini_del_caso_pct)
        varianza = sum((m - media) ** 2 for m in self.margini_del_caso_pct) / len(
            self.margini_del_caso_pct
        )
        return round(varianza**0.5, 2)

    @property
    def asticella_pct(self) -> float:
        """Il margine che bisogna superare per parlare di vittoria.

        Non è solo il meglio che la fortuna ha fatto: è quello **più** un
        margine, **più** un'allowance per quanto le prove erano sparse fra loro.
        Con margini stabili l'asticella coincide quasi col massimo osservato;
        con margini ballerini si alza, perché lì il massimo osservato è una
        misura debole di quello possibile.
        """
        return round(
            self.margine_del_caso_pct
            + MARGINE_SUL_CASO_MINIMO
            + PESO_DISPERSIONE * self.dispersione_pct,
            2,
        )


def mescola_serie(data: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Rimescola la storia mantenendo la statistica, distruggendo l'ordine.

    Si permutano le variazioni da una barra all'altra e si ricostruiscono i
    prezzi: la serie che ne esce ha la stessa volatilità, gli stessi salti e la
    stessa deriva complessiva di quella vera, ma nessuna tendenza, nessun
    ritorno alla media, nessuna struttura che una strategia possa sfruttare.
    Tutto quello che una strategia ci trova è fortuna per definizione.

    Le colonne high/low/open mantengono la loro distanza relativa dal close,
    così le barre restano forme plausibili e gli indicatori che usano massimi e
    minimi continuano a funzionare.
    """
    if "close" not in data.columns or len(data) < 3:
        return data.copy()

    rng = np.random.default_rng(seed)
    close = data["close"].astype(float)
    variazioni = close.pct_change().to_numpy()[1:]
    mescolate = rng.permutation(variazioni)

    partenza = float(close.iloc[0])
    nuovi = np.concatenate([[partenza], partenza * np.cumprod(1.0 + mescolate)])

    mescolata = pd.DataFrame(index=data.index)
    mescolata["close"] = nuovi
    rapporto = nuovi / close.to_numpy()
    for colonna in ("open", "high", "low"):
        if colonna in data.columns:
            mescolata[colonna] = data[colonna].astype(float).to_numpy() * rapporto
    if "volume" in data.columns:
        mescolata["volume"] = data["volume"].to_numpy()
    return mescolata


def mescola_mercati(
    mercati: dict[str, pd.DataFrame], seed: int = 0
) -> dict[str, pd.DataFrame]:
    """Rimescola più mercati insieme, con **la stessa permutazione per tutti**.

    Su un mercato solo la domanda era una: quanto ci guadagna la fortuna se il
    tempo non ha struttura? Con più mercati le domande diventano due, perché ci
    sono due strutture da distruggere — quella nel tempo e quella *fra* i
    mercati — e mescolare ognuno per conto suo le distrugge tutte e due.

    Sarebbe l'errore comodo. Una strategia che ordina i mercati fra loro vive
    proprio della struttura trasversale: misurarla contro un mondo dove quella
    struttura non esiste vorrebbe dire darle un avversario che non ha mai
    incontrato, e qualunque risultato passerebbe la prova.

    Con la stessa permutazione su tutti, invece, chi si muoveva insieme continua
    a muoversi insieme — i giorni cambiano ordine tutti nello stesso modo — e a
    sparire è solo il tempo: nessuna tendenza, nessun ritorno alla media,
    nessuna forza che dura. Su quei dati una classifica di forza non ha niente
    da trovare, per costruzione, e tutto quello che ci trova è fortuna.
    """
    if not mercati:
        return {}

    lunghezze = {len(dati) for dati in mercati.values()}
    if len(lunghezze) != 1:
        raise ValueError(
            "Per mescolare i mercati insieme devono avere lo stesso numero di barre: "
            "altrimenti la permutazione non sarebbe la stessa per tutti."
        )

    rng = np.random.default_rng(seed)
    quante = lunghezze.pop()
    if quante < 3:
        return {nome: dati.copy() for nome, dati in mercati.items()}
    ordine = rng.permutation(quante - 1)

    return {
        nome: _rimescola_con(dati, ordine) for nome, dati in mercati.items()
    }


def _rimescola_con(data: pd.DataFrame, ordine: np.ndarray) -> pd.DataFrame:
    """Ricostruisce una serie applicando un ordine di variazioni già deciso."""
    if "close" not in data.columns or len(data) < 3:
        return data.copy()

    close = data["close"].astype(float)
    variazioni = close.pct_change().to_numpy()[1:]
    partenza = float(close.iloc[0])
    nuovi = np.concatenate([[partenza], partenza * np.cumprod(1.0 + variazioni[ordine])])

    mescolata = pd.DataFrame(index=data.index)
    mescolata["close"] = nuovi
    rapporto = nuovi / close.to_numpy()
    for colonna in ("open", "high", "low"):
        if colonna in data.columns:
            mescolata[colonna] = data[colonna].astype(float).to_numpy() * rapporto
    if "volume" in data.columns:
        mescolata["volume"] = data["volume"].to_numpy()
    return mescolata


def valuta_contro_il_caso(
    margine_vero_pct: float, margini_del_caso_pct: list[float]
) -> EsitoProvaDelCaso:
    """Confronta il margine vero con quello che la fortuna ha saputo produrre."""
    esito = EsitoProvaDelCaso(
        prove=len(margini_del_caso_pct),
        margine_vero_pct=round(float(margine_vero_pct), 2),
        margini_del_caso_pct=[round(float(m), 2) for m in margini_del_caso_pct],
    )
    if not margini_del_caso_pct:
        esito.verdetto = "Prova del caso non eseguita."
        return esito

    caso = esito.margine_del_caso_pct
    vantaggio = esito.margine_vero_pct - caso
    supera_asticella = esito.margine_vero_pct >= esito.asticella_pct
    esito.superato = supera_asticella and esito.prove >= PROVE_MINIME_PER_VITTORIA

    # Poche prove non possono produrre un sì, ma possono benissimo produrre un
    # no: bocciare con pochi rimescolamenti è sicuro, perché aggiungendone altri
    # l'asticella può solo alzarsi. È il sì che va protetto — il massimo di due
    # estrazioni molto sparse promuove per sorteggio, e misurandolo su un mercato
    # senza struttura le prime due prove davano −2,2 mentre il soffitto vero
    # della fortuna era +20,8.
    if supera_asticella and esito.prove < PROVE_MINIME_PER_VITTORIA:
        esito.verdetto = (
            f"Con {esito.prove} rimescolament{'o' if esito.prove == 1 else 'i'} non si può "
            f"dire se questo risultato ({esito.margine_vero_pct:+.1f} punti sul mercato) "
            f"valga più della fortuna: quello che la fortuna produce cambia molto da una "
            f"prova all'altra, e il meglio di poche prove non descrive quanto può arrivare "
            f"a fare. Servono almeno {PROVE_MINIME_PER_VITTORIA} rimescolamenti per "
            f"pronunciarsi. Finora la fortuna è arrivata a {caso:+.1f}."
        )
        return esito

    if esito.superato:
        esito.verdetto = (
            f"Rimescolando la storia {esito.prove} volte, cercando ogni volta fra le stesse "
            f"identiche opzioni, la fortuna arriva al massimo a {caso:+.1f} punti sul "
            f"mercato. Questa strategia ne fa {esito.margine_vero_pct:+.1f}: "
            f"{vantaggio:.1f} punti in più di quanto si ottiene per caso, abbastanza da "
            f"restare davanti anche tenendo conto di quanto la fortuna balla fra una prova "
            f"e l'altra. È il segnale più incoraggiante che questo strumento sappia dare."
        )
    elif vantaggio < 0:
        # La fortuna ha fatto meglio: dire "quanto questa strategia" sarebbe
        # falso, ed e' il caso in cui c'e' meno da fidarsi di tutti.
        esito.verdetto = (
            f"Rimescolando la storia, cercando fra le stesse identiche opzioni, la fortuna "
            f"arriva a {caso:+.1f} punti sul mercato, cioè {abs(vantaggio):.1f} punti "
            f"più di questa strategia ({esito.margine_vero_pct:+.1f}). Su dati in cui non "
            "c'era niente da trovare si è ottenuto di più che su quelli veri: non c'è "
            "niente da cui fidarsi."
        )
    else:
        ballo = (
            f" Da una prova all'altra la fortuna ha ballato di {esito.dispersione_pct:.1f} "
            f"punti, quindi per parlare di vittoria ne servivano {esito.asticella_pct:+.1f}."
            if esito.dispersione_pct
            else ""
        )
        esito.verdetto = (
            f"Rimescolando la storia, cercando fra le stesse identiche opzioni, la fortuna "
            f"arriva a {caso:+.1f} punti sul mercato — quanto questa strategia "
            f"({esito.margine_vero_pct:+.1f}). Vuol dire che il risultato trovato è quello che "
            "salta fuori comunque quando si provano migliaia di combinazioni: non c'è niente "
            "da cui fidarsi." + ballo
        )
    return esito
