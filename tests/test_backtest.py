from __future__ import annotations

import math

import pandas as pd
import pytest

from trading_bot.backtest import (
    apply_sl_tp,
    compute_position_size,
    infer_periods_per_year,
    run_backtest,
)
from trading_bot.strategies import (
    STRATEGY_SPECS,
    adx_components,
    build_combined_signal,
    build_strategy_signal,
    commodity_channel_index,
    donchian_breakout,
    money_flow_index,
    relative_strength_index,
    rsi_mean_reversion,
    sma_crossover,
    williams_r_indicator,
)


def test_sma_crossover_returns_binary_positions() -> None:
    data = pd.DataFrame(
        {"close": [100, 101, 102, 103, 104, 105]},
        index=pd.date_range("2024-01-01", periods=6, freq="D"),
    )

    signal = sma_crossover(data, fast=2, slow=3)

    assert set(signal.dropna().unique()).issubset({0.0, 1.0})


def test_rsi_mean_reversion_returns_binary_positions() -> None:
    data = pd.DataFrame(
        {"close": [100, 90, 88, 89, 91, 94, 97, 99]},
        index=pd.date_range("2024-01-01", periods=8, freq="D"),
    )

    signal = rsi_mean_reversion(data, period=2, lower=35, upper=55)

    assert set(signal.unique()).issubset({0.0, 1.0})


