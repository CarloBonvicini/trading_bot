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
