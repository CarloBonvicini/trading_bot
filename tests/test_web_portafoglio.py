"""Il portafoglio arriva fino alla pagina, e la pagina dice le cose giuste."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from trading_bot.application import search_jobs
from trading_bot.web import create_app


def _mercato(seed: int, n: int = 700) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, n))),
        index=pd.bdate_range("2018-01-02", periods=n),
    )
    return pd.DataFrame(
        {"open": close, "high": close * 1.008, "low": close * 0.992, "close": close,
         "volume": pd.Series(1000.0, index=close.index)}
    )


def _attendi(job_id: str, reports_dir, secondi: float = 120.0) -> dict:
    scadenza = time.time() + secondi
    while time.time() < scadenza:
        job = search_jobs.get_portfolio_job(job_id, reports_dir)
        if job and job["status"] in {"done", "error"}:
            return job
        time.sleep(0.2)
    raise AssertionError("la ricerca di portafoglio non è finita in tempo")


def test_il_pulsante_per_dividere_i_soldi_e_nel_form(tmp_path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    pagina = app.test_client().get("/backtests/new").get_data(as_text=True)

    assert "/portfolios/start" in pagina
    assert "Dividi i soldi fra questi mercati" in pagina


def test_con_un_mercato_solo_lo_dice_invece_di_partire(tmp_path) -> None:
    """Un portafoglio da un mercato non è un portafoglio: meglio un messaggio
    chiaro che una ricerca che gira e poi fallisce."""
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    risposta = app.test_client().post(
        "/portfolios/start",
        data={"symbols": "SPY", "start": "2020-01-01", "end": "2024-12-31", "interval": "1d"},
    )

    assert risposta.status_code == 400
    assert "almeno due mercati" in risposta.get_data(as_text=True)


def test_una_ricerca_che_non_esiste_da_404(tmp_path) -> None:
    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    assert app.test_client().get("/portfolios/inesistente").status_code == 404


@pytest.mark.lento
def test_dal_form_alla_pagina_del_risultato(tmp_path, monkeypatch) -> None:
    """Il giro completo, senza rete: si preme il pulsante e alla fine si ottiene
    una pagina che dice in euro com'è andata."""
    dati = {"AAA": _mercato(1), "BBB": _mercato(2), "CCC": _mercato(3)}
    monkeypatch.setattr(
        search_jobs, "download_price_data",
        lambda symbol, start, end, interval: dati[symbol],
    )

    app = create_app({"TESTING": True, "REPORTS_DIR": tmp_path})
    client = app.test_client()
    risposta = client.post(
        "/portfolios/start",
        data={"symbols": "AAA, BBB, CCC", "start": "2018-01-01", "end": "2020-12-31",
              "interval": "1d", "initial_capital": "10000", "costi_operazione": "normale"},
    )

    assert risposta.status_code == 302
    job_id = risposta.headers["Location"].rstrip("/").split("/")[-1]
    job = _attendi(job_id, tmp_path)
    assert job["status"] == "done", job.get("error")

    pagina = client.get(f"/portfolios/{job_id}").get_data(as_text=True)
    assert "Come sarebbe andata dividendo i soldi" in pagina
    # Le due domande diverse devono restare distinte a colpo d'occhio.
    assert "Scelto senza sapere il futuro" in pagina
    assert "Il migliore col senno di poi" in pagina
    # Ogni metrica mostrata porta con sé la sua spiegazione, senza gergo.
    # (L'etichetta contiene un apostrofo, che il template trasforma in entità:
    # si cerca la parte che sopravvive alla trasformazione.)
    assert "Quanto i mercati vanno d" in pagina
    assert "In gergo: correlazione media a coppie" in pagina
    assert "Su quante cose eri dentro in media" in pagina
    # E il portafoglio è finito su disco, apribile con un foglio di calcolo.
    cartelle = [p for p in tmp_path.iterdir() if p.name.startswith("portafoglio-")]
    assert cartelle, "il portafoglio trovato non è stato salvato"
    attesi = {"summary.json", "metadata.json", "equity_curve.csv", "trades.csv", "pesi.csv"}
    assert attesi <= {f.name for f in cartelle[0].iterdir()}


@pytest.mark.lento
def test_le_ricerche_di_portafoglio_non_finiscono_fra_quelle_a_mercato_singolo(
    tmp_path, monkeypatch
) -> None:
    """Regressione: salvate nella stessa cartella, l'elenco delle ricerche
    salvate se le ritrovava dentro e provava a leggerle con la forma sbagliata."""
    dati = {"AAA": _mercato(1), "BBB": _mercato(2)}
    monkeypatch.setattr(
        search_jobs, "download_price_data",
        lambda symbol, start, end, interval: dati[symbol],
    )

    job_id = search_jobs.start_portfolio_search_job(
        symbols=["AAA", "BBB"], interval="1d", initial_capital=10_000.0, fee_bps=5.0,
        start="2018-01-01", end="2020-12-31", reports_dir=tmp_path,
    )
    _attendi(job_id, tmp_path)

    assert search_jobs.list_saved_searches(tmp_path) == []