def test_backtest_shifts_signal_to_avoid_lookahead() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 110.0, 121.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    signal = pd.Series([1.0, 1.0, 1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=0.0)

    assert result.equity_curve["position"].tolist() == [0.0, 1.0, 1.0]
    assert round(result.summary["final_equity"], 2) == 1210.0
    assert round(result.summary["gross_final_equity"], 2) == 1210.0
    assert round(result.summary["benchmark_final_equity"], 2) == 1210.0
    assert round(result.summary["excess_return_pct"], 2) == 0.0
    assert round(result.summary["fees_paid"], 2) == 0.0
    assert round(result.summary["fee_drag_equity"], 2) == 0.0


def test_backtest_tracks_fees_paid() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 110.0, 100.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    signal = pd.Series([1.0, 0.0, 0.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=100.0)

    assert result.summary["fees_paid"] > 0
    assert result.summary["gross_final_equity"] > result.summary["final_equity"]
    assert round(result.summary["fee_drag_equity"], 2) >= round(result.summary["fees_paid"], 2)


def test_donchian_breakout_returns_binary_positions(ohlc_da_chiusure) -> None:
    closes = [100.0, 99.0, 101.0, 100.0, 98.0, 102.0, 105.0, 107.0, 106.0, 108.0]
    data = ohlc_da_chiusure(closes)
    signal = donchian_breakout(data, entry_period=5, exit_period=3)
    assert set(signal.unique()).issubset({0.0, 1.0})


def test_donchian_breakout_entry_fires_on_new_high(ohlc_da_chiusure) -> None:
    # Prime 3 barre: high fermo a 101. Quarta barra: high = 110 -> breakout
    closes = [100.0, 100.0, 100.0, 110.0, 110.0]
    highs  = [101.0, 101.0, 101.0, 110.0, 110.0]
    lows   = [ 99.0,  99.0,  99.0,  99.0,  99.0]
    data = ohlc_da_chiusure(closes, massimi=highs, minimi=lows)
    signal = donchian_breakout(data, entry_period=3, exit_period=2)
    # Alla barra 3 (indice 3): close=110 >= max high(101,101,110)=110 -> entrata
    assert signal.iloc[3] == 1.0


def test_donchian_breakout_exit_fires_on_new_low(ohlc_da_chiusure) -> None:
    # Prezzi range-bound -> breakout a rialzo (ingresso) -> crollo sotto il canale (uscita)
    # entry_period=3, exit_period=2
    closes = [100.0, 101.0, 100.0, 101.0, 101.0, 121.0, 120.0, 73.0]
    highs  = [101.0, 102.0, 101.0, 102.0, 102.0, 121.0,  81.0, 74.0]
    lows   = [ 99.0,  99.0,  99.0,  99.0,  99.0,  99.0,  80.0, 73.0]
    data = ohlc_da_chiusure(closes, massimi=highs, minimi=lows)
    signal = donchian_breakout(data, entry_period=3, exit_period=2)
    # Ingresso alla barra 5: close 121 >= max high(102,102,121)=121
    assert signal.iloc[5] == 1.0
    # Uscita alla barra 7: close 73 <= min low(80,73)=73
    assert signal.iloc[7] == 0.0


def test_donchian_breakout_raises_if_exit_period_not_smaller(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0] * 10)
    with pytest.raises(ValueError, match="exit period"):
        donchian_breakout(data, entry_period=10, exit_period=10)


def test_donchian_breakout_raises_without_high_low_columns() -> None:
    data = pd.DataFrame(
        {"close": [100.0, 101.0, 102.0, 103.0]},
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )
    with pytest.raises(ValueError, match="colonne"):
        donchian_breakout(data, entry_period=3, exit_period=2)


def test_build_combined_signal_supports_and_logic() -> None:
    data = pd.DataFrame(
        {"close": [100, 99, 98, 99, 101, 103, 102, 104, 105, 107]},
        index=pd.date_range("2024-01-01", periods=10, freq="D"),
    )

    signal = build_combined_signal(
        data=data,
        rules=[
            ("sma_cross", {"fast": 2, "slow": 4}),
            ("ema_cross", {"fast": 2, "slow": 5}),
        ],
        combination_mode="all",
    )

    assert set(signal.dropna().unique()).issubset({0.0, 1.0})
    assert float(signal.max()) == 1.0


# ── apply_sl_tp ──────────────────────────────────────────────────────────────


def test_apply_sl_tp_noop_when_both_none(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0, 105.0, 110.0])
    pos = pd.Series([0.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=None, tp_pct=None)
    assert new_pos.tolist() == pos.tolist()
    assert mask.sum() == 0


def test_apply_sl_tp_stop_loss_triggers(ohlc_da_chiusure) -> None:
    # Posizione entra alla barra 1 (close=100). Entry price = close[0] = 100.
    # SL al 5% → prezzo soglia = 95. Barra 2: low = 88 - 2 = 86 → scatta.
    closes = [100.0, 100.0, 88.0, 110.0]
    data = ohlc_da_chiusure(closes, spread=2.0)
    # Segnale scende a 0 alla barra 3 per isolare: verifichiamo solo che SL chiuda a barra 2
    pos = pd.Series([0.0, 1.0, 1.0, 0.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=None)
    # Alla barra 2 (i=2) lo SL è scattato: posizione → 0
    assert new_pos.iloc[2] == 0.0
    assert mask.iloc[2] is True or mask.iloc[2] == True  # noqa: E712
    # Barra 3: segnale già 0, non è rientrato
    assert new_pos.iloc[3] == 0.0


def test_apply_sl_tp_take_profit_triggers(ohlc_da_chiusure) -> None:
    # Entry price = 100. TP al 10% → soglia = 110. Barra 2: high = 115 + 2 = 117 → scatta.
    closes = [100.0, 100.0, 115.0, 80.0]
    data = ohlc_da_chiusure(closes, spread=2.0)
    pos = pd.Series([0.0, 1.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=None, tp_pct=10.0)
    assert new_pos.iloc[2] == 0.0
    assert mask.iloc[2] is True or mask.iloc[2] == True  # noqa: E712


def test_apply_sl_tp_no_trigger_when_price_in_range(ohlc_da_chiusure) -> None:
    # SL 5% TP 10%: range 95–110. Prezzi mai fuori.
    closes = [100.0, 100.0, 103.0, 107.0, 109.0]
    data = ohlc_da_chiusure(closes, spread=0.5)
    pos = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=10.0)
    assert new_pos.tolist() == pos.tolist()
    assert mask.sum() == 0


def test_apply_sl_tp_result_integrated_in_run_backtest() -> None:
    # Con SL stretto (1%) su un drawdown ampio il numero trade SL deve essere > 0
    closes = [100.0, 100.0, 85.0, 80.0, 100.0, 100.0, 82.0]
    data = pd.DataFrame(
        {
            "close": closes,
            "high": [c + 2 for c in closes],
            "low":  [c - 2 for c in closes],
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    signal = pd.Series([1.0] * len(closes), index=data.index)
    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=0.0, sl_pct=5.0)
    assert result.summary["sl_tp_exit_count"] > 0


# ── compute_position_size ─────────────────────────────────────────────────────

def test_compute_position_size_full_unchanged(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0] * 5)
    pos = pd.Series([0.0, 1.0, 1.0, 0.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="full", param=100.0)
    assert result.tolist() == pos.tolist()


def test_compute_position_size_fixed_fraction(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0] * 5)
    pos = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="fixed", param=50.0)
    assert all(abs(v - 0.5) < 1e-9 for v in result)


def test_compute_position_size_fixed_zero_when_no_position(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0] * 4)
    pos = pd.Series([0.0, 1.0, 0.0, 1.0], index=data.index)
    result = compute_position_size(data, pos, method="fixed", param=40.0)
    assert result.iloc[0] == 0.0
    assert result.iloc[2] == 0.0
    assert abs(result.iloc[1] - 0.4) < 1e-9


