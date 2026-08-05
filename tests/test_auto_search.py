"""Test per la ricerca automatica multi-mercato e l'esecuzione in background."""
from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trading_bot.application.multi_search import MultiMarketSearchResult, run_multi_market_search
from trading_bot.application.search_jobs import (
    get_job,
    job_status,
    list_saved_searches,
    resume_search_job,
    start_multi_search_job,
)
from trading_bot.application.strategy_search import chiave_candidato, to_serializable

_STRATS = ["sma_cross", "ema_cross", "rsi_mean_reversion"]


def _fake_download_factory(mapping):
    def _download(symbol, start, end, interval):
        return mapping[symbol]
    return _download


@pytest.mark.lento
def test_run_multi_market_search_aggregates_across_markets(mercato_sintetico) -> None:
    mapping = {"AAA": mercato_sintetico(seed=1, deriva=60), "BBB": mercato_sintetico(seed=2, deriva=40), "CCC": mercato_sintetico(seed=3, deriva=-10)}
    result = run_multi_market_search(
        ["aaa", "bbb", "ccc"], interval="1d", fee_bps=0.0,
        strategy_ids=_STRATS, download_data=_fake_download_factory(mapping),
    )

    assert isinstance(result, MultiMarketSearchResult)
    assert result.symbols == ["AAA", "BBB", "CCC"]
    assert len(result.markets) == 3
    # Ogni strategia testata compare nel punteggio aggregato con il conteggio mercati.
    assert len(result.strategy_scores) == len(_STRATS)
    for score in result.strategy_scores:
        assert score.markets_tested == 3
        assert 0 <= score.markets_reliable <= 3
    # La classifica è ordinata per robustezza (affidabile, poi meglio del
    # mercato, poi margine medio sul comprare-e-tenere).
    keys = [
        (s.markets_reliable, s.markets_beat_market, s.avg_holdout_excess_pct)
        for s in result.strategy_scores
    ]
    assert keys == sorted(keys, reverse=True)
    assert result.verdict_note


@pytest.mark.lento
def test_run_multi_market_search_skips_broken_symbol(mercato_sintetico) -> None:
    mapping = {"AAA": mercato_sintetico(seed=1)}

    def _download(symbol, start, end, interval):
        if symbol == "BAD":
            raise ValueError("nessun dato")
        return mapping[symbol]

    result = run_multi_market_search(
        ["AAA", "BAD"], interval="1d", fee_bps=0.0,
        strategy_ids=_STRATS, download_data=_download,
    )
    outcomes = {m.symbol: m for m in result.markets}
    assert outcomes["BAD"].error is not None
    assert outcomes["AAA"].error is None


@pytest.mark.lento
def test_multi_market_result_is_json_serializable(mercato_sintetico) -> None:
    mapping = {"AAA": mercato_sintetico(seed=1, deriva=60)}
    result = run_multi_market_search(
        ["AAA"], interval="1d", fee_bps=0.0,
        strategy_ids=_STRATS, download_data=_fake_download_factory(mapping),
    )
    payload = to_serializable(result)
    # Non deve contenere valori non finiti (inf/nan romperebbero il JSON).
    json.dumps(payload)
    assert payload["symbols"] == ["AAA"]


def test_start_multi_search_job_runs_in_background_and_persists(tmp_path: Path, monkeypatch, mercato_sintetico) -> None:
    mapping = {"AAA": mercato_sintetico(seed=1, deriva=60), "BBB": mercato_sintetico(seed=2, deriva=40)}
    monkeypatch.setattr(
        "trading_bot.application.multi_search.download_price_data",
        _fake_download_factory(mapping),
    )

    job_id = start_multi_search_job(
        symbols=["AAA", "BBB"], interval="1d", initial_capital=10_000.0, fee_bps=0.0,
        scan_mode="rapida", start="", end="", reports_dir=tmp_path,
    )

    # Attende il completamento del thread (con timeout di sicurezza).
    deadline = time.time() + 60
    status = job_status(job_id, tmp_path)
    while status and status["status"] == "running" and time.time() < deadline:
        time.sleep(0.5)
        status = job_status(job_id, tmp_path)

    assert status is not None and status["status"] == "done"

    job = get_job(job_id, tmp_path)
    assert job["result"]["symbols"] == ["AAA", "BBB"]
    # Il risultato è stato salvato su disco e resta caricabile.
    assert (tmp_path / "auto_searches" / f"{job_id}.json").exists()


