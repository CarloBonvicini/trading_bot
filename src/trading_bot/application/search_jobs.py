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

from trading_bot.application.multi_search import N_STRATEGIES, run_multi_market_search
from trading_bot.application.ricerca_portafoglio import (
    cerca_portafoglio,
    esegui_configurazione,
)
from trading_bot.application.strategy_search import to_serializable
from trading_bot.data import download_price_data
from trading_bot.portafoglio import salva_report_portafoglio

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _job_dir(reports_dir: str | Path) -> Path:
    directory = Path(reports_dir) / "auto_searches"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _portfolio_dir(reports_dir: str | Path) -> Path:
    """Cartella a parte per le ricerche di portafoglio.

    Mescolarle a quelle a mercato singolo vorrebbe dire che l'elenco delle
    ricerche salvate se le ritrova dentro e prova a leggerle con la forma
    sbagliata: sono due risultati diversi, e stanno in due posti diversi.
    """
    directory = Path(reports_dir) / "portfolio_searches"
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
    consenti_short: bool = False,
    slippage_bps: float = 0.0,
    flat_at_close: bool = False,
    prove_del_caso: int = 0,
) -> str:
    """Avvia una ricerca multi-mercato in background e restituisce l'id del job."""
    job_id = uuid.uuid4().hex[:12]
    parametri = {
        "symbols": symbols,
        "interval": interval,
        "initial_capital": float(initial_capital),
        "fee_bps": float(fee_bps),
        "scan_mode": scan_mode,
        "start": start,
        "end": end,
        "consenti_short": bool(consenti_short),
        "slippage_bps": float(slippage_bps),
        "flat_at_close": bool(flat_at_close),
        "prove_del_caso": int(prove_del_caso),
    }
    stato = {"id": job_id, "params": parametri, "markets": {}}
    _write_checkpoint(job_id, reports_dir, stato)
    _launch(job_id=job_id, parametri=parametri, reports_dir=reports_dir, stato=stato)
    return job_id


def resume_search_job(job_id: str, reports_dir: str | Path) -> str | None:
    """Riprende una ricerca interrotta riusando il lavoro già salvato.

    Restituisce l'id del job, o None se non c'è un avanzamento da riprendere.
    Se il job è già in esecuzione non fa nulla (evita due thread sullo stesso id).
    """
    stato = load_checkpoint(job_id, reports_dir)
    if stato is None or not stato.get("params"):
        return None

    with _LOCK:
        esistente = _JOBS.get(job_id)
        if esistente is not None and esistente.get("status") == "running":
            return job_id

    _launch(job_id=job_id, parametri=stato["params"], reports_dir=reports_dir, stato=stato)
    return job_id


