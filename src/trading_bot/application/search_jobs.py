"""Esecuzione in background delle ricerche automatiche.

Una ricerca multi-mercato a profondità alta può durare a lungo: non può girare
dentro una richiesta HTTP (bloccherebbe la pagina e andrebbe in timeout). Qui la
lanciamo su un thread, teniamo traccia dell'avanzamento in un registro in
memoria e salviamo il risultato su disco così sopravvive ai riavvii ed è
riapribile.

Registro in-process: il bot è un'app locale a utente singolo, quindi un dict
protetto da lock è sufficiente (niente coda/broker esterni).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from trading_bot.application.multi_search import run_multi_market_search
from trading_bot.application.strategy_search import to_serializable

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_N_STRATEGIES = 15


def _job_dir(reports_dir: str | Path) -> Path:
    directory = Path(reports_dir) / "auto_searches"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def start_multi_search_job(
    *,
    symbols: list[str],
    interval: str,
    initial_capital: float,
    fee_bps: float,
    scan_mode: str,
    start: str,
    end: str,
    reports_dir: str | Path,
) -> str:
    """Avvia una ricerca multi-mercato in background e restituisce l'id del job."""
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "total": max(1, len(symbols) * _N_STRATEGIES),
        "message": "Avvio della ricerca…",
        "symbols": symbols,
        "interval": interval,
        "scan_mode": scan_mode,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "result": None,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job

    def _progress(done: int, total: int, message: str) -> None:
        with _LOCK:
            job["progress"] = done
            job["total"] = total
            job["message"] = message

    def _worker() -> None:
        try:
            result = run_multi_market_search(
                symbols=symbols, interval=interval, initial_capital=initial_capital,
                fee_bps=fee_bps, scan_mode=scan_mode, start=start, end=end,
                progress_callback=_progress,
            )
            payload = to_serializable(result)
            path = _job_dir(reports_dir) / f"{job_id}.json"
            with path.open("w", encoding="utf-8") as handle:
                json.dump(
                    {"id": job_id, "saved_at": datetime.now().isoformat(timespec="seconds"),
                     "result": payload},
                    handle, indent=2,
                )
            with _LOCK:
                job["status"] = "done"
                job["result"] = payload
                job["progress"] = job["total"]
                job["message"] = "Completato"
        except Exception as exc:  # il thread non deve morire silenziosamente
            with _LOCK:
                job["status"] = "error"
                job["error"] = str(exc)
                job["message"] = "Errore durante la ricerca"

    threading.Thread(target=_worker, name=f"search-{job_id}", daemon=True).start()
    return job_id


def get_job(job_id: str, reports_dir: str | Path) -> dict | None:
    """Restituisce lo snapshot del job (in memoria o ricaricato da disco)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            return dict(job)

    path = _job_dir(reports_dir) / f"{job_id}.json"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            saved = json.load(handle)
        result = saved.get("result", {})
        return {
            "id": job_id, "status": "done", "progress": 1, "total": 1,
            "message": "Completato", "result": result, "error": None,
            "symbols": result.get("symbols", []),
            "scan_mode": result.get("scan_mode", ""),
        }
    return None


def job_status(job_id: str, reports_dir: str | Path) -> dict | None:
    """Snapshot leggero per il polling (senza il payload completo del risultato)."""
    job = get_job(job_id, reports_dir)
    if job is None:
        return None
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": int(job.get("progress", 0)),
        "total": int(job.get("total", 1)),
        "message": job.get("message", ""),
        "error": job.get("error"),
    }