@pytest.mark.lento
def test_search_counts_combinations_while_working(mercato_sintetico) -> None:
    """L'avanzamento conta le combinazioni provate (non le strategie finite),
    così l'utente vede un numero che sale invece di scatti da 15 passi."""
    from trading_bot.application.strategy_search import (
        estimate_search_combinations,
        run_strategy_search,
    )

    data = mercato_sintetico(seed=1, deriva=60)
    eventi: list[tuple[int, int, str]] = []
    # Su un solo processo: è il percorso che annuncia la strategia in corso
    # (in parallelo le strategie girano insieme e l'etichetta è complessiva).
    run_strategy_search(
        data=data, symbol="AAA", fee_bps=0.0,
        strategy_ids=_STRATS, max_workers=1,
        progress_callback=lambda done, total, label: eventi.append((done, total, label)),
    )

    atteso = estimate_search_combinations(len(data), strategy_ids=_STRATS)
    assert atteso > 0
    # Il primo evento annuncia la strategia in corso prima di iniziare a contare.
    assert eventi[0][0] == 0
    assert eventi[0][2] == "SMA Crossover"
    # Il totale annunciato coincide con la stima mostrata all'utente.
    assert {e[1] for e in eventi} == {atteso}
    # Il contatore sale sempre e arriva esattamente al totale.
    assert [e[0] for e in eventi] == sorted(e[0] for e in eventi)
    assert eventi[-1][0] == atteso
    # Ci sono aggiornamenti intermedi: non è un salto unico da 0 a fine.
    assert len([e for e in eventi if 0 < e[0] < atteso]) > 3


def test_estimate_search_combinations_grows_with_depth() -> None:
    """Più la profondità è alta, più opzioni vengono controllate."""
    from trading_bot.application.strategy_search import estimate_search_combinations

    rapida = estimate_search_combinations(320, scan_mode="rapida", strategy_ids=_STRATS)
    media = estimate_search_combinations(320, scan_mode="media", strategy_ids=_STRATS)
    lunga = estimate_search_combinations(320, scan_mode="lunga", strategy_ids=_STRATS)

    assert 0 < rapida < media < lunga


def test_job_status_reports_elapsed_and_remaining(tmp_path: Path) -> None:
    """Fra un passo e l'altro possono passare minuti: lo stato deve dire da
    quanto sta girando e quanto manca."""
    from datetime import datetime, timedelta

    from trading_bot.application import search_jobs

    search_jobs._JOBS["fake"] = {
        "id": "fake", "status": "running", "progress": 3, "total": 15,
        "message": "SPY · MACD Trend", "error": None,
        "started_at": (datetime.now() - timedelta(seconds=60)).isoformat(timespec="seconds"),
    }
    try:
        status = job_status("fake", tmp_path)
    finally:
        search_jobs._JOBS.pop("fake", None)

    assert status["elapsed_seconds"] >= 59
    # 3 passi in 60s → i 12 rimanenti richiedono circa 240s.
    assert 200 <= status["remaining_seconds"] <= 280


def test_list_saved_searches_returns_newest_first(tmp_path: Path) -> None:
    directory = tmp_path / "auto_searches"
    directory.mkdir(parents=True)
    for job_id, saved_at, symbols in (
        ("vecchia", "2026-07-01T09:00:00", ["SPY"]),
        ("nuova", "2026-07-24T18:15:00", ["AAPL", "MSFT"]),
    ):
        (directory / f"{job_id}.json").write_text(
            json.dumps({
                "id": job_id, "saved_at": saved_at,
                "result": {
                    "symbols": symbols,
                    "overall_champion_label": "SMA Crossover",
                    "markets": [{"reliability": "alta"}] * len(symbols),
                },
            }),
            encoding="utf-8",
        )

    searches = list_saved_searches(tmp_path)

    assert [s["id"] for s in searches] == ["nuova", "vecchia"]
    assert searches[0]["symbols_display"] == "AAPL, MSFT"
    assert searches[0]["markets_reliable"] == 2
    assert searches[0]["saved_at_display"] == "24/07/2026 18:15"


