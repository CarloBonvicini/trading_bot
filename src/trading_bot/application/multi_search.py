"""Ricerca multi-mercato: la stessa validazione severa, ma su più simboli insieme.

La domanda a cui risponde: *esiste una strategia che regge su dati nuovi non su
un solo mercato per fortuna, ma su tanti mercati diversi?* È il test più severo
di robustezza — ed è quello che può durare a lungo (molti mercati × profondità
alta), quindi gira in background.

Per ogni simbolo esegue ``run_strategy_search`` (holdout + walk-forward), poi
aggrega per strategia: quante volte è risultata affidabile su dati nuovi, e con
quale resa media. Vince la strategia più costantemente solida fra i mercati.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from trading_bot.application.autosetting import AUTOSETTING_GRIDS
from trading_bot.application.strategy_search import (
    RELIABILITY_HIGH,
    run_strategy_search,
)
from trading_bot.data import download_price_data
from trading_bot.strategies import STRATEGY_SPECS

N_STRATEGIES = len(AUTOSETTING_GRIDS)
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class MarketOutcome:
    """Come è andata su un mercato la strategia mostrata (di norma il campione
    complessivo; il campione locale del mercato solo se non c'è un vincitore
    complessivo)."""

    symbol: str
    champion_label: str | None
    reliability: str
    holdout_return_pct: float
    benchmark_return_pct: float
    bars: int
    error: str | None = None


@dataclass
class StrategyAcrossMarkets:
    strategy_id: str
    label: str
    markets_tested: int
    markets_reliable: int       # affidabilità "alta" su dati nuovi
    markets_positive: int       # resa su dati nuovi > 0
    avg_holdout_return_pct: float
    avg_dev_sharpe: float


@dataclass
class MultiMarketSearchResult:
    symbols: list[str]
    interval: str
    scan_mode: str
    markets: list[MarketOutcome] = field(default_factory=list)
    strategy_scores: list[StrategyAcrossMarkets] = field(default_factory=list)
    overall_champion_id: str | None = None
    overall_champion_label: str | None = None
    verdict_note: str = ""
    settings: dict = field(default_factory=dict)


def run_multi_market_search(
    symbols: list[str],
    interval: str = "1d",
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float = 5.0,
    scan_mode: str = "rapida",
    start: str = "",
    end: str = "",
    strategy_ids: list[str] | None = None,
    download_data: Callable[..., pd.DataFrame] = download_price_data,
    progress_callback: ProgressCallback | None = None,
) -> MultiMarketSearchResult:
    """Esegue la ricerca su più mercati e aggrega la robustezza per strategia."""
    clean_symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not clean_symbols:
        raise ValueError("Indica almeno un simbolo da analizzare.")

    n_strategies = len(strategy_ids) if strategy_ids else N_STRATEGIES
    total = len(clean_symbols) * n_strategies
    # Info per mercato, tenute finché non conosciamo il campione complessivo.
    market_info: dict[str, dict] = {}
    # strategy_id -> liste di risultati per mercato (resa su dati nuovi, sharpe sviluppo, affidabile)
    per_strategy: dict[str, dict[str, list]] = {}

    for index, symbol in enumerate(clean_symbols):
        base_done = index * n_strategies

        def inner_progress(done: int, _local_total: int, label: str, _sym=symbol, _base=base_done) -> None:
            if progress_callback is not None:
                progress_callback(_base + done, total, f"{_sym} · {label}")

        try:
            data = download_data(symbol=symbol, start=start, end=end, interval=interval)
            result = run_strategy_search(
                data=data, symbol=symbol, interval=interval,
                initial_capital=initial_capital, fee_bps=fee_bps,
                scan_mode=scan_mode, strategy_ids=strategy_ids, progress_callback=inner_progress,
            )
        except Exception as exc:
            market_info[symbol] = {"error": str(exc)}
            if progress_callback is not None:
                progress_callback(base_done + n_strategies, total, f"{symbol} · saltato")
            continue

        by_strategy = {
            row.strategy_id: {"return": row.holdout_return_pct, "reliability": row.reliability}
            for row in result.ranking if row.error is None
        }
        market_info[symbol] = {
            "error": None,
            "bars": int(result.data_span.get("bars", 0)),
            "benchmark": result.holdout_benchmark_return_pct,
            "local_return": float(result.holdout.get("total_return_pct", 0.0)) if result.holdout else 0.0,
            "local_reliability": result.reliability,
            "local_champion_label": result.champion_label,
            "by_strategy": by_strategy,
        }

        for row in result.ranking:
            if row.error is not None:
                continue
            bucket = per_strategy.setdefault(
                row.strategy_id, {"returns": [], "dev_sharpe": [], "reliable": 0, "positive": 0}
            )
            bucket["returns"].append(row.holdout_return_pct)
            bucket["dev_sharpe"].append(row.avg_oos_sharpe)
            if row.reliability == RELIABILITY_HIGH:
                bucket["reliable"] += 1
            if row.holdout_return_pct > 0:
                bucket["positive"] += 1

    strategy_scores = _aggregate(per_strategy)
    overall = strategy_scores[0] if strategy_scores else None
    overall_id = None
    if overall and (overall.markets_reliable > 0 or overall.markets_positive > 0):
        overall_id = overall.strategy_id
    overall_label = STRATEGY_SPECS[overall_id].label if overall_id else None

    # Ogni scheda mostra come è andato il campione complessivo su quel mercato
    # (coerente con l'intestazione); se non c'è un campione complessivo, ripiega
    # sul campione locale del singolo mercato.
    markets = [_market_outcome(symbol, market_info.get(symbol, {"error": "nessun dato"}),
                               overall_id, overall_label)
               for symbol in clean_symbols]

    return MultiMarketSearchResult(
        symbols=clean_symbols,
        interval=interval,
        scan_mode=scan_mode,
        markets=markets,
        strategy_scores=strategy_scores,
        overall_champion_id=overall_id,
        overall_champion_label=overall_label,
        verdict_note=_overall_note(overall, len(clean_symbols)),
        settings={"initial_capital": float(initial_capital), "fee_bps": float(fee_bps)},
    )


def _market_outcome(symbol: str, info: dict, overall_id: str | None, overall_label: str | None) -> MarketOutcome:
    """Scheda di un mercato: mostra il campione complessivo su quel mercato,
    oppure il campione locale se non c'è un vincitore complessivo."""
    if info.get("error"):
        return MarketOutcome(symbol=symbol, champion_label=None, reliability="insufficiente",
                             holdout_return_pct=0.0, benchmark_return_pct=0.0, bars=0, error=info["error"])
    by_strategy = info.get("by_strategy", {})
    if overall_id and overall_id in by_strategy:
        entry = by_strategy[overall_id]
        return MarketOutcome(
            symbol=symbol, champion_label=overall_label,
            reliability=entry["reliability"], holdout_return_pct=entry["return"],
            benchmark_return_pct=info["benchmark"], bars=info["bars"],
        )
    return MarketOutcome(
        symbol=symbol, champion_label=info.get("local_champion_label"),
        reliability=info.get("local_reliability", "insufficiente"),
        holdout_return_pct=info.get("local_return", 0.0),
        benchmark_return_pct=info.get("benchmark", 0.0), bars=info.get("bars", 0),
    )


