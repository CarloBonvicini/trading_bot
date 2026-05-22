document.addEventListener("DOMContentLoaded", () => {
  const configNode = document.getElementById("chart-strategy-lab-config");
  const chartPayloadNode = document.getElementById("chart-window-data");
  if (!configNode) {
    return;
  }

  const config = JSON.parse(configNode.textContent || "{}");
  const initialChartPayload = chartPayloadNode ? JSON.parse(chartPayloadNode.textContent || "{}") : {};
  if (!config.preview_endpoint) {
    return;
  }

  const strategyToggles = Array.from(document.querySelectorAll("[data-chart-strategy-toggle]"));
  const strategyCards = Array.from(document.querySelectorAll("[data-chart-strategy-card]"));
  const parameterSections = Array.from(document.querySelectorAll("[data-chart-parameters]"));
  const parameterInputs = Array.from(document.querySelectorAll("[data-chart-parameter-input]"));
  const ruleLogicSelect = document.querySelector("[data-chart-rule-logic]");
  const statusNode = document.querySelector("[data-live-preview-status]");
  const badgeNode = document.querySelector("[data-live-preview-badge]");
  const ruleSummaryNode = document.querySelector("[data-live-rule-summary]");
  const comparisonGrid = document.querySelector("[data-live-comparison-grid]");
  const validationGrid = document.querySelector("[data-live-validation-grid]");
  const validationChecksNode = document.querySelector("[data-live-validation-checks]");
  const tradePreviewNode = document.querySelector("[data-live-trade-preview]");
  const resetButton = document.querySelector("[data-chart-preview-reset]");
  const autosettingButtons = Array.from(document.querySelectorAll("[data-autosetting-btn]"));
  const indicatorSectionNode = document.querySelector("[data-preview-indicator-section]");
  const indicatorPanelsNode = document.querySelector("[data-preview-indicator-panels]");
  const indicatorTitleNode = document.querySelector("[data-preview-indicator-title]");

  let debounceTimer = null;
  let requestCounter = 0;
  let currentIndicatorPayload = Array.isArray(config.indicator_payload) ? config.indicator_payload : [];
  let currentIndicatorLabel = config.baseline_label || "Setup iniziale del report";
  let currentChartPayload = initialChartPayload;

  const initialState = captureState();
  renderComparisonCards(config.comparison_cards || []);
  renderValidationCards(config.validation_cards || []);
  renderValidationChecks(config.validation_checks || []);
  renderTradePreview(config.trade_preview || []);
  renderIndicatorPanels(currentIndicatorPayload, currentIndicatorLabel, currentChartPayload);
  syncSections();
  syncRuleSummary();

  strategyToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      ensureAtLeastOneActive(toggle.value);
      syncSections();
      schedulePreview();
    });
  });

  ruleLogicSelect?.addEventListener("change", schedulePreview);
  parameterInputs.forEach((input) => {
    input.addEventListener("input", schedulePreview);
    input.addEventListener("change", schedulePreview);
  });

  resetButton?.addEventListener("click", (event) => {
    event.preventDefault();
    restoreInitialState();
  });

  // ── Autosetting modal setup ──────────────────────────────────────
  const autosettingModal = document.getElementById("autosetting-modal");
  const autosettingModalTitle = autosettingModal?.querySelector("[data-autosetting-modal-title]");
  const autosettingModalSubtitle = autosettingModal?.querySelector("[data-autosetting-modal-subtitle]");
  const autosettingLoadingNode = autosettingModal?.querySelector("[data-autosetting-loading]");
  const autosettingContentNode = autosettingModal?.querySelector("[data-autosetting-content]");
  const autosettingMetricsNode = autosettingModal?.querySelector("[data-autosetting-metrics]");
  const autosettingWarningNode = autosettingModal?.querySelector("[data-autosetting-warning]");
  const autosettingChartNode = autosettingModal?.querySelector("[data-autosetting-chart]");
  const autosettingSelectedLabel = autosettingModal?.querySelector("[data-autosetting-selected-label]");
  const autosettingApplyBtn = autosettingModal?.querySelector("[data-autosetting-apply]");
  const autosettingChartToggle = autosettingModal?.querySelector("[data-autosetting-chart-toggle]");

  let autosettingData = null;      // risposta completa dall'endpoint
  let autosettingStrategyId = "";  // strategia corrente nel modal
  let autosettingSelectedParams = null;  // parametri selezionati dall'utente
  let autosettingActiveMetric = "sharpe"; // "sharpe" o "robustness"

  autosettingButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const strategyId = btn.dataset.autosettingBtn;
      const label = btn.dataset.autosettingLabel || strategyId;
      if (strategyId) {
        openAutosettingModal(strategyId, label);
      }
    });
  });

  autosettingModal?.querySelectorAll("[data-autosetting-modal-close]").forEach((el) => {
    el.addEventListener("click", closeAutosettingModal);
  });

  autosettingApplyBtn?.addEventListener("click", () => {
    if (autosettingSelectedParams && autosettingStrategyId) {
      applyAutosettingParams(autosettingStrategyId, autosettingSelectedParams);
      closeAutosettingModal();
    }
  });

  // ── Bottom tabs ──────────────────────────────────────────────────
  const bottomTabs = Array.from(document.querySelectorAll("[data-bottom-tab]"));
  const bottomPanels = Array.from(document.querySelectorAll("[data-bottom-panel]"));

  bottomTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.bottomTab;
      const isAlreadyActive = tab.classList.contains("is-active");

      // Toggle: se già attivo, chiudi tutto
      if (isAlreadyActive) {
        bottomTabs.forEach((t) => t.classList.remove("is-active"));
        bottomPanels.forEach((p) => { p.hidden = true; });
        return;
      }

      bottomTabs.forEach((t) => t.classList.toggle("is-active", t === tab));
      bottomPanels.forEach((p) => { p.hidden = p.dataset.bottomPanel !== target; });
    });
  });

  // ── Scansione rapida ─────────────────────────────────────────────
  const scanAllBtn = document.querySelector("[data-scan-all-btn]");
  const scanBadges = Object.fromEntries(
    Array.from(document.querySelectorAll("[data-strategy-score]")).map((el) => [
      el.dataset.strategyScore,
      el,
    ]),
  );

  scanAllBtn?.addEventListener("click", runScanAll);

  async function runScanAll() {
    if (!config.autosetting_endpoint) return;

    const strategyIds = Object.keys(config.strategies || {});
    if (!strategyIds.length) return;

    scanAllBtn.disabled = true;
    scanAllBtn.textContent = "Scansione…";

    // Mostra stato "…" su tutti i badge
    strategyIds.forEach((id) => {
      const badge = scanBadges[id];
      if (!badge) return;
      badge.textContent = "…";
      badge.className = "strategy-scan-badge scan-loading";
      badge.hidden = false;
    });

    const feeInput = parameterInputs.find((input) => input.name === "fee_bps");
    const feeValue = feeInput ? parseFloat(feeInput.value) || 5 : 5;

    // Analisi sequenziale — una alla volta per non sovraccaricare il server
    for (let i = 0; i < strategyIds.length; i++) {
      const strategyId = strategyIds[i];
      const badge = scanBadges[strategyId];
      if (badge) {
        badge.textContent = "…";
        badge.className = "strategy-scan-badge scan-loading";
      }
      if (statusNode) {
        statusNode.textContent = `Scansione ${i + 1}/${strategyIds.length}: ${config.strategies[strategyId]?.label || strategyId}…`;
      }

      try {
        const response = await fetch(config.autosetting_endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy_id: strategyId, fee_bps: feeValue }),
        });
        const data = await response.json();

        if (!response.ok || typeof data.sharpe_in_sample !== "number") {
          throw new Error(data.error || "errore");
        }

        const sharpe = data.sharpe_in_sample;
        const ret = typeof data.total_return_pct === "number" ? data.total_return_pct : null;
        if (badge) {
          const sharpeSign = sharpe >= 0 ? "+" : "";
          const retSign = ret !== null && ret >= 0 ? "+" : "";
          const retStr = ret !== null ? ` · ${retSign}${ret.toFixed(1)}%` : "";
          badge.innerHTML = `<span>Sharpe ${sharpeSign}${sharpe.toFixed(2)}</span><span>${ret !== null ? `${retSign}${ret.toFixed(1)}%` : ""}</span>`;
          badge.className = `strategy-scan-badge strategy-scan-badge-dual ${_scanTone(sharpe)}`;
          badge.title = `Sharpe in-sample: ${sharpe.toFixed(3)} · out-of-sample: ${typeof data.sharpe_out_of_sample === "number" ? data.sharpe_out_of_sample.toFixed(3) : "—"}${retStr}`;
          badge.hidden = false;
        }
      } catch (_) {
        if (badge) {
          badge.textContent = "err";
          badge.className = "strategy-scan-badge scan-bad";
        }
      }
    }

    scanAllBtn.disabled = false;
    scanAllBtn.textContent = "Scansione rapida";
    if (statusNode) statusNode.textContent = "Scansione completata.";
  }

  function _scanTone(sharpe) {
    if (sharpe >= 0.3) return "scan-good";
    if (sharpe >= 0)   return "scan-ok";
    return "scan-bad";
  }

  autosettingChartToggle?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-autosetting-metric]");
    if (!btn) return;
    autosettingActiveMetric = btn.dataset.autosettingMetric;
    autosettingChartToggle.querySelectorAll("[data-autosetting-metric]").forEach((b) => {
      b.classList.toggle("is-active", b === btn);
    });
    if (autosettingData) {
      renderAutosettingChart(autosettingData, autosettingActiveMetric);
    }
  });

  function activeStrategyIds() {
    return strategyToggles.filter((toggle) => toggle.checked).map((toggle) => toggle.value);
  }

  function ensureAtLeastOneActive(preferredStrategyId = "") {
    if (activeStrategyIds().length > 0) {
      return;
    }

    const fallback =
      strategyToggles.find((toggle) => toggle.value === preferredStrategyId)
      || strategyToggles[0];
    if (fallback) {
      fallback.checked = true;
    }
  }

  function syncSections() {
    const activeIds = activeStrategyIds();
    window.tradingBotChartTerminal?.setPreviewIndicatorFilter(activeIds);
    renderIndicatorPanels(filterIndicatorsByActiveStrategies(currentIndicatorPayload, activeIds), currentIndicatorLabel, currentChartPayload);
    strategyCards.forEach((card) => {
      card.classList.toggle("is-active", activeIds.includes(card.dataset.chartStrategyCard));
    });
    parameterSections.forEach((section) => {
      const isActive = activeIds.includes(section.dataset.chartParameters);
      section.classList.toggle("is-active", isActive);
      section.querySelectorAll("input, select, textarea").forEach((field) => {
        field.disabled = !isActive;
      });
    });
    syncRuleSummary();
  }

  function syncRuleSummary(previewLabel = config.baseline_label || "Setup iniziale del report") {
    const labels = activeStrategyIds()
      .map((strategyId) => config.strategies?.[strategyId]?.label)
      .filter(Boolean);
    const ruleLogic = ruleLogicSelect?.value || config.rule_logic || "all";
    const descriptor = ruleLogic === "any" ? "OR" : "AND";
    if (!ruleSummaryNode) {
      return;
    }
    if (labels.length > 1) {
      ruleSummaryNode.textContent = `Config: ${previewLabel} · ${labels.join(" + ")} (${descriptor})`;
      return;
    }
    ruleSummaryNode.textContent = `Config: ${previewLabel} · ${labels[0] || "nessuna"}`;
  }

  function schedulePreview() {
    if (statusNode) {
      statusNode.textContent = "Aggiornamento preview...";
    }
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(runPreview, 260);
  }

  async function runPreview() {
    const requestId = ++requestCounter;
    const payload = buildPayload();

    let response = null;
    try {
      response = await fetch(config.preview_endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (requestId !== requestCounter) {
        return;
      }
      if (!response.ok) {
        throw new Error(data.error || "Preview non disponibile.");
      }
      applyPreviewResponse(data);
    } catch (error) {
      if (requestId !== requestCounter) {
        return;
      }
      if (statusNode) {
        const httpStatus = response ? ` (HTTP ${response.status})` : "";
        const msg = error instanceof Error ? error.message : "Preview non disponibile.";
        statusNode.textContent = `Errore preview${httpStatus}: ${msg}`;
      }
    }
  }

  function buildPayload() {
    const payload = {
      active_strategies: activeStrategyIds(),
      rule_logic: ruleLogicSelect?.value || config.rule_logic || "all",
    };
    parameterInputs.forEach((input) => {
      payload[input.name] = input.value;
    });
    return payload;
  }

  function applyPreviewResponse(data) {
    currentIndicatorPayload = data.indicator_payload || data.chart_payload?.indicators || [];
    currentIndicatorLabel = data.preview_label || "Configurazione attuale";
    currentChartPayload = data.chart_payload || initialChartPayload;
    renderComparisonCards(data.comparison_cards || []);
    renderValidationCards(data.validation_cards || []);
    renderValidationChecks(data.validation_checks || []);
    renderTradePreview(data.trade_preview || []);
    renderIndicatorPanels(
      filterIndicatorsByActiveStrategies(currentIndicatorPayload, activeStrategyIds()),
      currentIndicatorLabel,
      currentChartPayload,
    );
    if (badgeNode) {
      badgeNode.textContent = data.preview_label || "Configurazione attuale";
    }
    if (statusNode) {
      statusNode.textContent = `Preview: ${data.preview_label || "configurazione attuale"}`;
    }
    syncRuleSummary(data.preview_label || "Configurazione attuale");
    try {
      window.tradingBotChartTerminal?.applyPreview(data.chart_payload || {}, data.preview_label || "Configurazione attuale");
    } catch (e) {
      console.warn("Errore durante l'aggiornamento del grafico preview:", e?.message || e);
    }
  }

  function restoreInitialState() {
    strategyToggles.forEach((toggle) => {
      toggle.checked = initialState.activeStrategyIds.includes(toggle.value);
    });
    if (ruleLogicSelect) {
      ruleLogicSelect.value = initialState.ruleLogic;
    }
    parameterInputs.forEach((input) => {
      if (Object.prototype.hasOwnProperty.call(initialState.parameters, input.name)) {
        input.value = initialState.parameters[input.name];
      }
    });
    currentIndicatorPayload = Array.isArray(config.indicator_payload) ? config.indicator_payload : [];
    currentIndicatorLabel = config.baseline_label || "Setup iniziale del report";
    currentChartPayload = initialChartPayload;
    syncSections();
    renderComparisonCards(config.comparison_cards || []);
    renderValidationCards(config.validation_cards || []);
    renderValidationChecks(config.validation_checks || []);
    renderTradePreview(config.trade_preview || []);
    renderIndicatorPanels(
      filterIndicatorsByActiveStrategies(currentIndicatorPayload, activeStrategyIds()),
      currentIndicatorLabel,
      currentChartPayload,
    );
    if (badgeNode) {
      badgeNode.textContent = config.baseline_label || "Setup iniziale del report";
    }
    if (statusNode) {
      statusNode.textContent = "Setup iniziale ripristinato.";
    }
    syncRuleSummary(config.baseline_label || "Setup iniziale del report");
    window.tradingBotChartTerminal?.clearPreview();
  }

  function captureState() {
    const parameters = {};
    parameterInputs.forEach((input) => {
      parameters[input.name] = input.value;
    });
    return {
      activeStrategyIds: activeStrategyIds(),
      ruleLogic: ruleLogicSelect?.value || "all",
      parameters,
    };
  }

  function renderComparisonCards(cards) {
    if (!comparisonGrid) {
      return;
    }

    comparisonGrid.innerHTML = cards.map((card) => `
      <article class="terminal-metric-card">
        <p>${escapeHtml(card.label ?? "")}</p>
        <strong>${escapeHtml(card.value ?? "")}</strong>
      </article>
    `).join("");
  }

  function renderTradePreview(trades) {
    if (!tradePreviewNode) {
      return;
    }

    if (!Array.isArray(trades) || trades.length === 0) {
      tradePreviewNode.innerHTML = `
        <div class="empty-state">
          <p>Nessun trade disponibile per questa preview live.</p>
        </div>
      `;
      return;
    }

    tradePreviewNode.innerHTML = `
      <div class="table-wrap trade-table-wrap">
        <table class="trade-table">
          <thead>
            <tr>
              <th>Esito</th>
              <th>Entrata</th>
              <th>Uscita</th>
              <th>PnL</th>
              <th>Durata</th>
            </tr>
          </thead>
          <tbody>
            ${trades.map((trade) => `
              <tr>
                <td><span class="trade-badge trade-badge-${escapeHtml(trade.status_class || "neutral")}">${escapeHtml(trade.status_label || "-")}</span></td>
                <td>
                  <div class="trade-cell">
                    <strong>${escapeHtml(trade.entry_price_display || "-")}</strong>
                    <span>${escapeHtml(trade.entry_date_display || "-")}</span>
                    ${trade.entry_time_display ? `<span>${escapeHtml(trade.entry_time_display)}</span>` : ""}
                  </div>
                </td>
                <td>
                  <div class="trade-cell">
                    <strong>${escapeHtml(trade.exit_price_display || "-")}</strong>
                    <span>${escapeHtml(trade.exit_date_display || "-")}</span>
                    ${trade.exit_time_display ? `<span>${escapeHtml(trade.exit_time_display)}</span>` : ""}
                  </div>
                </td>
                <td><span class="trade-pnl trade-pnl-${escapeHtml(trade.status_class || "neutral")}">${escapeHtml(trade.pnl_display || "-")}</span></td>
                <td>${escapeHtml(trade.duration_display || "-")}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderValidationCards(cards) {
    if (!validationGrid) {
      return;
    }

    validationGrid.innerHTML = (Array.isArray(cards) ? cards : []).map((card) => `
      <article class="terminal-metric-card report-tone-${escapeHtml(card.tone || "neutral")}">
        <p>${escapeHtml(card.label ?? "")}</p>
        <strong>${escapeHtml(card.value ?? "")}</strong>
        <span>${escapeHtml(card.hint ?? "")}</span>
      </article>
    `).join("");
  }

  function renderValidationChecks(checks) {
    if (!validationChecksNode) {
      return;
    }

    validationChecksNode.innerHTML = (Array.isArray(checks) ? checks : []).map((check) => `
      <article class="chart-validation-check chart-validation-check-${escapeHtml(check.status_class || "neutral")}">
        <div class="chart-validation-check-head">
          <strong>${escapeHtml(check.label ?? "")}</strong>
          <span class="chart-validation-check-badge chart-validation-check-badge-${escapeHtml(check.status_class || "neutral")}">
            ${escapeHtml(check.status_label ?? "")}
          </span>
        </div>
        <p>${escapeHtml(check.value ?? "")}</p>
        <span>${escapeHtml(check.hint ?? "")}</span>
      </article>
    `).join("");
  }

  function renderIndicatorPanels(panels, previewLabel, chartPayload) {
    if (!indicatorSectionNode || !indicatorPanelsNode) {
      return;
    }

    const normalizedPanels = Array.isArray(panels)
      ? panels.filter((panel) => panel && panel.placement === "panel")
      : [];
    if (indicatorTitleNode) {
      indicatorTitleNode.textContent = normalizedPanels.length
        ? `Indicatori della configurazione attuale: ${previewLabel || "preview"}`
        : "Indicatori della preview";
    }

    if (normalizedPanels.length === 0) {
      indicatorSectionNode.hidden = true;
      indicatorPanelsNode.innerHTML = "";
      return;
    }

    indicatorSectionNode.hidden = false;
    indicatorPanelsNode.innerHTML = normalizedPanels.map((panel) => `
      <article class="chart-preview-indicator-card">
        <div class="chart-preview-indicator-copy">
          <h4>${escapeHtml(panel.label || "Indicatore")}</h4>
          <p>${escapeHtml(panel.description || "Indicatore calcolato sulla configurazione attuale.")}</p>
        </div>
        <div class="chart-preview-indicator-plot" data-preview-indicator-chart="${escapeHtml(panel.key || "")}"></div>
      </article>
    `).join("");

    if (typeof Plotly === "undefined") {
      return;
    }

    const dates = Array.isArray(chartPayload?.dates) ? chartPayload.dates : [];
    normalizedPanels.forEach((panel) => {
      const chartNode = indicatorPanelsNode.querySelector(`[data-preview-indicator-chart="${cssEscape(panel.key || "")}"]`);
      if (!chartNode) {
        return;
      }
      Plotly.newPlot(
        chartNode,
        buildIndicatorPanelTraces(panel, dates),
        buildIndicatorPanelLayout(panel),
        {
          responsive: true,
          displaylogo: false,
          displayModeBar: false,
          staticPlot: false,
        },
      );
    });
  }

  function filterIndicatorsByActiveStrategies(panels, activeIds) {
    if (!Array.isArray(panels)) {
      return [];
    }
    const allowed = new Set((Array.isArray(activeIds) ? activeIds : []).map((value) => String(value || "").trim()).filter(Boolean));
    if (allowed.size === 0) {
      return [];
    }
    return panels.filter((panel) => allowed.has(String(panel?.key || "").trim()));
  }

  function buildIndicatorPanelTraces(panel, dates) {
    return (Array.isArray(panel?.series) ? panel.series : []).map((series) => ({
      type: "scattergl",
      mode: "lines",
      name: series.label || "Serie",
      x: dates,
      y: Array.isArray(series.values) ? series.values : [],
      line: {
        color: series.color || "#60a5fa",
        width: 2,
        dash: series.dash || "solid",
      },
      hovertemplate: `${escapeHtml(series.label || "Serie")} %{y:.4f}<br>%{x}<extra></extra>`,
    }));
  }

  function buildIndicatorPanelLayout(panel) {
    const thresholdShapes = (Array.isArray(panel?.thresholds) ? panel.thresholds : []).map((threshold) => ({
      type: "line",
      xref: "paper",
      x0: 0,
      x1: 1,
      yref: "y",
      y0: Number(threshold.value),
      y1: Number(threshold.value),
      line: {
        color: threshold.color || "#94a3b8",
        width: 1,
        dash: threshold.dash || "dot",
      },
    }));

    return {
      paper_bgcolor: "#07111b",
      plot_bgcolor: "#07111b",
      font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5" },
      margin: { l: 44, r: 18, t: 10, b: 28 },
      hovermode: "x unified",
      showlegend: true,
      legend: {
        orientation: "h",
        x: 0,
        y: 1.12,
        xanchor: "left",
        yanchor: "bottom",
        font: { size: 10, color: "#9ba7c2" },
      },
      xaxis: {
        type: "date",
        showgrid: true,
        gridcolor: "rgba(171, 184, 214, 0.05)",
        zeroline: false,
        tickfont: { color: "#8d98b2", size: 10 },
      },
      yaxis: {
        showgrid: true,
        gridcolor: "rgba(171, 184, 214, 0.05)",
        zeroline: false,
        tickfont: { color: "#8d98b2", size: 10 },
      },
      shapes: thresholdShapes,
      height: 180,
    };
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(String(value));
    }
    return String(value).replace(/"/g, '\\"');
  }

  function openAutosettingModal(strategyId, label) {
    if (!autosettingModal || !config.autosetting_endpoint) return;

    autosettingStrategyId = strategyId;
    autosettingData = null;
    autosettingSelectedParams = null;

    if (autosettingModalTitle) autosettingModalTitle.textContent = `Analisi parametri — ${label}`;
    if (autosettingModalSubtitle) autosettingModalSubtitle.textContent = "";
    if (autosettingLoadingNode) autosettingLoadingNode.hidden = false;
    if (autosettingContentNode) autosettingContentNode.hidden = true;
    if (autosettingApplyBtn) autosettingApplyBtn.disabled = true;
    if (autosettingSelectedLabel) autosettingSelectedLabel.textContent = "Nessuna selezione.";

    autosettingModal.hidden = false;
    document.body.classList.add("autosetting-modal-open");

    fetchAutosettingData(strategyId);
  }

  function closeAutosettingModal() {
    if (!autosettingModal) return;
    autosettingModal.hidden = true;
    document.body.classList.remove("autosetting-modal-open");
  }

  async function fetchAutosettingData(strategyId) {
    if (statusNode) statusNode.textContent = "Analisi parametri in corso...";

    try {
      const feeInput = parameterInputs.find((input) => input.name === "fee_bps");
      const feeValue = feeInput ? parseFloat(feeInput.value) || 5 : 5;

      const response = await fetch(config.autosetting_endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: strategyId, fee_bps: feeValue }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Analisi non disponibile.");
      }

      autosettingData = data;

      // Selezione iniziale = parametri autosetting
      autosettingSelectedParams = { ...data.best_params };

      if (autosettingLoadingNode) autosettingLoadingNode.hidden = true;
      if (autosettingContentNode) autosettingContentNode.hidden = false;

      renderAutosettingMetrics(data);
      renderAutosettingChart(data, autosettingActiveMetric);
      updateAutosettingSelectedLabel(data.best_params, data);

      if (autosettingApplyBtn) autosettingApplyBtn.disabled = false;

      // Status bar aggiornato
      const isStr = typeof data.sharpe_in_sample === "number" ? data.sharpe_in_sample.toFixed(2) : "—";
      const oosStr = typeof data.sharpe_out_of_sample === "number" ? data.sharpe_out_of_sample.toFixed(2) : "—";
      if (statusNode) {
        statusNode.textContent = `Analisi: Sharpe IS ${isStr} · OOS ${oosStr} · ${data.combinations_tested} combinazioni`;
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Analisi non disponibile.";
      if (autosettingLoadingNode) {
        autosettingLoadingNode.innerHTML = `<span style="color:#ef4444">Errore: ${escapeHtml(msg)}</span>`;
      }
      if (statusNode) statusNode.textContent = `Errore analisi: ${msg}`;
    }
  }

  function renderAutosettingMetrics(data) {
    if (!autosettingMetricsNode) return;

    const fmt = (v) => typeof v === "number" ? v.toFixed(2) : "—";

    autosettingMetricsNode.innerHTML = [
      { label: "Parametri ottimali", value: formatParams(data.best_params) },
      { label: "Sharpe in-sample", value: fmt(data.sharpe_in_sample) },
      { label: "Sharpe out-of-sample", value: fmt(data.sharpe_out_of_sample) },
      { label: "Robustness score", value: fmt(data.robustness_score) },
      { label: "Combinazioni testate", value: `${data.combinations_tested ?? "—"}` },
      { label: "Train / Test", value: `${data.train_bars ?? "—"} / ${data.test_bars ?? "—"} barre` },
    ].map(({ label, value }) => `
      <div class="autosetting-metric">
        <span class="autosetting-metric-label">${escapeHtml(label)}</span>
        <span class="autosetting-metric-value">${escapeHtml(value)}</span>
      </div>
    `).join("");

    if (autosettingWarningNode) {
      if (data.overfitting_warning) {
        autosettingWarningNode.textContent = `⚠ ${data.overfitting_warning}`;
        autosettingWarningNode.hidden = false;
      } else {
        autosettingWarningNode.hidden = true;
      }
    }
  }

  function renderAutosettingChart(data, metric) {
    if (!autosettingChartNode || typeof Plotly === "undefined") return;

    const allScores = Array.isArray(data.all_scores) ? data.all_scores : [];
    const paramNames = Array.isArray(data.param_names) ? data.param_names : [];
    const bestParams = data.best_params || {};

    if (allScores.length === 0 || paramNames.length === 0) return;

    // Individua le 2 dimensioni con più valori unici (le più interessanti da visualizzare)
    const dimSizes = paramNames.map((name) => ({
      name,
      values: [...new Set(allScores.map((s) => s.params[name]))].sort((a, b) => a - b),
    }));
    dimSizes.sort((a, b) => b.values.length - a.values.length);

    const xDim = dimSizes[0];  // dimensione con più valori → asse X
    const yDim = dimSizes[1] || null;  // seconda dimensione → asse Y (null se solo 1 param)

    const metricKey = metric === "robustness" ? "robustness" : "sharpe";
    const metricLabel = metric === "robustness" ? "Robustness score" : "Sharpe ratio";

    if (yDim) {
      // Heatmap 2D
      const xVals = xDim.values;
      const yVals = yDim.values;

      // Per ogni (x, y) prende il massimo score tra tutti i valori delle altre dimensioni
      const zMatrix = yVals.map((y) =>
        xVals.map((x) => {
          const matches = allScores.filter(
            (s) => s.params[xDim.name] === x && s.params[yDim.name] === y,
          );
          if (!matches.length) return null;
          return Math.max(...matches.map((s) => s[metricKey] ?? s.sharpe));
        }),
      );

      // Marker per il vincitore autosetting
      const bestX = bestParams[xDim.name];
      const bestY = bestParams[yDim.name];

      const textMatrix = zMatrix.map((row) =>
        row.map((v) => (v !== null ? v.toFixed(2) : "")),
      );

      Plotly.react(
        autosettingChartNode,
        [
          {
            type: "heatmap",
            x: xVals,
            y: yVals,
            z: zMatrix,
            text: textMatrix,
            texttemplate: "%{text}",
            textfont: { size: 9, color: "rgba(255,255,255,0.85)" },
            colorscale: [
              [0, "#7f1d1d"],
              [0.3, "#b45309"],
              [0.5, "#374151"],
              [0.7, "#065f46"],
              [1, "#34d399"],
            ],
            hovertemplate: `${escapeHtml(xDim.name)}: %{x}<br>${escapeHtml(yDim.name)}: %{y}<br>${escapeHtml(metricLabel)}: %{z:.3f}<extra></extra>`,
            showscale: true,
            colorbar: {
              thickness: 12,
              len: 0.9,
              tickfont: { color: "#8d98b2", size: 10 },
              outlinewidth: 0,
            },
          },
          {
            type: "scatter",
            x: [bestX],
            y: [bestY],
            mode: "markers",
            marker: { symbol: "star", size: 16, color: "#38bdf8", line: { color: "#fff", width: 1.5 } },
            name: "Autosetting",
            hovertemplate: `Autosetting<br>${escapeHtml(xDim.name)}: %{x}<br>${escapeHtml(yDim.name)}: %{y}<extra></extra>`,
          },
        ],
        {
          paper_bgcolor: "transparent",
          plot_bgcolor: "#07111b",
          font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5", size: 11 },
          margin: { l: 52, r: 16, t: 10, b: 44 },
          xaxis: {
            title: { text: xDim.name, font: { size: 11, color: "#9ba7c2" } },
            tickfont: { color: "#8d98b2", size: 10 },
            gridcolor: "rgba(171,184,214,0.06)",
          },
          yaxis: {
            title: { text: yDim.name, font: { size: 11, color: "#9ba7c2" } },
            tickfont: { color: "#8d98b2", size: 10 },
            gridcolor: "rgba(171,184,214,0.06)",
          },
          height: 320,
          showlegend: false,
        },
        { responsive: true, displaylogo: false, displayModeBar: false },
      );

      // Click su cella → seleziona quei parametri
      autosettingChartNode.removeAllListeners?.("plotly_click");
      autosettingChartNode.on("plotly_click", (eventData) => {
        const point = eventData?.points?.[0];
        if (!point || point.curveNumber !== 0) return;
        const clicked = { ...bestParams };
        clicked[xDim.name] = point.x;
        clicked[yDim.name] = point.y;
        autosettingSelectedParams = clicked;
        updateAutosettingSelectedLabel(clicked, data);
        if (autosettingApplyBtn) autosettingApplyBtn.disabled = false;
      });
    } else {
      // Bar chart 1D (una sola dimensione significativa)
      const xVals = xDim.values;
      const yVals = xVals.map((x) => {
        const matches = allScores.filter((s) => s.params[xDim.name] === x);
        return matches.length ? Math.max(...matches.map((s) => s[metricKey] ?? s.sharpe)) : null;
      });

      Plotly.react(
        autosettingChartNode,
        [{
          type: "bar",
          x: xVals,
          y: yVals,
          marker: {
            color: yVals.map((v) => (v !== null && v === Math.max(...yVals.filter((n) => n !== null)) ? "#38bdf8" : "rgba(56,189,248,0.35)")),
          },
          hovertemplate: `${escapeHtml(xDim.name)}: %{x}<br>${escapeHtml(metricLabel)}: %{y:.3f}<extra></extra>`,
        }],
        {
          paper_bgcolor: "transparent",
          plot_bgcolor: "#07111b",
          font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5", size: 11 },
          margin: { l: 48, r: 16, t: 10, b: 44 },
          xaxis: { title: { text: xDim.name, font: { size: 11, color: "#9ba7c2" } }, tickfont: { color: "#8d98b2", size: 10 }, gridcolor: "rgba(171,184,214,0.06)" },
          yaxis: { title: { text: metricLabel, font: { size: 11, color: "#9ba7c2" } }, tickfont: { color: "#8d98b2", size: 10 }, gridcolor: "rgba(171,184,214,0.06)" },
          height: 280,
          showlegend: false,
        },
        { responsive: true, displaylogo: false, displayModeBar: false },
      );

      autosettingChartNode.on("plotly_click", (eventData) => {
        const point = eventData?.points?.[0];
        if (!point) return;
        const clicked = { ...bestParams };
        clicked[xDim.name] = point.x;
        autosettingSelectedParams = clicked;
        updateAutosettingSelectedLabel(clicked, data);
        if (autosettingApplyBtn) autosettingApplyBtn.disabled = false;
      });
    }
  }

  function updateAutosettingSelectedLabel(params, data) {
    if (!autosettingSelectedLabel) return;
    const isAutosetting = JSON.stringify(params) === JSON.stringify(data.best_params);
    const paramStr = formatParams(params);
    const tag = isAutosetting ? " (scelta autosetting ★)" : "";
    autosettingSelectedLabel.innerHTML = `Selezione: <strong>${escapeHtml(paramStr)}</strong><span style="color:#9ba7c2">${escapeHtml(tag)}</span>`;
  }

  function applyAutosettingParams(strategyId, params) {
    Object.entries(params).forEach(([paramName, value]) => {
      const fieldName = `${strategyId}__${paramName}`;
      const input = parameterInputs.find((el) => el.name === fieldName);
      if (input) input.value = value;
    });
    window.clearTimeout(debounceTimer);
    runPreview();
    if (statusNode) {
      statusNode.textContent = `Parametri applicati: ${formatParams(params)}`;
    }
  }

  function formatParams(params) {
    if (!params) return "—";
    return Object.entries(params).map(([k, v]) => `${k}=${v}`).join(", ");
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
});