def test_list_saved_searches_is_empty_without_directory(tmp_path: Path) -> None:
    assert list_saved_searches(tmp_path) == []


def test_list_saved_searches_prefers_champion_aggregate(tmp_path: Path) -> None:
    """Il conteggio mostrato deve venire dall'aggregato del campione (stessa
    fonte della frase di verdetto), non dalle schede per-mercato."""
    directory = tmp_path / "auto_searches"
    directory.mkdir(parents=True)
    (directory / "x.json").write_text(
        json.dumps({
            "id": "x", "saved_at": "2026-07-24T12:00:00",
            "result": {
                "symbols": ["SPY", "AAPL"],
                "overall_champion_id": "keltner_reversion",
                "overall_champion_label": "Keltner Reversion",
                # Schede con il campione locale (vecchio formato): direbbero 0.
                "markets": [{"reliability": "bassa"}, {"reliability": "bassa"}],
                "strategy_scores": [
                    {"strategy_id": "keltner_reversion", "markets_reliable": 2, "markets_tested": 2},
                ],
            },
        }),
        encoding="utf-8",
    )

    search = list_saved_searches(tmp_path)[0]

    assert search["markets_reliable"] == 2
    assert search["markets_count"] == 2


@pytest.mark.lento
def test_checkpoint_lets_search_skip_already_computed_strategies(mercato_sintetico) -> None:
    """Il cuore della ripresa: le strategie già salvate non vengono ricalcolate."""
    from trading_bot.application.strategy_search import run_strategy_search

    data = mercato_sintetico(seed=1, deriva=60)
    # Prima passata completa: raccoglie le righe da riusare.
    completa = run_strategy_search(data=data, symbol="AAA", fee_bps=0.0, strategy_ids=_STRATS)
    salvate = {
        chiave_candidato(r): dataclasses.asdict(r)
        for r in completa.ranking
        if r.strategy_id in {"sma_cross", "ema_cross"}
    }

    combinazioni: list[int] = []
    ripresa = run_strategy_search(
        data=data, symbol="AAA", fee_bps=0.0, strategy_ids=_STRATS,
        precomputed_rows=salvate,
        progress_callback=lambda done, total, label: combinazioni.append(done),
    )

    # Stesso esito della passata completa...
    assert ripresa.champion_id == completa.champion_id
    assert {r.strategy_id for r in ripresa.ranking} == {r.strategy_id for r in completa.ranking}
    # ...ma le due strategie salvate risultano già conteggiate fin dall'inizio,
    # quindi il contatore parte molto avanti invece che da zero.
    assert combinazioni[0] > 0


@pytest.mark.lento
def test_job_saves_partial_progress_and_can_be_resumed(tmp_path: Path, monkeypatch, mercato_sintetico) -> None:
    """Un lavoro interrotto lascia un checkpoint riprendibile, e la ripresa
    riusa i dati senza riscaricare i mercati già completati."""
    mapping = {"AAA": mercato_sintetico(seed=1, deriva=60)}
    monkeypatch.setattr(
        "trading_bot.application.multi_search.download_price_data",
        _fake_download_factory(mapping),
    )
    monkeypatch.setattr("trading_bot.application.multi_search.N_STRATEGIES", len(_STRATS))
    monkeypatch.setattr("trading_bot.application.search_jobs.N_STRATEGIES", len(_STRATS))

    # Simula un'interruzione: checkpoint scritto a mano con una strategia fatta.
    job_id = "ripresa1"
    parziale = run_strategy_search_rows(mapping["AAA"])
    directory = tmp_path / "auto_searches"
    directory.mkdir(parents=True)
    (directory / f"{job_id}.progress.json").write_text(
        json.dumps({
            "id": job_id,
            "updated_at": "2026-08-06T01:00:00",
            "params": {
                "symbols": ["AAA"], "interval": "1d", "initial_capital": 10000.0,
                "fee_bps": 0.0, "scan_mode": "rapida", "start": "", "end": "",
            },
            "markets": {"AAA": {"rows": parziale, "benchmark_return_pct": 1.0, "bars": 320}},
        }),
        encoding="utf-8",
    )

    # La home la mostra come interrotta e riprendibile.
    elenco = list_saved_searches(tmp_path)
    assert elenco[0]["interrupted"] is True
    assert elenco[0]["strategies_done"] == len(parziale)
    assert get_job(job_id, tmp_path)["status"] == "interrupted"

    assert resume_search_job(job_id, tmp_path) == job_id

    deadline = time.time() + 60
    status = job_status(job_id, tmp_path)
    while status and status["status"] == "running" and time.time() < deadline:
        time.sleep(0.4)
        status = job_status(job_id, tmp_path)

    assert status["status"] == "done"
    # A fine corsa il risultato sostituisce il checkpoint.
    assert (directory / f"{job_id}.json").exists()
    assert not (directory / f"{job_id}.progress.json").exists()
    # E non compare più come interrotta.
    assert all(not s["interrupted"] for s in list_saved_searches(tmp_path))


