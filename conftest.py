"""Configurazione condivisa dei test.

Tre compiti:

1. **Guardia sul codice collaudato.** Il pacchetto è installato in editable
   mode e punta al checkout principale: qualunque import di ``trading_bot``
   fatto senza accortezze finisce lì, anche lavorando in un worktree. I test
   sono al riparo perché ``pythonpath = ["src"]`` nel pyproject è relativo alla
   rootdir, ma se un giorno quella riga sparisse la suite passerebbe collaudando
   in silenzio un altro codice. Qui lo verifichiamo e ci fermiamo subito.

2. **Test lenti fuori dal giro veloce.** Alcuni test eseguono ricerche vere e da
   soli valgono più di un minuto: sono marcati ``lento`` e girano solo con
   ``--lenti`` (la CI li esegue sempre).

3. **Dati sintetici condivisi**, prima duplicati in quattro file di test.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ── 1. Guardia sul codice collaudato ─────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    import trading_bot

    modulo = Path(trading_bot.__file__).resolve()
    atteso = (Path(config.rootpath) / "src").resolve()
    if atteso not in modulo.parents:
        raise pytest.UsageError(
            "I test importerebbero un altro checkout del progetto:\n"
            f"  trading_bot caricato da: {modulo}\n"
            f"  atteso sotto:            {atteso}\n"
            "Succede quando l'installazione in editable mode punta altrove. "
            "Lancia i test con `python -m pytest` dalla radice del progetto, "
            "oppure crea un ambiente virtuale qui dentro:\n"
            "  python -m venv .venv\n"
            "  .venv\\Scripts\\python -m pip install -e .[dev]"
        )


# ── 2. Test lenti ────────────────────────────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--lenti",
        action="store_true",
        default=False,
        help="Esegue anche i test marcati 'lento' (ricerche vere, ~1 minuto).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--lenti"):
        return
    salta = pytest.mark.skip(reason="test lento: aggiungi --lenti per eseguirlo")
    for item in items:
        if "lento" in item.keywords:
            item.add_marker(salta)


# ── 3. Dati sintetici ────────────────────────────────────────────────────────

def _mercato_sintetico(
    n: int = 320,
    seed: int = 1,
    deriva: float = 50.0,
    rumore: float = 1.2,
    inizio: str = "2022-01-01",
) -> pd.DataFrame:
    """Serie OHLCV sintetica: tendenza lineare più rumore accumulato.

    ``deriva`` è quanto sale il prezzo da inizio a fine (in punti, partendo da
    100), ``rumore`` la deviazione standard degli scarti giornalieri prima
    dell'accumulo. Con lo stesso ``seed`` la serie è identica a ogni giro.
    """
    rng = np.random.default_rng(seed)
    chiusure = np.linspace(100.0, 100.0 + deriva, n) + rng.normal(0.0, rumore, n).cumsum() * 0.3
    return pd.DataFrame(
        {
            "open": chiusure,
            "high": chiusure + 1.0,
            "low": chiusure - 1.0,
            "close": chiusure,
            "volume": rng.integers(1000, 5000, n),
        },
        index=pd.date_range(inizio, periods=n, freq="D"),
    )


def _ohlc_da_chiusure(
    chiusure: list[float],
    spread: float = 1.0,
    massimi: list[float] | None = None,
    minimi: list[float] | None = None,
) -> pd.DataFrame:
    """OHLC costruito attorno a chiusure date a mano.

    Senza ``massimi``/``minimi`` high e low stanno a ``spread`` dal close; per i
    test sui canali (Donchian) si passano espliciti.
    """
    return pd.DataFrame(
        {
            "close": chiusure,
            "high": massimi if massimi is not None else [c + spread for c in chiusure],
            "low": minimi if minimi is not None else [c - spread for c in chiusure],
        },
        index=pd.date_range("2024-01-01", periods=len(chiusure), freq="D"),
    )


def _mercato_piatto(n: int = 80) -> pd.DataFrame:
    """Mercato fermo: high == low == close e volume costante.

    È il caso che azzera i denominatori degli indicatori (ampiezza del canale,
    ATR, flusso negativo) e che faceva degradare le serie a dtype "object".
    """
    prezzo = [100.0] * n
    return pd.DataFrame(
        {"open": prezzo, "high": prezzo, "low": prezzo, "close": prezzo,
         "volume": [1000.0] * n},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


@pytest.fixture
def mercato_sintetico():
    """Fabbrica di serie OHLCV sintetiche: vedi ``_mercato_sintetico``."""
    return _mercato_sintetico


@pytest.fixture
def ohlc_da_chiusure():
    """Fabbrica di OHLC da una lista di chiusure: vedi ``_ohlc_da_chiusure``."""
    return _ohlc_da_chiusure


@pytest.fixture
def mercato_piatto():
    """Fabbrica di mercati fermi: vedi ``_mercato_piatto``."""
    return _mercato_piatto
