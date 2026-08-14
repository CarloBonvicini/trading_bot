"""Nessuna strategia può vedere il futuro.

È il difetto più pericoloso di un backtest, perché non fallisce: produce un
risultato splendido e inservibile. Un indicatore centrato, una soglia calcolata
sull'intera serie, una media che guarda avanti di una barra — e la curva sale
bellissima su dati che nella realtà non erano ancora disponibili.

Il controllo qui è meccanico e non richiede di leggere il codice: si calcola il
segnale sulla serie intera, poi lo si ricalcola su una serie **troncata** al
punto k. Se la strategia guarda solo indietro, i primi k valori devono essere
identici; se cambiano, da qualche parte stava usando il futuro.

Questa proprietà diventa cruciale con i modelli che stimano i propri parametri
dai dati: è lì che è facilissimo stimare "su tutta la serie" e non accorgersene.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.strategies import STRATEGY_SPECS, build_strategy_signal

TUTTE = sorted(STRATEGY_SPECS)
# Dove si taglia la serie: abbastanza avanti da avere indicatori già avviati.
TAGLIO = 320


def _mercato(n: int = 500, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    chiusure = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, n)))
    idx = pd.bdate_range("2021-01-04", periods=n)
    close = pd.Series(chiusure, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "volume": pd.Series(rng.integers(1000, 5000, n).astype(float), index=idx),
        }
    )


@pytest.mark.parametrize("strategy_id", TUTTE)
@pytest.mark.parametrize("consenti_short", [False, True])
def test_il_passato_non_cambia_se_cambia_il_futuro(
    strategy_id: str, consenti_short: bool
) -> None:
    """La prova: troncare la serie non deve toccare i valori già calcolati."""
    completo = _mercato()
    troncato = completo.iloc[:TAGLIO]
    parametri = STRATEGY_SPECS[strategy_id].defaults()

    intero = build_strategy_signal(
        strategy_id=strategy_id, data=completo, parameters=parametri,
        consenti_short=consenti_short,
    ).iloc[:TAGLIO]
    parziale = build_strategy_signal(
        strategy_id=strategy_id, data=troncato, parameters=parametri,
        consenti_short=consenti_short,
    )

    differenze = (intero.to_numpy() != parziale.to_numpy()).sum()
    assert differenze == 0, (
        f"{strategy_id}: {differenze} barre su {TAGLIO} cambiano quando si aggiunge "
        "il futuro. La strategia sta usando dati che a quel momento non esistevano."
    )


@pytest.mark.parametrize("strategy_id", TUTTE)
def test_stravolgere_il_futuro_non_tocca_il_passato(strategy_id: str) -> None:
    """Controllo più severo del troncamento: il futuro c'è, ma è un altro.

    Se una strategia stimasse una soglia sull'intera serie, il troncamento
    potrebbe non bastare a smascherarla — mentre un futuro completamente diverso
    sposterebbe quella soglia e con essa tutto il passato.
    """
    completo = _mercato()
    stravolto = completo.copy()
    # Da metà in poi il mercato diventa un'altra cosa: dieci volte più mosso.
    coda = stravolto.index[TAGLIO:]
    fattore = pd.Series(
        np.linspace(1.0, 4.0, len(coda)) * np.tile([1.0, 0.6], len(coda))[: len(coda)],
        index=coda,
    )
    for colonna in ("open", "high", "low", "close"):
        stravolto.loc[coda, colonna] = stravolto.loc[coda, colonna] * fattore

    parametri = STRATEGY_SPECS[strategy_id].defaults()
    originale = build_strategy_signal(
        strategy_id=strategy_id, data=completo, parameters=parametri
    ).iloc[:TAGLIO]
    con_altro_futuro = build_strategy_signal(
        strategy_id=strategy_id, data=stravolto, parameters=parametri
    ).iloc[:TAGLIO]

    differenze = (originale.to_numpy() != con_altro_futuro.to_numpy()).sum()
    assert differenze == 0, (
        f"{strategy_id}: {differenze} barre del passato cambiano se si stravolge il "
        "futuro. Da qualche parte la strategia guarda avanti."
    )


def test_il_controllo_riconosce_una_strategia_che_bara() -> None:
    """Un test che non fallisce mai non protegge niente.

    Qui si costruisce di proposito una strategia che guarda una barra avanti —
    l'errore classico, uno shift col segno sbagliato — e si verifica che il
    controllo la smaschera.
    """
    dati = _mercato()

    def strategia_che_bara(data: pd.DataFrame) -> pd.Series:
        # Compra oggi se domani il prezzo sale: nella realtà è impossibile.
        return (data["close"].shift(-1) > data["close"]).astype(float)

    intero = strategia_che_bara(dati).iloc[:TAGLIO]
    parziale = strategia_che_bara(dati.iloc[:TAGLIO])

    assert (intero.to_numpy() != parziale.to_numpy()).sum() > 0, (
        "il controllo non si accorge nemmeno di una strategia che guarda "
        "esplicitamente il futuro: non protegge niente"
    )