def test_compute_position_size_vol_target_clips_at_2x(ohlc_da_chiusure) -> None:
    # Vol molto bassa → size > 2 → deve essere clippata a 2.0
    closes = [100.0 + i * 0.0001 for i in range(30)]  # vol quasi zero
    data = ohlc_da_chiusure(closes)
    pos = pd.Series([1.0] * 30, index=data.index)
    result = compute_position_size(data, pos, method="vol_target", param=15.0)
    assert float(result.max()) <= 2.0 + 1e-9


# ── Metriche economiche ────────────────────────────────────────────────────

def _run_simple_bt(ohlc, closes: list[float], signal_values: list[float], spread: float = 1.0):
    """Wrapper per test: crea OHLC simmetrico e lancia un backtest senza fee.

    ``ohlc`` è la fabbrica ``ohlc_da_chiusure`` (una fixture non è utilizzabile
    da una funzione normale, quindi arriva come argomento).
    """
    data = ohlc(closes, spread=spread)
    signal = pd.Series(signal_values, index=data.index)
    return run_backtest(data=data, signal=signal, initial_capital=10_000.0, fee_bps=0.0)


def test_summary_includes_new_metrics(ohlc_da_chiusure) -> None:
    result = _run_simple_bt(ohlc_da_chiusure, [100.0, 110.0, 121.0, 110.0, 100.0, 110.0], [1.0] * 6)
    for key in (
        "sortino_ratio", "calmar_ratio", "win_rate_pct",
        "profit_factor", "avg_win_pct", "avg_loss_pct", "expectancy_pct",
    ):
        assert key in result.summary, f"manca metrica {key}"


def test_win_rate_correct_with_known_trades(ohlc_da_chiusure) -> None:
    # 2 trade chiusi, uno in profitto e uno in perdita → win_rate = 50%.
    # signal = [1, 1, 0, 1, 1, 0, 0]  → executed (shift 1) = [0, 1, 1, 0, 1, 1, 0]
    # Trade 1 (chiuso): entry@bar1 (close=110), exit@bar3 (close=121) → +10%
    # Trade 2 (chiuso): entry@bar4 (close=115), exit@bar6 (close=105) → -8.7%
    closes = [100.0, 110.0, 120.0, 121.0, 115.0, 110.0, 105.0]
    signal = [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0]
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["trade_count"] == 2
    assert result.summary["win_rate_pct"] == 50.0