def _launch(*, job_id: str, parametri: dict, reports_dir: str | Path, stato: dict) -> None:
    """Avvia il thread di ricerca, salvando l'avanzamento a ogni strategia."""
    job = {
        "id": job_id,
        "status": "running",
        "consenti_short": bool(parametri.get("consenti_short", False)),
        "progress": 0,
        # Il totale reale (combinazioni da provare) si conosce dopo il download
        # dei dati: fino ad allora l'avanzamento resta a 0.
        "total": 1,
        "message": "Scarico i dati di mercato…",
        "symbols": parametri["symbols"],
        "interval": parametri["interval"],
        "scan_mode": parametri["scan_mode"],
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

    def _on_row(symbol: str, riga: dict, benchmark: float, barre: int) -> None:
        """Salva su disco una strategia completata: se la ricerca si interrompe
        qui, alla ripresa non verrà rifatta."""
        with _LOCK:
            mercato = stato.setdefault("markets", {}).setdefault(symbol, {"rows": {}})
            # La chiave comprende il verso: con il ribasso attivo la stessa
            # strategia corre due volte e le due righe non vanno confuse.
            verso = "short" if riga.get("consenti_short") else "long"
            mercato["rows"][f"{riga['strategy_id']}|{verso}"] = riga
            mercato["benchmark_return_pct"] = benchmark
            mercato["bars"] = barre
            _write_checkpoint(job_id, reports_dir, stato)

    def _worker() -> None:
        try:
            result = run_multi_market_search(
                symbols=parametri["symbols"], interval=parametri["interval"],
                initial_capital=parametri["initial_capital"], fee_bps=parametri["fee_bps"],
                scan_mode=parametri["scan_mode"], start=parametri["start"], end=parametri["end"],
                consenti_short=parametri.get("consenti_short", False),
                slippage_bps=parametri.get("slippage_bps", 0.0),
                flat_at_close=parametri.get("flat_at_close", False),
                prove_del_caso=parametri.get("prove_del_caso", 0),
                progress_callback=_progress, checkpoint=stato, on_row=_on_row,
            )
            payload = to_serializable(result)
            path = _job_dir(reports_dir) / f"{job_id}.json"
            with path.open("w", encoding="utf-8") as handle:
                json.dump(
                    {"id": job_id, "saved_at": datetime.now().isoformat(timespec="seconds"),
                     "result": payload},
                    handle, indent=2,
                )
            # Il risultato definitivo sostituisce l'avanzamento parziale.
            _checkpoint_path(job_id, reports_dir).unlink(missing_ok=True)
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


def start_portfolio_search_job(
    *,
    symbols: list[str],
    interval: str,
    initial_capital: float,
    fee_bps: float,
    start: str,
    end: str,
    reports_dir: str | Path,
    consenti_short: bool = False,
    slippage_bps: float = 0.0,
    prove_del_caso: int = 0,
    download_data=None,
) -> str:
    """Avvia in background la ricerca del portafoglio e restituisce l'id del job.

    Non ha checkpoint come la ricerca multi-mercato, e per una ragione: il
    budget qui è dichiarato e piccolo, quindi una ricerca dura minuti e non ore.
    Riprendere qualcosa che si rifà in due minuti aggiungerebbe una macchina da
    mantenere in cambio di niente.
    """
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "total": 1,
        "message": "Scarico i dati di mercato…",
        "symbols": symbols,
        "interval": interval,
        "scan_mode": "portafoglio",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "result": None,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job

    def _progress(fatte: int, totali: int, messaggio: str) -> None:
        with _LOCK:
            job["progress"] = fatte
            job["total"] = totali
            job["message"] = messaggio

    def _worker() -> None:
        try:
            # Risolto qui e non nella firma: legato come valore predefinito, un
            # test che sostituisce lo scaricatore non avrebbe alcun effetto,
            # perche' il nome sarebbe gia' stato catturato alla definizione.
            scarica = download_data or download_price_data
            mercati = {
                simbolo: scarica(symbol=simbolo, start=start, end=end, interval=interval)
                for simbolo in symbols
            }
            esito = cerca_portafoglio(
                mercati, initial_capital=initial_capital, fee_bps=fee_bps,
                slippage_bps=slippage_bps, consenti_short=consenti_short,
                prove_del_caso=prove_del_caso, progress_callback=_progress,
            )
            payload = to_serializable(esito)
            # La curva, i pesi nel tempo e il registro delle operazioni non
            # stanno in un riepilogo: si salvano a parte, cosi' si possono
            # aprire con un foglio di calcolo.
            if esito.parametri:
                _progress(job["total"], job["total"], "Salvo il portafoglio trovato…")
                intero = esegui_configurazione(
                    mercati, esito.parametri, initial_capital=initial_capital,
                    fee_bps=fee_bps, slippage_bps=slippage_bps,
                )
                if intero is not None:
                    cartella = salva_report_portafoglio(
                        intero, reports_dir,
                        nome="portafoglio-" + "_".join(symbols)[:40],
                        configurazione={**esito.parametri, "job_id": job_id},
                    )
                    payload["cartella_report"] = cartella.name

            with (_portfolio_dir(reports_dir) / f"{job_id}.json").open(
                "w", encoding="utf-8"
            ) as handle:
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

    threading.Thread(target=_worker, name=f"portafoglio-{job_id}", daemon=True).start()
    return job_id


def get_portfolio_job(job_id: str, reports_dir: str | Path) -> dict | None:
    """Snapshot del job di portafoglio, in memoria o ricaricato da disco."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            return dict(job)

    path = _portfolio_dir(reports_dir) / f"{job_id}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        salvato = json.load(handle)
    risultato = salvato.get("result", {})
    return {
        "id": job_id, "status": "done", "progress": 1, "total": 1,
        "message": "Completato", "result": risultato, "error": None,
        "symbols": risultato.get("mercati", []),
        "scan_mode": "portafoglio",
    }


def _checkpoint_path(job_id: str, reports_dir: str | Path) -> Path:
    return _job_dir(reports_dir) / f"{job_id}.progress.json"


def _write_checkpoint(job_id: str, reports_dir: str | Path, stato: dict) -> None:
    stato["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = _checkpoint_path(job_id, reports_dir)
    # Scrittura atomica: un'interruzione a metà non deve lasciare un file rotto.
    temporaneo = path.with_suffix(".tmp")
    with temporaneo.open("w", encoding="utf-8") as handle:
        json.dump(stato, handle, indent=2)
    temporaneo.replace(path)


def load_checkpoint(job_id: str, reports_dir: str | Path) -> dict | None:
    """Legge l'avanzamento salvato di una ricerca (None se non esiste)."""
    path = _checkpoint_path(job_id, reports_dir)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


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

    # Nessun risultato ma un avanzamento salvato: ricerca interrotta, riprendibile.
    stato = load_checkpoint(job_id, reports_dir)
    if stato is not None:
        parametri = stato.get("params") or {}
        fatte = sum(len(m.get("rows") or {}) for m in (stato.get("markets") or {}).values())
        symbols = parametri.get("symbols") or []
        return {
            "id": job_id, "status": "interrupted", "progress": fatte,
            "total": max(1, len(symbols) * N_STRATEGIES),
            "message": f"Interrotta dopo {fatte} strategie completate",
            "result": None, "error": None,
            "symbols": symbols,
            "scan_mode": parametri.get("scan_mode", ""),
        }
    return None


def list_saved_searches(reports_dir: str | Path, limit: int = 20) -> list[dict]:
    """Elenca le ricerche automatiche già completate, dalla più recente.

    Legge i file salvati in ``reports/auto_searches``: servono alla home per
    mostrare lo storico e riaprire un risultato senza rifare il calcolo.
    """
    directory = Path(reports_dir) / "auto_searches"
    if not directory.exists():
        return []

    searches: list[dict] = []
    for path in directory.glob("*.json"):
        # I file di avanzamento non sono risultati: vengono elencati a parte.
        if path.name.endswith(".progress.json") or path.name.endswith(".tmp"):
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            continue
        result = saved.get("result") or {}
        symbols = result.get("symbols") or []
        markets = result.get("markets") or []
        # Conteggio autorevole: quello aggregato del campione (stessa fonte della
        # frase di verdetto). Le schede per-mercato sono un ripiego per i
        # risultati salvati prima che l'aggregato esistesse.
        champion_id = result.get("overall_champion_id")
        champion_score = next(
            (s for s in (result.get("strategy_scores") or []) if s.get("strategy_id") == champion_id),
            None,
        )
        if champion_score:
            reliable = int(champion_score.get("markets_reliable") or 0)
            tested = int(champion_score.get("markets_tested") or len(markets))
        else:
            reliable = sum(1 for m in markets if m.get("reliability") == "alta")
            tested = len(markets)
        searches.append(
            {
                "id": str(saved.get("id") or path.stem),
                "saved_at": str(saved.get("saved_at") or ""),
                "saved_at_display": _format_saved_at(saved.get("saved_at")),
                "symbols": symbols,
                "symbols_display": ", ".join(symbols) if symbols else "—",
                "champion_label": result.get("overall_champion_label"),
                "verdict_note": result.get("verdict_note") or "",
                "markets_count": tested,
                "markets_reliable": reliable,
                "scan_mode": result.get("scan_mode") or "",
                "interrupted": False,
            }
        )

    # Ricerche interrotte (avanzamento salvato senza risultato finale): vanno
    # mostrate perché sono riprendibili.
    completate = {item["id"] for item in searches}
    for path in directory.glob("*.progress.json"):
        job_id = path.name[: -len(".progress.json")]
        if job_id in completate:
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                stato = json.load(handle)
        except (OSError, ValueError):
            continue
        parametri = stato.get("params") or {}
        symbols = parametri.get("symbols") or []
        fatte = sum(len(m.get("rows") or {}) for m in (stato.get("markets") or {}).values())
        searches.append(
            {
                "id": job_id,
                "saved_at": str(stato.get("updated_at") or ""),
                "saved_at_display": _format_saved_at(stato.get("updated_at")),
                "symbols": symbols,
                "symbols_display": ", ".join(symbols) if symbols else "—",
                "champion_label": None,
                "verdict_note": "",
                "markets_count": len(symbols),
                "markets_reliable": 0,
                "scan_mode": parametri.get("scan_mode") or "",
                "interrupted": True,
                "strategies_done": fatte,
                "strategies_total": len(symbols) * N_STRATEGIES,
            }
        )

    searches.sort(key=lambda item: item["saved_at"], reverse=True)
    return searches[:limit]


def _format_saved_at(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "data non disponibile"
    try:
        return datetime.fromisoformat(text).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def job_status(job_id: str, reports_dir: str | Path) -> dict | None:
    """Snapshot leggero per il polling (senza il payload completo del risultato).

    Include tempo trascorso e stima del rimanente: fra un passo e l'altro possono
    passare minuti, e senza questi numeri la pagina sembra ferma.
    """
    job = get_job(job_id, reports_dir)
    if job is None:
        return None

    progress = int(job.get("progress", 0))
    total = max(1, int(job.get("total", 1)))
    elapsed = _elapsed_seconds(job.get("started_at"))
    remaining = None
    if elapsed is not None and progress > 0 and job.get("status") == "running":
        remaining = int(elapsed / progress * max(0, total - progress))

    return {
        "id": job["id"],
        "status": job["status"],
        "progress": progress,
        "total": total,
        "message": job.get("message", ""),
        "error": job.get("error"),
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
    }


def _elapsed_seconds(started_at: object) -> int | None:
    text = str(started_at or "").strip()
    if not text:
        return None
    try:
        return max(0, int((datetime.now() - datetime.fromisoformat(text)).total_seconds()))
    except ValueError:
        return None
