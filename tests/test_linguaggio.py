"""Il report deve dire com'è andata a chi non sa leggere i numeri di finanza."""
from __future__ import annotations

import pytest

from trading_bot.application.constants import COSTI_OPERAZIONE
from trading_bot.application.requests import BacktestRequest, costi_operazione
from trading_bot.reporting import METRIC_TOOLTIPS, SUMMARY_LABELS, build_plain_verdict


def _riepilogo(**extra) -> dict:
    base = {
        "initial_capital": 10_000.0,
        "final_equity": 12_000.0,
        "benchmark_final_equity": 11_000.0,
        "gross_final_equity": 12_200.0,
        "trade_count": 30,
        "max_drawdown_pct": -12.0,
        "trading_costs_paid": 50.0,
        "wiped_out": False,
    }
    base.update(extra)
    return base


# ── Il verdetto in una frase ─────────────────────────────────────────────────

def test_verdetto_dice_quanto_hai_guadagnato_in_euro() -> None:
    v = build_plain_verdict(_riepilogo(), barre=500)

    assert v["tono"] == "positive"
    assert "2.000 €" in v["titolo"]          # 12.000 - 10.000
    assert "10.000 €" in v["frase"] and "12.000 €" in v["frase"]
    assert "11.000 €" in v["confronto"]      # comprando e basta
    assert "1.000 €" in v["confronto"]       # margine sul mercato
    assert not v["avvisi"]


def test_verdetto_dice_quando_hai_perso() -> None:
    v = build_plain_verdict(_riepilogo(final_equity=8_500.0), barre=500)

    assert v["tono"] == "negative"
    assert "perso" in v["titolo"].lower()
    assert "1.500 €" in v["titolo"]


def test_guadagnare_meno_del_mercato_non_e_un_buon_risultato() -> None:
    """Guadagnare 200 € mentre chi stava fermo ne faceva 1.000 non è un successo:
    il tono non deve essere verde."""
    v = build_plain_verdict(
        _riepilogo(final_equity=10_200.0, benchmark_final_equity=11_000.0), barre=500
    )

    assert v["tono"] == "neutral"
    assert "ti è costata" in v["confronto"]
    assert "800 €" in v["confronto"]


def test_verdetto_spiega_il_capitale_azzerato() -> None:
    v = build_plain_verdict(
        _riepilogo(final_equity=0.0, wiped_out=True, wiped_out_date="2024-03-05"), barre=500
    )

    assert v["tono"] == "negative"
    assert "azzerato" in v["titolo"].lower()
    assert "2024-03-05" in v["frase"]
    assert "allo scoperto" in v["confronto"]


# ── Gli avvisi quando il risultato non vuol dire niente ──────────────────────

def test_avvisa_se_le_operazioni_sono_troppo_poche() -> None:
    v = build_plain_verdict(_riepilogo(trade_count=3), barre=500)

    assert any("3 operazioni" in a for a in v["avvisi"])
    assert any("fortunata" in a or "caso" in a for a in v["avvisi"])


def test_avvisa_se_non_ha_mai_operato() -> None:
    v = build_plain_verdict(_riepilogo(trade_count=0), barre=500)

    assert any("non ha mai comprato" in a for a in v["avvisi"])


def test_avvisa_se_il_periodo_e_troppo_corto() -> None:
    v = build_plain_verdict(_riepilogo(), barre=40)

    assert any("periodo di prova è breve" in a for a in v["avvisi"])


def test_avvisa_sul_calo_che_avresti_dovuto_sopportare() -> None:
    v = build_plain_verdict(_riepilogo(max_drawdown_pct=-45.0), barre=500)

    assert any("45%" in a for a in v["avvisi"])


def test_avvisa_se_i_costi_si_mangiano_il_guadagno() -> None:
    # Lordo +2.200, costi 1.500: più di metà del guadagno se ne va in costi.
    v = build_plain_verdict(
        _riepilogo(gross_final_equity=12_200.0, trading_costs_paid=1_500.0), barre=500
    )

    assert any("mangiati" in a for a in v["avvisi"])


# ── Le etichette ─────────────────────────────────────────────────────────────

