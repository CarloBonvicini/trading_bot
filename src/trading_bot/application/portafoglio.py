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

**Non è più un conto a parte.** Le due versioni sono due portafogli come tutti
gli altri — segnale sempre a uno su ogni mercato — e le calcola lo stesso
motore che misura le strategie. Se il metro di paragone avesse una matematica
sua, un giorno le due matematiche direbbero cose diverse e il confronto non
varrebbe niente. Come effetto, il ribilanciato mensile ora **paga le
commissioni** su ogni spostamento: prima era un avversario che ribilanciava
gratis, cioè più facile del vero.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.portafoglio import MAI, esegui_portafoglio


@dataclass
class RisultatoPortafoglio:
    """Come sarebbe andata dividendo i soldi fra i mercati in esame."""

    mercati: list[str]
    barre: int
    rendimento_fermo_pct: float
    calo_peggiore_fermo_pct: float
    rendimento_ribilanciato_pct: float
    calo_peggiore_ribilanciato_pct: float
    # Quanto i mercati si muovono insieme: dice se dividere è servito davvero o
    # se erano lo stesso mercato comprato più volte.
    quanto_si_muovono_insieme: float = 0.0
    # Quanto è costato ribilanciare ogni mese. Zero quando non si indicano
    # commissioni, ma non è più zero per costruzione.
    costi_ribilanciamento: float = 0.0

    @property
    def rendimento_migliore_pct(self) -> float:
        """La più efficace delle due versioni noiose: è quella da battere."""
        return max(self.rendimento_fermo_pct, self.rendimento_ribilanciato_pct)


def costruisci_portafoglio(
    chiusure: dict[str, pd.Series],
    *,
    ultima_frazione: float = 0.20,
    ribilancia_ogni: str = "M",
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> RisultatoPortafoglio | None:
    """Divide il capitale in parti uguali fra i mercati e misura come va.

    ``ultima_frazione`` ritaglia lo stesso tratto finale usato dalle ricerche
    come prova su dati nuovi, così il confronto è fra periodi uguali. Serve
    almeno un secondo mercato: con uno solo non c'è niente da diversificare.

    ``fee_bps`` e ``slippage_bps`` sono quelli con cui è stata misurata la
    strategia: il confronto ha senso solo se le due parti pagano lo stesso
    prezzo per operare.
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

    mercati = {nome: prezzi[[nome]].rename(columns={nome: "close"}) for nome in prezzi.columns}
    # Sempre dentro, su tutto: è esattamente cosa vuol dire "comprare e tenere".
    dentro = {nome: pd.Series(1.0, index=prezzi.index) for nome in prezzi.columns}

    def _noioso(ogni: str):
        return esegui_portafoglio(
            mercati, dentro, ribilancia_ogni=ogni, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )

    fermo = _noioso(MAI)
    ribilanciato = _noioso(ribilancia_ogni)

    return RisultatoPortafoglio(
        mercati=list(prezzi.columns),
        barre=int(len(prezzi)),
        rendimento_fermo_pct=float(fermo.summary["total_return_pct"]),
        calo_peggiore_fermo_pct=float(fermo.summary["max_drawdown_pct"]),
        rendimento_ribilanciato_pct=float(ribilanciato.summary["total_return_pct"]),
        calo_peggiore_ribilanciato_pct=float(ribilanciato.summary["max_drawdown_pct"]),
        quanto_si_muovono_insieme=float(fermo.summary["quanto_si_muovono_insieme"]),
        costi_ribilanciamento=round(
            float(ribilanciato.summary["trading_costs_paid"])
            - float(fermo.summary["trading_costs_paid"]),
            2,
        ),
    )