def run_strategy_search_rows(data) -> dict:
    """Righe di una sola strategia, come le salverebbe un lavoro interrotto."""
    from trading_bot.application.strategy_search import run_strategy_search

    parziale = run_strategy_search(data=data, symbol="AAA", fee_bps=0.0, strategy_ids=["sma_cross"])
    return {chiave_candidato(r): dataclasses.asdict(r) for r in parziale.ranking}


def test_get_job_loads_persisted_result_after_restart(tmp_path: Path) -> None:
    # Simula un risultato salvato da una sessione precedente (job non in memoria).
    directory = tmp_path / "auto_searches"
    directory.mkdir(parents=True)
    (directory / "abc123.json").write_text(
        json.dumps({"id": "abc123", "result": {"symbols": ["XYZ"], "markets": [], "strategy_scores": []}}),
        encoding="utf-8",
    )
    job = get_job("abc123", tmp_path)
    assert job is not None
    assert job["status"] == "done"
    assert job["result"]["symbols"] == ["XYZ"]


# ── Affidabilità misurata sul mercato, non sullo zero ────────────────────────

def test_affidabilita_confronta_col_mercato_non_con_lo_zero() -> None:
    """Regressione: in un periodo di prova al ribasso il motore (solo long) non
    può guadagnare in assoluto, quindi pretenderlo bocciava chiunque — comprese
    le strategie che avevano limitato le perdite."""
    from trading_bot.application.strategy_search import (
        RELIABILITY_LOW,
        RELIABILITY_MEDIUM,
        RELIABILITY_NONE,
        _reliability,
    )

    # Mercato -18%, strategia -5%: 13 punti risparmiati, non è una bocciatura.
    limita_i_danni = _reliability(
        dev_oos_sharpe=0.8, holdout_return_pct=-5.0, holdout_excess_return_pct=13.0,
        holdout_sharpe=-0.2, holdout_trades=6,
    )
    assert limita_i_danni == RELIABILITY_MEDIUM

    # Guadagna il 4% ma il mercato ha fatto +12%: non ha aggiunto niente.
    peggio_del_mercato = _reliability(
        dev_oos_sharpe=0.8, holdout_return_pct=4.0, holdout_excess_return_pct=-8.0,
        holdout_sharpe=0.5, holdout_trades=6,
    )
    assert peggio_del_mercato == RELIABILITY_LOW

    # Senza operazioni non c'è niente da giudicare.
    assert _reliability(
        dev_oos_sharpe=0.8, holdout_return_pct=0.0, holdout_excess_return_pct=18.0,
        holdout_sharpe=0.0, holdout_trades=0,
    ) == RELIABILITY_NONE


def test_affidabilita_alta_richiede_guadagno_e_tenuta() -> None:
    from trading_bot.application.strategy_search import (
        RELIABILITY_HIGH,
        RELIABILITY_MEDIUM,
        _reliability,
    )

    assert _reliability(
        dev_oos_sharpe=1.0, holdout_return_pct=14.0, holdout_excess_return_pct=6.0,
        holdout_sharpe=0.9, holdout_trades=8,
    ) == RELIABILITY_HIGH
    # Stesso guadagno ma crollo rispetto allo sviluppo: promettente, non solida.
    assert _reliability(
        dev_oos_sharpe=2.0, holdout_return_pct=14.0, holdout_excess_return_pct=6.0,
        holdout_sharpe=0.4, holdout_trades=8,
    ) == RELIABILITY_MEDIUM


