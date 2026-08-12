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
# intera: due bastano per accorgersi dei casi palesi, cinque danno una misura
# più stabile.
PROVE_PREDEFINITE = 2
# Sotto questo margine di vantaggio sul caso non c'è niente da festeggiare.
MARGINE_SUL_CASO_MINIMO = 2.0


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
        """Il meglio che la fortuna è riuscita a fare: è il metro da battere."""
        return max(self.margini_del_caso_pct) if self.margini_del_caso_pct else 0.0


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
    esito.superato = vantaggio >= MARGINE_SUL_CASO_MINIMO

    if esito.superato:
        esito.verdetto = (
            f"Rimescolando la storia, cercando fra le stesse identiche opzioni, la fortuna "
            f"arriva al massimo a {caso:+.1f} punti sul mercato. Questa strategia ne fa "
            f"{esito.margine_vero_pct:+.1f}: {vantaggio:.1f} punti in più di quanto si "
            "ottiene per caso. È il segnale più incoraggiante che questo strumento sappia dare."
        )
    else:
        esito.verdetto = (
            f"Rimescolando la storia, cercando fra le stesse identiche opzioni, la fortuna "
            f"arriva a {caso:+.1f} punti sul mercato — quanto questa strategia "
            f"({esito.margine_vero_pct:+.1f}). Vuol dire che il risultato trovato è quello che "
            "salta fuori comunque quando si provano migliaia di combinazioni: non c'è niente "
            "da cui fidarsi."
        )
    return esito