def test_profit_factor_no_losses_caps_at_999(ohlc_da_chiusure) -> None:
    # Trade chiuso in profitto, nessun trade in perdita → profit_factor = 999.
    # signal = [1, 1, 0, 0]  → executed = [0, 1, 1, 0]
    # Trade chiuso: entry@bar1 (close=105), exit@bar3 (close=110) → +4.76%
    closes = [100.0, 105.0, 108.0, 110.0]
    signal = [1.0, 1.0, 0.0, 0.0]
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["trade_count"] >= 1
    # Nessuna perdita registrata
    assert result.summary["avg_loss_pct"] is None
    assert result.summary["profit_factor"] == 999.0


def test_calmar_ratio_zero_when_no_drawdown(ohlc_da_chiusure) -> None:
    # Equity sempre crescente: drawdown = 0 → calmar capped a 999 se return > 0.
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    signal = [1.0, 1.0, 1.0, 1.0, 1.0]
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    # Calmar definito (non NaN)
    assert isinstance(result.summary["calmar_ratio"], float)


def test_annual_return_falls_back_to_total_for_short_periods(ohlc_da_chiusure) -> None:
    # Periodo < 1 anno: annual_return_pct deve essere == total_return_pct,
    # per evitare CAGR amplificati.
    closes = [100.0, 110.0]  # +10% in 1 giorno
    signal = [1.0, 1.0]
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    assert result.summary["annual_return_pct"] == result.summary["total_return_pct"]


