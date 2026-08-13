"""Il metro di paragone onesto: dividere i soldi fra i mercati e stare fermi."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.application.portafoglio import costruisci_portafoglio


def _serie(valori: list[float], inizio: str = "2022-01-03") -> pd.Series:
    return pd.Series(valori, index=pd.bdate_range(inizio, periods=len(valori)))


def _serve_almeno_venti(base: float, passo: float, n: int = 40) -> list[float]:
    return [base + passo * i for i in range(n)]


def test_due_mercati_uguali_danno_il_rendimento_del_singolo() -> None:
    """Diversificare fra due cose identiche non cambia niente: è il controllo
    che dice se il conto è giusto."""
    serie = _serie(_serve_almeno_venti(100.0, 1.0))
    p = costruisci_portafoglio({"AAA": serie, "BBB": serie.copy()}, ultima_frazione=1.0)

    atteso = (serie.iloc[-1] / serie.iloc[0] - 1) * 100
    assert p.rendimento_fermo_pct == pytest.approx(atteso, abs=0.01)
    assert p.rendimento_ribilanciato_pct == pytest.approx(atteso, abs=0.01)


def test_il_portafoglio_sta_in_mezzo_ai_suoi_mercati() -> None:
    """Metà su una cosa che sale e metà su una che scende: il risultato deve
    stare fra i due, mai fuori."""
    sale = _serie(_serve_almeno_venti(100.0, 2.0))
    scende = _serie(_serve_almeno_venti(100.0, -1.0))
    p = costruisci_portafoglio({"SU": sale, "GIU": scende}, ultima_frazione=1.0)

    resa_su = (sale.iloc[-1] / sale.iloc[0] - 1) * 100
    resa_giu = (scende.iloc[-1] / scende.iloc[0] - 1) * 100
    assert resa_giu < p.rendimento_fermo_pct < resa_su


def test_dividere_riduce_il_calo_peggiore() -> None:
    """Il motivo per cui la diversificazione esiste: due mercati che crollano in
    momenti diversi fanno un portafoglio che scende meno di ciascuno dei due."""
    rng = np.random.default_rng(3)
    n = 200
    base = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.008, n)))
    primo, secondo = base.copy(), base.copy()
    primo[50:80] *= np.linspace(1.0, 0.72, 30)      # crolla presto
    primo[80:] *= 0.72
    secondo[140:170] *= np.linspace(1.0, 0.72, 30)  # crolla tardi
    secondo[170:] *= 0.72

    a, b = _serie(list(primo)), _serie(list(secondo))
    p = costruisci_portafoglio({"A": a, "B": b}, ultima_frazione=1.0)

    calo_a = float((a / a.cummax() - 1).min()) * 100
    calo_b = float((b / b.cummax() - 1).min()) * 100
    assert p.calo_peggiore_fermo_pct > max(calo_a, calo_b)  # meno negativo


def test_serve_piu_di_un_mercato() -> None:
    """Con un mercato solo non c'è niente da diversificare: meglio niente che
    un confronto finto."""
    assert costruisci_portafoglio({"AAA": _serie(_serve_almeno_venti(100.0, 1.0))}) is None
    assert costruisci_portafoglio({}) is None


def test_usa_solo_il_tratto_finale_come_le_ricerche() -> None:
    """Il confronto deve riguardare lo stesso periodo su cui le strategie sono
    state messe alla prova, altrimenti non è un confronto."""
    lunga = _serie(_serve_almeno_venti(100.0, 1.0, n=100))
    p = costruisci_portafoglio({"A": lunga, "B": lunga.copy()}, ultima_frazione=0.20)

    assert p.barre == 20


def test_il_ribilanciamento_cambia_il_risultato() -> None:
    """Vendere un po' di ciò che è salito e comprare ciò che è sceso porta a un
    risultato diverso dal non fare niente: se coincidesse, non staremmo
    ribilanciando davvero."""
    rng = np.random.default_rng(11)
    n = 250
    a = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, n)))
    b = 100 * np.exp(np.cumsum(rng.normal(-0.0004, 0.02, n)))
    p = costruisci_portafoglio({"A": _serie(list(a)), "B": _serie(list(b))}, ultima_frazione=1.0)

    assert p.rendimento_fermo_pct != p.rendimento_ribilanciato_pct
    assert p.rendimento_migliore_pct == max(
        p.rendimento_fermo_pct, p.rendimento_ribilanciato_pct
    )


def test_senza_vittorie_riconosciute_non_si_incorona_nessuno() -> None:
    """Regressione: il verdetto diceva "X è la più solida" mentre ogni singolo
    mercato riportava "nessuna vittoria". Il semaforo di affidabilità da solo
    non basta più: se i controlli non passano, si dice che non passano."""
    from trading_bot.application.multi_search import StrategyAcrossMarkets, _overall_note

    prima_in_classifica = StrategyAcrossMarkets(
        strategy_id="parabolic_sar", label="Parabolic SAR", markets_tested=4,
        markets_reliable=2, markets_beat_market=2, avg_holdout_return_pct=8.5,
        avg_holdout_excess_pct=0.4, avg_dev_sharpe=0.3,
    )

    senza = _overall_note(prima_in_classifica, 4, None, vittorie_riconosciute=0)
    con = _overall_note(prima_in_classifica, 4, None, vittorie_riconosciute=2)

    assert "Non c'e' niente da cui fidarsi" in senza
    assert "più solida" not in senza
    assert "più solida" in con