def test_nessuna_etichetta_in_gergo() -> None:
    """Il nome tecnico può stare nella spiegazione, mai nell'etichetta."""
    gergo = ("sharpe", "sortino", "calmar", "drawdown", "equity", "win rate",
             "profit factor", "expectancy", "bps", "pnl", "benchmark")

    colpevoli = {
        chiave: etichetta
        for chiave, etichetta in SUMMARY_LABELS.items()
        if any(parola in etichetta.lower() for parola in gergo)
    }

    assert not colpevoli, f"etichette ancora in gergo: {colpevoli}"


def test_ogni_metrica_mostrata_ha_la_sua_spiegazione() -> None:
    senza = [chiave for chiave in SUMMARY_LABELS if chiave not in METRIC_TOOLTIPS]
    assert not senza, f"metriche senza spiegazione: {senza}"


# ── Il costo di un'operazione senza "bps" ────────────────────────────────────

@pytest.mark.parametrize("scelta", sorted(COSTI_OPERAZIONE))
def test_ogni_scelta_di_costo_si_traduce_in_numeri(scelta: str) -> None:
    fee, slippage = costi_operazione({"costi_operazione": scelta})

    assert fee > 0 and slippage > 0
    assert COSTI_OPERAZIONE[scelta]["descrizione"]


def test_la_scelta_semplice_batte_i_valori_in_bps() -> None:
    """Chi usa il menu non deve preoccuparsi dei campi tecnici."""
    richiesta = BacktestRequest.from_mapping({
        "symbol": "SPY", "start": "2020-01-01", "end": "2021-01-01",
        "active_strategies": ["sma_cross"], "costi_operazione": "caro",
        "fee_bps": "5", "slippage_bps": "0",
    })

    assert richiesta.fee_bps == COSTI_OPERAZIONE["caro"]["fee_bps"]
    assert richiesta.slippage_bps == COSTI_OPERAZIONE["caro"]["slippage_bps"]


def test_senza_scelta_valgono_i_valori_indicati_a_mano() -> None:
    richiesta = BacktestRequest.from_mapping({
        "symbol": "SPY", "start": "2020-01-01", "end": "2021-01-01",
        "active_strategies": ["sma_cross"], "fee_bps": "12", "slippage_bps": "3",
    })

    assert richiesta.fee_bps == 12.0
    assert richiesta.slippage_bps == 3.0


# ── I verdetti, non solo le etichette ────────────────────────────────────────
# Il buco da cui è passato "punti": il test sulle etichette guardava soltanto
# SUMMARY_LABELS, e la parola stava nei paragrafi di verdetto — che nessuno
# controllava. Un verdetto è il testo che l'utente legge per primo e spesso per
# unico, quindi è il posto dove il gergo fa più danno.

# Il capitale con cui il programma chiama davvero questi verdetti: senza,
# si collauderebbe un percorso che in produzione non esiste.
CAPITALE = 10_000.0


