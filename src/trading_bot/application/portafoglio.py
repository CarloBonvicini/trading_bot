"""Il metro di paragone onesto: dividere i soldi e stare fermi.

Ogni strategia veniva confrontata col comprare-e-tenere **dello stesso singolo
titolo**. Ma una persona con diecimila euro non compra un titolo solo: li
divide fra le cose che sta guardando. Battere SPY da soli è una domanda; battere
"tutti i mercati che ho in lista, in parti uguali" è un'altra, ed è quella vera
— perché è la cosa che chiunque può fare senza strumenti, senza tempo e senza
pagare commissioni ogni settimana.

Qui si costruiscono due versioni di quella cosa noiosa:

- **diviso e fermo**: si compra all'inizio in parti uguali e non si tocca più
  niente. I pesi si sbilanciano da soli (chi sale pesa di più).
- **diviso e ribilanciato**: ogni mese si riportano le quote in parti uguali,
  cioè si vende un po' di quello che è salito e si compra quello che è sceso.

Nessuna delle due è un consiglio: sono il pavimento sotto cui una strategia non
ha motivo di esistere.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class RisultatoPortafoglio:
    """Come sarebbe andata dividendo i soldi fra i mercati in esame."""

    mercati: list[str]
    barre: int
    rendimento_fermo_pct: float
    calo_peggiore_fermo_pct: float
    rendimento_ribilanciato_pct: float
    calo_peggiore_ribilanciato_pct: float

    @property
    def rendimento_migliore_pct(self) -> float:
        """La più efficace delle due versioni noiose: è quella da battere."""
        return max(self.rendimento_fermo_pct, self.rendimento_ribilanciato_pct)


def costruisci_portafoglio(
    chiusure: dict[str, pd.Series],
    *,
    ultima_frazione: float = 0.20,
    ribilancia_ogni: str = "M",
) -> RisultatoPortafoglio | None:
    """Divide il capitale in parti uguali fra i mercati e misura come va.

    ``ultima_frazione`` ritaglia lo stesso tratto finale usato dalle ricerche
    come prova su dati nuovi, così il confronto è fra periodi uguali. Serve
    almeno un secondo mercato: con uno solo non c'è niente da diversificare.
    """
    serie = {nome: s.dropna() for nome, s in chiusure.items() if s is not None and len(s) > 2}
    if len(serie) < 2:
        return None

    prezzi = pd.DataFrame(serie).dropna()
    if len(prezzi) < 10:
        return None

    taglio = max(1, int(round(len(prezzi) * ultima_frazione)))
    prezzi = prezzi.iloc[-taglio:]
    if len(prezzi) < 3:
        return None

    rendimenti = prezzi.pct_change().fillna(0.0)
    quota = 1.0 / len(prezzi.columns)

    # Diviso e fermo: si compra all'inizio e non si tocca piu' niente, quindi
    # i pesi si sbilanciano da soli man mano che i mercati divergono.
    fermo = (prezzi / prezzi.iloc[0] * quota).sum(axis=1)

    # Diviso e ribilanciato: ogni mese si riportano le quote in parti uguali.
    gruppi = prezzi.index.to_period(ribilancia_ogni)
    ribilanciato = pd.Series(1.0, index=prezzi.index)
    valore = 1.0
    for _, blocco in rendimenti.groupby(gruppi, sort=False):
        andamento = (1.0 + blocco).cumprod().mul(quota).sum(axis=1)
        ribilanciato.loc[blocco.index] = valore * andamento
        valore = float(ribilanciato.loc[blocco.index].iloc[-1])

    return RisultatoPortafoglio(
        mercati=list(prezzi.columns),
        barre=int(len(prezzi)),
        rendimento_fermo_pct=_rendimento(fermo),
        calo_peggiore_fermo_pct=_calo_peggiore(fermo),
        rendimento_ribilanciato_pct=_rendimento(ribilanciato),
        calo_peggiore_ribilanciato_pct=_calo_peggiore(ribilanciato),
    )


def _rendimento(curva: pd.Series) -> float:
    return round(float(curva.iloc[-1] / curva.iloc[0] - 1.0) * 100, 2)


def _calo_peggiore(curva: pd.Series) -> float:
    return round(float((curva / curva.cummax() - 1.0).min()) * 100, 2)