def test_classifica_multi_mercato_conta_chi_batte_il_mercato() -> None:
    """L'aggregato deve contare i mercati battuti, non quelli chiusi in positivo."""
    from trading_bot.application.multi_search import _aggregate
    from trading_bot.application.strategy_search import Candidato

    scores = _aggregate({
        Candidato("sma_cross", False): {
            # Perde meno del mercato in entrambi: due mercati battuti.
            "returns": [-4.0, -6.0], "excess": [10.0, 8.0],
            "dev_sharpe": [0.4, 0.3], "reliable": 0, "beat": 2,
        },
        Candidato("ema_cross", False): {
            # Guadagna, ma meno del mercato: nessun mercato battuto.
            "returns": [5.0, 7.0], "excess": [-6.0, -4.0],
            "dev_sharpe": [0.9, 0.8], "reliable": 0, "beat": 0,
        },
    })

    assert [s.strategy_id for s in scores] == ["sma_cross", "ema_cross"]
    assert scores[0].markets_beat_market == 2
    assert scores[0].avg_holdout_excess_pct == 9.0


def test_le_due_versioni_della_stessa_strategia_restano_separate() -> None:
    """La stessa strategia al rialzo e nei due versi sono due candidati: i loro
    risultati non devono finire nello stesso mucchio."""
    from trading_bot.application.multi_search import _aggregate
    from trading_bot.application.strategy_search import Candidato

    scores = _aggregate({
        Candidato("sma_cross", False): {
            "returns": [2.0], "excess": [1.0], "dev_sharpe": [0.2],
            "reliable": 0, "beat": 1, "label": "SMA Crossover",
        },
        Candidato("sma_cross", True): {
            "returns": [20.0], "excess": [18.0], "dev_sharpe": [1.2],
            "reliable": 1, "beat": 1, "label": "SMA Crossover · anche al ribasso",
        },
    })

    assert len(scores) == 2
    # Vince la versione che regge su dati nuovi, e si vede dall'etichetta.
    assert scores[0].consenti_short is True
    assert "ribasso" in scores[0].label
    assert scores[1].consenti_short is False


@pytest.mark.lento
def test_ricerca_in_parallelo_da_lo_stesso_risultato(monkeypatch, mercato_sintetico) -> None:
    """Il parallelismo è solo velocità: campione, parametri e classifica devono
    coincidere con l'esecuzione su un solo processo."""
    from trading_bot.application.strategy_search import run_strategy_search

    data = mercato_sintetico(n=400, seed=4, deriva=45)
    comuni = dict(data=data, symbol="AAA", fee_bps=0.0, strategy_ids=_STRATS)

    sequenziale = run_strategy_search(**comuni, max_workers=1)
    parallelo = run_strategy_search(**comuni, max_workers=2)

    assert parallelo.champion_id == sequenziale.champion_id
    assert parallelo.champion_params == sequenziale.champion_params
    assert [r.strategy_id for r in parallelo.ranking] == [
        r.strategy_id for r in sequenziale.ranking
    ]
    assert parallelo.reliability == sequenziale.reliability


@pytest.mark.lento
def test_avanzamento_arriva_al_totale_anche_in_parallelo(mercato_sintetico) -> None:
    from trading_bot.application.strategy_search import (
        estimate_search_combinations,
        run_strategy_search,
    )

    data = mercato_sintetico(n=400, seed=4, deriva=45)
    eventi: list[tuple[int, int, str]] = []
    run_strategy_search(
        data=data, symbol="AAA", fee_bps=0.0, strategy_ids=_STRATS, max_workers=2,
        progress_callback=lambda done, total, label: eventi.append((done, total, label)),
    )

    atteso = estimate_search_combinations(len(data), strategy_ids=_STRATS)
    assert [e[0] for e in eventi] == sorted(e[0] for e in eventi)
    assert eventi[-1][0] == atteso
    assert all(e[0] <= atteso for e in eventi)


# ── Ricerca con il ribasso attivo ────────────────────────────────────────────