def _verdetti_del_programma() -> dict[str, str]:
    """Ogni frase che il programma mostra per spiegare un risultato.

    Aggiungendo un verdetto nuovo va aggiunto qui: se non compare in questo
    elenco non è sotto controllo, ed è esattamente com'è nato il problema.
    """
    from trading_bot.application.multi_search import StrategyAcrossMarkets, _overall_note
    from trading_bot.application.prova_del_caso import valuta_contro_il_caso
    from trading_bot.application.ricerca_portafoglio import (
        EsitoRicercaPortafoglio,
        _verdetto as verdetto_portafoglio,
    )
    from trading_bot.application.strategy_search import (
        RELIABILITY_HIGH,
        RELIABILITY_LOW,
        RELIABILITY_MEDIUM,
        RELIABILITY_NONE,
        StrategyRanking,
        _verdict_note,
    )

    verdetti: dict[str, str] = {}

    # 1. Il verdetto in euro che apre ogni report.
    v = build_plain_verdict(_riepilogo(), barre=500)
    verdetti["build_plain_verdict"] = " ".join(
        [v["titolo"], v["frase"], v["confronto"], *v["avvisi"]]
    )

    # 2. La prova del caso, in tutti i suoi esiti.
    for nome, args in {
        "vittoria": (25.0, [4.0, 2.0, 3.0, 1.0, 2.5]),
        "la fortuna pareggia": (8.0, [7.5, 8.0, 7.0, 7.8, 8.1]),
        "la fortuna fa meglio": (-9.8, [0.3, 1.0, 2.0, 0.5, 1.2]),
        "poche prove": (25.0, [4.0, 2.0]),
    }.items():
        esito = valuta_contro_il_caso(*args, capitale=CAPITALE)
        verdetti[f"prova del caso · {nome}"] = esito.verdetto

    # 3. La frase di sintesi sul campione, in tutti i semafori.
    def _campione(reliability: str, resa: float, margine: float) -> StrategyRanking:
        return StrategyRanking(
            strategy_id="sma_cross", label="Incrocio di medie", avg_oos_sharpe=0.4,
            avg_is_sharpe=0.5, avg_oos_return_pct=3.0, wf_efficiency=0.8, windows=4,
            params={"fast": 20, "slow": 100}, holdout_return_pct=resa,
            holdout_sharpe=0.6, holdout_max_drawdown_pct=-12.0, holdout_trades=25,
            reliability=reliability, holdout_excess_return_pct=margine,
        )

    for nome, campione in {
        "alta": _campione(RELIABILITY_HIGH, 12.0, 4.0),
        "media in perdita": _campione(RELIABILITY_MEDIUM, -3.0, 2.0),
        "media in utile": _campione(RELIABILITY_MEDIUM, 5.0, 1.0),
        "bassa": _campione(RELIABILITY_LOW, 2.0, -3.0),
        "insufficiente": _campione(RELIABILITY_NONE, 0.0, 0.0),
    }.items():
        verdetti[f"campione · {nome}"] = _verdict_note(
            campione, benchmark_return_pct=8.0, capitale=CAPITALE
        )

    # 4. Il verdetto aggregato su più mercati.
    prima = StrategyAcrossMarkets(
        strategy_id="sma_cross", label="Incrocio di medie", markets_tested=4,
        markets_reliable=2, markets_beat_market=3, avg_holdout_return_pct=8.5,
        avg_holdout_excess_pct=2.4, avg_dev_sharpe=0.3,
    )
    verdetti["multi mercato · con vittorie"] = _overall_note(
        prima, 4, None, 2, capitale=CAPITALE
    )
    verdetti["multi mercato · senza vittorie"] = _overall_note(
        prima, 4, None, 0, capitale=CAPITALE
    )

    # 5. Il verdetto della ricerca di portafoglio.
    esito = EsitoRicercaPortafoglio(
        mercati=["AAA", "BBB"], barre=1000, barre_sviluppo=800, barre_prova=200,
        configurazioni_provate=192, configurazioni_possibili=192, budget=400,
        migliore="I più forti del gruppo", margine_pct=-9.8,
        margine_col_senno_di_poi_pct=19.3, configurazioni_in_vantaggio=66,
        riepilogo_prova={
            "initial_capital": CAPITALE, "final_equity": 11_666.0,
            "benchmark_final_equity": 12_644.0,
        },
    )
    verdetti["portafoglio"] = verdetto_portafoglio(esito)

    return verdetti


@pytest.mark.parametrize("dove", sorted(_verdetti_del_programma()))
def test_nessun_verdetto_usa_il_gergo(dove: str) -> None:
    """Le stesse parole vietate nelle etichette lo sono anche nelle frasi."""
    gergo = ("sharpe", "sortino", "calmar", "drawdown", "equity", "win rate",
             "profit factor", "expectancy", "bps", "pnl", "benchmark", "holdout",
             "overfitting", "out-of-sample", "walk-forward")
    testo = _verdetti_del_programma()[dove].lower()

    colpevoli = [parola for parola in gergo if parola in testo]
    assert not colpevoli, f"il verdetto «{dove}» usa gergo: {colpevoli}"


@pytest.mark.parametrize("dove", sorted(_verdetti_del_programma()))
def test_un_verdetto_che_parla_di_punti_dice_anche_gli_euro(dove: str) -> None:
    """La regola nata da "cosa sono i +20 punti, non capisco".

    Un punto percentuale non è un'unità che l'utente di questa app conosce. Se
    un verdetto la introduce deve tradurla, altrimenti il paragrafo comincia in
    euro e finisce in una lingua che nessuno ha insegnato a chi legge.
    """
    testo = _verdetti_del_programma()[dove]
    if "punti" not in testo and "punto" not in testo:
        return

    assert "€" in testo, (
        f"il verdetto «{dove}» parla di punti senza mai dire quanti euro sono:\n  {testo}"
    )
