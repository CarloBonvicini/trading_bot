"""Test per la ricerca automatica multi-mercato e l'esecuzione in background."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from trading_bot.application.multi_search import MultiMarketSearchResult, run_multi_market_search
from trading_bot.application.search_jobs import get_job, job_status, start_multi_search_job
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