def _mercato_in_discesa(n: int = 400, seed: int = 3) -> pd.DataFrame:
    """Mercato che scende: comprando e basta si perde, quindi è il caso in cui
    il ribasso dovrebbe fare la differenza."""
    rng = np.random.default_rng(seed)
    chiusure = 100.0 * np.exp(np.cumsum(rng.normal(-0.0035, 0.015, n)))
    return pd.DataFrame(
        {"open": chiusure, "high": chiusure * 1.008, "low": chiusure * 0.992,
         "close": chiusure, "volume": rng.integers(1000, 5000, n).astype(float)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def test_costruisci_candidati_raddoppia_col_ribasso() -> None:
    from trading_bot.application.strategy_search import costruisci_candidati

    solo_long = costruisci_candidati(_STRATS, consenti_short=False)
    entrambi = costruisci_candidati(_STRATS, consenti_short=True)

    assert [c.consenti_short for c in solo_long] == [False] * 3
    assert len(entrambi) == 6
    assert sum(c.consenti_short for c in entrambi) == 3
    # L'etichetta dice il verso, così in classifica le due righe si distinguono.
    ribassiste = [c for c in entrambi if c.consenti_short]
    assert all("ribasso" in c.label for c in ribassiste)


def test_stima_combinazioni_raddoppia_col_ribasso() -> None:
    from trading_bot.application.strategy_search import estimate_search_combinations

    solo_long = estimate_search_combinations(320, strategy_ids=_STRATS)
    entrambi = estimate_search_combinations(320, strategy_ids=_STRATS, consenti_short=True)

    assert entrambi == solo_long * 2


@pytest.mark.lento
def test_ricerca_col_ribasso_mette_in_gara_entrambi_i_versi() -> None:
    from trading_bot.application.strategy_search import run_strategy_search

    result = run_strategy_search(
        data=_mercato_in_discesa(), symbol="GIU", fee_bps=0.0,
        strategy_ids=_STRATS, consenti_short=True, max_workers=1,
    )

    versi = {(r.strategy_id, r.consenti_short) for r in result.ranking}
    assert len(versi) == 6  # tre strategie per due versi
    assert any(r.consenti_short for r in result.ranking)
    # Il campione dichiara in che verso ha corso.
    assert isinstance(result.champion_consenti_short, bool)


@pytest.mark.lento
def test_su_un_mercato_in_discesa_il_ribasso_vince() -> None:
    """La prova del nove: dove il mercato scende del 70%, comprare e basta non
    può funzionare, e la versione al ribasso deve risultare la migliore."""
    from trading_bot.application.strategy_search import run_strategy_search

    data = _mercato_in_discesa()
    result = run_strategy_search(
        data=data, symbol="GIU", fee_bps=0.0,
        strategy_ids=_STRATS, consenti_short=True, max_workers=1,
    )

    assert result.holdout_benchmark_return_pct < 0
    assert result.champion_consenti_short is True
    assert "ribasso" in (result.champion_label or "")


@pytest.mark.lento
def test_lo_slippage_arriva_fino_alla_ricerca(mercato_sintetico) -> None:
    """Se lo slippage non attraversasse tutta la catena, la ricerca sceglierebbe
    strategie iperattive che nella realtà si mangiano il guadagno in costi."""
    from trading_bot.application.strategy_search import run_strategy_search

    data = mercato_sintetico(n=400, seed=7, deriva=40)
    comuni = dict(data=data, symbol="AAA", fee_bps=0.0, strategy_ids=_STRATS, max_workers=1)

    senza = run_strategy_search(**comuni, slippage_bps=0.0)
    con = run_strategy_search(**comuni, slippage_bps=50.0)

    assert senza.settings["slippage_bps"] == 0.0
    assert con.settings["slippage_bps"] == 50.0
    # Con costi pesanti la resa su dati nuovi non può che peggiorare.
    rese_senza = {r.strategy_id: r.holdout_return_pct for r in senza.ranking if r.error is None}
    rese_con = {r.strategy_id: r.holdout_return_pct for r in con.ranking if r.error is None}
    comuni_ids = set(rese_senza) & set(rese_con)
    assert comuni_ids
    assert any(rese_con[sid] < rese_senza[sid] for sid in comuni_ids)
