"""Test per la ricerca automatica multi-mercato e l'esecuzione in background."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from trading_bot.application.multi_search import MultiMarketSearchResult, run_multi_market_search
from trading_bot.application.search_jobs import (
    get_job,
    job_status,
    list_saved_searches,
    start_multi_search_job,
)
from trading_bot.application.strategy_search import to_serializable

_STRATS = ["sma_cross", "ema_cross", "rsi_mean_reversion"]


def _synth(n: int = 320, seed: int = 1, drift: float = 50.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = np.linspace(100.0, 100.0 + drift, n) + rng.normal(0, 1.2, n).cumsum() * 0.3
    return pd.DataFrame(
        {"open": closes, "high": closes + 1, "low": closes - 1, "close": closes,
         "volume": rng.integers(1000, 5000, n)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def _fake_download_factory(mapping):
    def _download(symbol, start, end, interval):
        return mapping[symbol]
    return _download


def test_run_multi_market_search_aggregates_across_markets() -> None:
    mapping = {"AAA": _synth(seed=1, drift=60), "BBB": _synth(seed=2, drift=40), "CCC": _synth(seed=3, drift=-10)}
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
    # La classifica è ordinata per robustezza (affidabile, poi positivo, poi resa).
    keys = [(s.markets_reliable, s.markets_positive, s.avg_holdout_return_pct) for s in result.strategy_scores]
    assert keys == sorted(keys, reverse=True)
    assert result.verdict_note


def test_run_multi_market_search_skips_broken_symbol() -> None:
    mapping = {"AAA": _synth(seed=1)}

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


def test_multi_market_result_is_json_serializable() -> None:
    mapping = {"AAA": _synth(seed=1, drift=60)}
    result = run_multi_market_search(
        ["AAA"], interval="1d", fee_bps=0.0,
        strategy_ids=_STRATS, download_data=_fake_download_factory(mapping),
    )
    payload = to_serializable(result)
    # Non deve contenere valori non finiti (inf/nan romperebbero il JSON).
    json.dumps(payload)
    assert payload["symbols"] == ["AAA"]


def test_start_multi_search_job_runs_in_background_and_persists(tmp_path: Path, monkeypatch) -> None:
    mapping = {"AAA": _synth(seed=1, drift=60), "BBB": _synth(seed=2, drift=40)}
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


def test_search_counts_combinations_while_working() -> None:
    """L'avanzamento conta le combinazioni provate (non le strategie finite),
    così l'utente vede un numero che sale invece di scatti da 15 passi."""
    from trading_bot.application.strategy_search import (
        estimate_search_combinations,
        run_strategy_search,
    )

    data = _synth(seed=1, drift=60)
    eventi: list[tuple[int, int, str]] = []
    run_strategy_search(
        data=data, symbol="AAA", fee_bps=0.0,
        strategy_ids=_STRATS,
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