def test_sl_tp_can_trigger_on_entry_bar() -> None:
    # Entry al close[0]=100. Barra 1 (eseguita): low=92 < 95 (SL 5%) → uscita
    # nel BAR DI ENTRY. Verifica che il fix copra anche questo caso.
    closes = [100.0, 100.0]
    data = pd.DataFrame(
        {
            "close": closes,
            "high":  [101.0, 102.0],
            "low":   [99.0,  92.0],   # crollo intrabar
        },
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    pos = pd.Series([0.0, 1.0], index=data.index)
    new_pos, mask = apply_sl_tp(data, pos, sl_pct=5.0, tp_pct=None)
    # Posizione esce subito nella stessa barra in cui sarebbe entrata
    assert new_pos.iloc[1] == 0.0
    assert bool(mask.iloc[1]) is True


def test_vol_target_does_not_create_fake_trades(ohlc_da_chiusure) -> None:
    # Con vol_target la posizione frazionaria varia molto, ma il trade tracking
    # deve basarsi sulla posizione binaria → un solo trade.
    closes = [100.0, 101.0, 99.0, 102.0, 98.0, 105.0, 103.0]
    signal = [1.0] * 7  # sempre long
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(
        data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0,
        sizing_method="vol_target", sizing_param=10.0,
    )
    # Un solo trade aperto (chiusura non avviene perché signal sempre 1)
    assert int(result.summary["trade_count"]) <= 1


def test_sortino_handles_no_downside_returns(ohlc_da_chiusure) -> None:
    # Solo rendimenti positivi: sortino deve essere finito (cap a 999) o 0.
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    signal = [1.0] * 5
    data = ohlc_da_chiusure(closes, spread=0.5)
    sig = pd.Series(signal, index=data.index)
    result = run_backtest(data=data, signal=sig, initial_capital=10_000.0, fee_bps=0.0)
    sortino = result.summary["sortino_ratio"]
    assert isinstance(sortino, float)
    assert not (sortino != sortino)  # not NaN


# ── Annualizzazione dedotta dal calendario ───────────────────────────────────

def test_infer_periods_per_year_daily_resta_252() -> None:
    """Le serie giornaliere devono restare a 252: i report già salvati non
    devono cambiare valore."""
    idx = pd.bdate_range("2022-01-03", periods=300)
    assert infer_periods_per_year(idx) == 252.0


def test_infer_periods_per_year_intraday_conta_le_barre_del_giorno() -> None:
    # 7 barre orarie al giorno per 40 giorni di borsa.
    idx = pd.DatetimeIndex(
        [
            giorno + pd.Timedelta(hours=ora)
            for giorno in pd.bdate_range("2024-01-02", periods=40)
            for ora in range(9, 16)
        ]
    )
    assert infer_periods_per_year(idx) == pytest.approx(252 * 7)


def test_infer_periods_per_year_settimanale_e_mensile() -> None:
    settimanale = pd.date_range("2020-01-06", periods=120, freq="W-MON")
    mensile = pd.date_range("2015-01-31", periods=60, freq="ME")
    # ~50 barre l'anno sul settimanale, ~12 sul mensile.
    assert infer_periods_per_year(settimanale) == pytest.approx(252 / 5)
    assert 10.0 <= infer_periods_per_year(mensile) <= 13.0


def test_infer_periods_per_year_fallback_su_serie_corte() -> None:
    assert infer_periods_per_year(pd.date_range("2024-01-01", periods=4)) == 252.0
    assert infer_periods_per_year(pd.Index([1, 2, 3])) == 252.0


def test_sharpe_orario_non_annualizzato_come_giornaliero() -> None:
    """Regressione: su barre orarie ogni barra veniva contata come un giorno,
    quindi Sharpe risultava schiacciato di un fattore radice(barre al giorno) e
    il rendimento annuo veniva spalmato su sette volte il tempo reale."""
    idx = pd.DatetimeIndex(
        [
            giorno + pd.Timedelta(hours=ora)
            for giorno in pd.bdate_range("2024-01-02", periods=60)
            for ora in range(9, 16)
        ]
    )
    rendimenti = [0.001 if i % 2 else 0.002 for i in range(len(idx))]
    closes = 100.0 * pd.Series(rendimenti, index=idx).add(1).cumprod()
    data = pd.DataFrame({"close": closes, "high": closes, "low": closes}, index=idx)
    signal = pd.Series(1.0, index=idx)

    orario = run_backtest(data=data, signal=signal, fee_bps=0.0)

    # Stessa identica serie di rendimenti, ma su barre giornaliere.
    idx_daily = pd.bdate_range("2020-01-01", periods=len(idx))
    closes_daily = pd.Series(closes.to_numpy(), index=idx_daily)
    data_daily = pd.DataFrame(
        {"close": closes_daily, "high": closes_daily, "low": closes_daily}, index=idx_daily
    )
    giornaliero = run_backtest(
        data=data_daily, signal=pd.Series(1.0, index=idx_daily), fee_bps=0.0
    )

    # Stessi rendimenti per barra, ma le barre orarie sono 7 volte più fitte:
    # annualizzate correttamente danno uno Sharpe radice(7) volte più alto.
    rapporto = orario.summary["sharpe_ratio"] / giornaliero.summary["sharpe_ratio"]
    assert rapporto == pytest.approx(math.sqrt(7), rel=0.01)
    # Stesso guadagno totale concentrato in 60 giorni invece che in 420: il
    # rendimento annuo orario deve risultare molto più alto, non uguale.
    assert orario.summary["annual_return_pct"] > giornaliero.summary["annual_return_pct"]


# ── Divisioni protette senza degradare a dtype "object" ──────────────────────


def test_indicatori_restano_numerici_su_mercato_piatto(mercato_piatto) -> None:
    """Regressione: sostituire lo zero con pd.NA rendeva la serie di tipo
    object, e da lì in poi fillna avvisava del cambio di comportamento."""
    import warnings

    data = mercato_piatto()
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        indicatori = {
            "rsi": relative_strength_index(data["close"], period=14),
            "cci": commodity_channel_index(data, period=20),
            "williams_r": williams_r_indicator(data, period=14),
            "mfi": money_flow_index(data, period=14),
        }

    for nome, serie in indicatori.items():
        assert serie.dtype == float, f"{nome} non è numerico: {serie.dtype}"
        assert not serie.isna().any(), f"{nome} contiene valori mancanti"


def test_adx_su_mercato_piatto_non_solleva(mercato_piatto) -> None:
    """Regressione: con ATR a zero la serie diventava object e la media
    esponenziale falliva, facendo sparire in silenzio l'intera strategia."""
    componenti = adx_components(mercato_piatto(), period=14)

    assert list(componenti.columns) == ["adx", "plus_di", "minus_di"]
    assert all(componenti[colonna].dtype == float for colonna in componenti.columns)


def test_strategie_su_mercato_piatto_non_operano(mercato_piatto) -> None:
    """Su un mercato che non si muove nessuna strategia deve entrare."""
    import warnings

    data = mercato_piatto()
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        for strategy_id in ("adx_trend", "stochastic_reversion", "mfi_reversion",
                            "roc_momentum", "williams_r_reversion", "cci_reversion"):
            segnale = build_strategy_signal(
                strategy_id=strategy_id, data=data,
                parameters=STRATEGY_SPECS[strategy_id].defaults(),
            )
            assert segnale.sum() == 0.0, f"{strategy_id} ha operato su un mercato fermo"


# ── Posizioni al ribasso ─────────────────────────────────────────────────────

def test_posizione_al_ribasso_guadagna_quando_il_prezzo_scende(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0, 90.0, 81.0])
    signal = pd.Series([-1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=1_000.0, fee_bps=0.0)

    # Lo shift di una barra vale anche al ribasso: la prima barra è fuori mercato.
    assert result.equity_curve["position"].tolist() == [0.0, -1.0, -1.0]
    # -10% e -10% di mercato diventano +10% e +10% per chi è al ribasso.
    assert round(result.summary["final_equity"], 2) == 1210.0
    # Il mercato ha perso: il confronto col comprare-e-tenere è nettamente positivo.
    assert result.summary["benchmark_return_pct"] < 0
    assert result.summary["excess_return_pct"] > 0


def test_segnale_negativo_non_viene_piu_azzerato(ohlc_da_chiusure) -> None:
    """Regressione: il clip a 0..1 buttava via qualsiasi segnale al ribasso."""
    data = ohlc_da_chiusure([100.0, 95.0, 90.0])
    result = run_backtest(
        data=data, signal=pd.Series([-1.0, -1.0, -1.0], index=data.index), fee_bps=0.0
    )

    assert result.equity_curve["signal"].tolist() == [-1.0, -1.0, -1.0]
    assert result.summary["short_exposure_pct"] > 0
    assert result.summary["long_exposure_pct"] == 0


def test_esposizione_conta_il_valore_assoluto(ohlc_da_chiusure) -> None:
    """Una strategia sempre a mercato che alterna i due versi è esposta al 100%,
    non a zero: senza valore assoluto long e short si annullerebbero."""
    data = ohlc_da_chiusure([100.0, 101.0, 102.0, 103.0])
    signal = pd.Series([1.0, 1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, fee_bps=0.0)

    # Con lo shift di una barra le posizioni sono [0, +1, +1, -1].
    assert result.summary["exposure_pct"] == 75.0
    assert result.summary["long_exposure_pct"] == 50.0
    assert result.summary["short_exposure_pct"] == 25.0


def test_stop_loss_al_ribasso_scatta_quando_il_prezzo_sale(ohlc_da_chiusure) -> None:
    """Chi è al ribasso perde quando il mercato sale: le soglie si scambiano."""
    # Entrata al ribasso alla barra 1 (prezzo di entrata = close[0] = 100).
    # SL al 5% → soglia a 105. Barra 2: high = 108 + 2 = 110 → scatta.
    data = ohlc_da_chiusure([100.0, 100.0, 108.0, 90.0], spread=2.0)
    signal = pd.Series([-1.0, -1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, sl_pct=5.0, fee_bps=0.0)

    assert result.equity_curve["position"].iloc[2] == 0.0
    assert result.summary["sl_tp_exit_count"] == 1


def test_take_profit_al_ribasso_scatta_quando_il_prezzo_scende(ohlc_da_chiusure) -> None:
    # Entrata al ribasso a 100, TP al 10% → soglia a 90. Barra 2: low = 88 - 2 = 86.
    data = ohlc_da_chiusure([100.0, 100.0, 88.0, 95.0], spread=2.0)
    signal = pd.Series([-1.0, -1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, tp_pct=10.0, fee_bps=0.0)

    assert result.equity_curve["position"].iloc[2] == 0.0
    assert result.summary["sl_tp_exit_count"] == 1


def test_trade_al_ribasso_registra_direzione_e_pnl_corretto(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0, 100.0, 80.0, 80.0])
    # Al ribasso dalla barra 1, chiuso alla barra 3.
    signal = pd.Series([-1.0, -1.0, 0.0, 0.0], index=data.index)

    result = run_backtest(data=data, signal=signal, fee_bps=0.0)
    trades = result.trades

    assert len(trades) == 1
    assert trades.iloc[0]["direction"] == "short"
    # Entrata a 100, uscita a 80: al ribasso è un guadagno del 20%.
    assert trades.iloc[0]["pnl_pct"] == 20.0
    assert result.summary["short_trade_count"] == 1


def test_ribaltamento_diretto_produce_due_operazioni(ohlc_da_chiusure) -> None:
    """Passare da rialzo a ribasso senza tornare a zero è una chiusura più
    un'apertura, non un'unica operazione."""
    data = ohlc_da_chiusure([100.0, 110.0, 120.0, 100.0, 90.0])
    signal = pd.Series([1.0, 1.0, -1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, fee_bps=0.0)
    trades = result.trades

    assert len(trades) == 2
    assert trades.iloc[0]["direction"] == "long"
    assert trades.iloc[1]["direction"] == "short"
    # La chiusura del primo e l'apertura del secondo cadono sulla stessa barra.
    assert trades.iloc[0]["exit_date"] == trades.iloc[1]["entry_date"]
    assert result.summary["trade_count"] == 2
    assert result.summary["short_trade_count"] == 1


def test_conto_azzerato_se_il_ribasso_va_oltre_il_capitale(ohlc_da_chiusure) -> None:
    """Al ribasso la perdita non ha tetto: oltre il -100% il capitale non deve
    diventare negativo, altrimenti ogni metrica successiva è priva di senso."""
    data = ohlc_da_chiusure([100.0, 100.0, 260.0, 200.0, 150.0], spread=0.0)
    signal = pd.Series([-1.0, -1.0, -1.0, -1.0, -1.0], index=data.index)

    result = run_backtest(data=data, signal=signal, initial_capital=10_000.0, fee_bps=0.0)

    assert result.summary["wiped_out"] is True
    assert result.summary["wiped_out_date"]
    assert result.summary["final_equity"] == 0.0
    assert result.summary["total_return_pct"] == -100.0
    # Niente valori negativi e nessuna operazione dopo il tracollo.
    assert (result.equity_curve["equity"] >= 0).all()
    assert result.equity_curve["position"].iloc[3:].abs().sum() == 0.0
    assert round(result.summary["max_drawdown_pct"], 2) == -100.0


def test_backtest_solo_long_non_segnala_mai_il_tracollo(ohlc_da_chiusure) -> None:
    """Senza posizioni al ribasso il capitale non può azzerarsi: la guardia non
    deve intromettersi nei backtest normali."""
    data = ohlc_da_chiusure([100.0, 50.0, 25.0, 12.0])
    result = run_backtest(
        data=data, signal=pd.Series([1.0] * 4, index=data.index), fee_bps=0.0
    )

    assert result.summary["wiped_out"] is False
    assert result.summary["final_equity"] > 0


# ── Slippage ─────────────────────────────────────────────────────────────────

def test_slippage_zero_lascia_il_risultato_identico(ohlc_da_chiusure) -> None:
    """Il default non deve cambiare nulla: i report già salvati restano validi."""
    data = ohlc_da_chiusure([100.0, 110.0, 105.0, 115.0, 120.0])
    signal = pd.Series([1.0, 0.0, 1.0, 1.0, 0.0], index=data.index)

    senza = run_backtest(data=data, signal=signal, fee_bps=5.0)
    con_zero = run_backtest(data=data, signal=signal, fee_bps=5.0, slippage_bps=0.0)

    assert senza.summary == con_zero.summary
    assert con_zero.summary["slippage_paid"] == 0.0


def test_slippage_riduce_il_risultato_come_una_commissione(ohlc_da_chiusure) -> None:
    """Si paga sul volume scambiato, quindi 5 bps di slippage pesano quanto
    5 bps di commissione."""
    data = ohlc_da_chiusure([100.0, 110.0, 105.0, 115.0, 120.0])
    signal = pd.Series([1.0, 0.0, 1.0, 1.0, 0.0], index=data.index)

    solo_fee = run_backtest(data=data, signal=signal, fee_bps=10.0, slippage_bps=0.0)
    meta_e_meta = run_backtest(data=data, signal=signal, fee_bps=5.0, slippage_bps=5.0)

    assert meta_e_meta.summary["final_equity"] == pytest.approx(
        solo_fee.summary["final_equity"], rel=1e-9
    )
    # Ma le due voci restano distinte nel riepilogo.
    assert meta_e_meta.summary["fees_paid"] == pytest.approx(
        meta_e_meta.summary["slippage_paid"], abs=0.01
    )
    assert solo_fee.summary["slippage_paid"] == 0.0


def test_slippage_separa_le_due_voci_di_costo(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0, 110.0, 105.0, 115.0])
    signal = pd.Series([1.0, 0.0, 1.0, 0.0], index=data.index)

    result = run_backtest(data=data, signal=signal, fee_bps=4.0, slippage_bps=6.0)
    s = result.summary

    # Lo slippage pesa una volta e mezza le commissioni (6 bps contro 4).
    # Le voci del riepilogo sono arrotondate al centesimo di euro.
    assert s["slippage_paid"] == pytest.approx(s["fees_paid"] * 1.5, abs=0.01)
    assert s["trading_costs_paid"] == pytest.approx(s["fees_paid"] + s["slippage_paid"], abs=0.02)
    # Il totale coincide con quanto separa la curva lorda da quella netta.
    assert s["fee_drag_equity"] > 0
    assert result.equity_curve["slippage_cost_amount"].sum() == pytest.approx(
        s["slippage_paid"], abs=0.01
    )


def test_slippage_negativo_viene_rifiutato(ohlc_da_chiusure) -> None:
    data = ohlc_da_chiusure([100.0, 110.0, 105.0])
    with pytest.raises(ValueError, match="slippage_bps"):
        run_backtest(
            data=data, signal=pd.Series([1.0, 1.0, 1.0], index=data.index), slippage_bps=-1.0
        )


def test_slippage_penalizza_chi_opera_di_piu(ohlc_da_chiusure) -> None:
    """A parità di mercato, una strategia che entra ed esce di continuo paga
    molto più slippage di una che resta ferma: è il punto della modifica."""
    chiusure = [100.0 + (i % 2) * 3 for i in range(40)]
    data = ohlc_da_chiusure(chiusure)
    nervosa = pd.Series([float(i % 2) for i in range(40)], index=data.index)
    tranquilla = pd.Series([1.0] * 40, index=data.index)

    a = run_backtest(data=data, signal=nervosa, fee_bps=0.0, slippage_bps=10.0)
    b = run_backtest(data=data, signal=tranquilla, fee_bps=0.0, slippage_bps=10.0)

    assert a.summary["slippage_paid"] > 10 * b.summary["slippage_paid"]
