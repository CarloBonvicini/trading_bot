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
      ruleSummaryNode.textContent = `Configurazione attuale: ${previewLabel}. Strategie attive: ${labels.join(" + ")} con logica ${descriptor}.`;
      return;
    }
    ruleSummaryNode.textContent = `Configurazione attuale: ${previewLabel}. Strategia attiva: ${labels[0] || "nessuna"}.`;
  }

  function schedulePreview() {
    if (statusNode) {
      statusNode.textContent = "Aggiorno la preview sul grafico...";
    }
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(runPreview, 260);
  }

  async function runPreview() {
    const requestId = ++requestCounter;
    const payload = buildPayload();

    try {
      const response = await fetch(config.preview_endpoint, {
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
        statusNode.textContent = error instanceof Error ? error.message : "Preview non disponibile.";
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
      statusNode.textContent = `Grafico aggiornato sulla configurazione attuale: ${data.preview_label || "configurazione attuale"}.`;
    }
    syncRuleSummary(data.preview_label || "Configurazione attuale");
    window.tradingBotChartTerminal?.applyPreview(data.chart_payload || {}, data.preview_label || "Configurazione attuale");
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
      statusNode.textContent = "Setup iniziale ripristinato. Il confronto resta sempre contro il buy & hold.";
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
        <span>${escapeHtml(card.hint ?? "")}</span>
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

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
});
