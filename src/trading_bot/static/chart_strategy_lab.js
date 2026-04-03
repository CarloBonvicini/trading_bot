document.addEventListener("DOMContentLoaded", () => {
  const configNode = document.getElementById("chart-strategy-lab-config");
  if (!configNode) {
    return;
  }

  const config = JSON.parse(configNode.textContent || "{}");
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
  const tradePreviewNode = document.querySelector("[data-live-trade-preview]");
  const resetButton = document.querySelector("[data-chart-preview-reset]");

  let debounceTimer = null;
  let requestCounter = 0;

  const initialState = captureState();
  renderComparisonCards(config.comparison_cards || []);
  renderTradePreview(config.trade_preview || []);
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

  function syncRuleSummary(previewLabel = config.baseline_label || "Sistema salvato") {
    const labels = activeStrategyIds()
      .map((strategyId) => config.strategies?.[strategyId]?.label)
      .filter(Boolean);
    const ruleLogic = ruleLogicSelect?.value || config.rule_logic || "all";
    const descriptor = ruleLogic === "any" ? "OR" : "AND";
    if (!ruleSummaryNode) {
      return;
    }
    if (labels.length > 1) {
      ruleSummaryNode.textContent = `Preview attuale: ${previewLabel}. Regole attive: ${labels.join(" + ")} con logica ${descriptor}.`;
      return;
    }
    ruleSummaryNode.textContent = `Preview attuale: ${previewLabel}. Regola attiva: ${labels[0] || "nessuna"}.`;
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
    renderComparisonCards(data.comparison_cards || []);
    renderTradePreview(data.trade_preview || []);
    if (badgeNode) {
      badgeNode.textContent = data.preview_label || "Preview live";
    }
    if (statusNode) {
      statusNode.textContent = `Grafico aggiornato su ${data.preview_label || "preview live"}.`;
    }
    syncRuleSummary(data.preview_label || "Preview live");
    window.tradingBotChartTerminal?.applyPreview(data.chart_payload || {}, data.preview_label || "Preview live");
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
    syncSections();
    renderComparisonCards(config.comparison_cards || []);
    renderTradePreview(config.trade_preview || []);
    if (badgeNode) {
      badgeNode.textContent = config.baseline_label || "Sistema salvato";
    }
    if (statusNode) {
      statusNode.textContent = "Baseline ripristinato. Il grafico mostra di nuovo solo il sistema salvato.";
    }
    syncRuleSummary(config.baseline_label || "Sistema salvato");
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

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
});