def _aggregate(per_strategy: dict[str, dict[str, list]]) -> list[StrategyAcrossMarkets]:
    scores: list[StrategyAcrossMarkets] = []
    for strategy_id, bucket in per_strategy.items():
        returns = bucket["returns"]
        dev = bucket["dev_sharpe"]
        tested = len(returns)
        scores.append(
            StrategyAcrossMarkets(
                strategy_id=strategy_id,
                label=STRATEGY_SPECS[strategy_id].label,
                markets_tested=tested,
                markets_reliable=bucket["reliable"],
                markets_positive=bucket["positive"],
                avg_holdout_return_pct=round(sum(returns) / tested, 2) if tested else 0.0,
                avg_dev_sharpe=round(sum(dev) / tested, 3) if tested else 0.0,
            )
        )
    # La più robusta: prima chi è affidabile su più mercati, poi chi è positivo
    # su più mercati, poi la resa media più alta.
    scores.sort(
        key=lambda s: (s.markets_reliable, s.markets_positive, s.avg_holdout_return_pct),
        reverse=True,
    )
    return scores


def _mercati(n: int) -> str:
    return "1 mercato" if n == 1 else f"{n} mercati"


def _overall_note(overall: "StrategyAcrossMarkets | None", n_markets: int) -> str:
    if overall is None:
        return "Nessun mercato ha prodotto risultati validi. Prova con altri simboli o più storia."
    if overall.markets_reliable > 0:
        return (
            f"{overall.label} è la più solida: affidabile su dati nuovi in "
            f"{_mercati(overall.markets_reliable)} su {n_markets} testati, "
            f"con una resa media su dati nuovi del {overall.avg_holdout_return_pct:+.1f}%."
        )
    if overall.markets_positive > 0:
        return (
            f"Nessuna strategia è risultata pienamente affidabile su più mercati. "
            f"La meno debole è {overall.label} (in positivo su "
            f"{_mercati(overall.markets_positive)} su {n_markets})."
        )
    return (
        "Nessuna strategia ha retto su dati nuovi in questi mercati: è il segno che "
        "batterli stabilmente è molto difficile, e spesso comprare e tenere è già competitivo."
    )
