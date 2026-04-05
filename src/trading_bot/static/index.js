const homeUiState = {
  keydownBound: false,
  popstateBound: false,
  currentBacktestStage: "setup",
  selectedSessionName: "",
};

function parseIndexConfig() {
  const configNode = document.getElementById("index-page-config");
  if (!configNode) {
    return null;
  }

  try {
    return JSON.parse(configNode.textContent);
  } catch {
    return null;
  }
}

function getHomeShell() {
  return document.querySelector("[data-home-tab-shell]");
}

function currentRelativeUrl() {
  return `${window.location.pathname}${window.location.search}`;
}

function normalizeRelativeUrl(rawUrl) {
  if (!rawUrl) {
    return "";
  }

  try {
    const resolved = new URL(rawUrl, window.location.origin);
    if (resolved.origin !== window.location.origin) {
      return "";
    }
    return `${resolved.pathname}${resolved.search}`;
  } catch {
    return "";
  }
}

function currentHomeTabFromView(viewName) {
  if (viewName === "results") {
    return "results";
  }
  if (viewName === "setup" || viewName === "strategies") {
    return "backtest";
  }
  return "dashboard";
}

function currentHomeTabFromLocation() {
  const pathname = window.location.pathname;
  if (pathname.startsWith("/history")) {
    return "results";
  }
  if (pathname.startsWith("/backtests/new") || pathname.startsWith("/strategies")) {
    return "backtest";
  }
  return "dashboard";
}

function currentBacktestStageFromLocation() {
  return window.location.pathname.startsWith("/strategies") ? "strategies" : "setup";
}

function activateBacktestStage(stageName = "setup") {
  const nextStage = stageName === "strategies" ? "strategies" : "setup";
  homeUiState.currentBacktestStage = nextStage;

  const setupPanel = document.getElementById("home-panel-setup");
  const strategyPanel = document.getElementById("home-panel-strategies");

  if (setupPanel) {
    const isActive = nextStage === "setup";
    setupPanel.hidden = !isActive;
    setupPanel.classList.toggle("is-active", isActive);
  }

  if (strategyPanel) {
    const isActive = nextStage === "strategies";
    strategyPanel.hidden = !isActive;
    strategyPanel.classList.toggle("is-active", isActive);
  }
}

function routeForHomeTab(tabName, pageConfig) {
  const homeRoutes = pageConfig?.homeRoutes || {};
  if (tabName === "results") {
    return homeRoutes.results || "/history";
  }
  if (tabName === "backtest") {
    return homeUiState.currentBacktestStage === "strategies"
      ? homeRoutes.strategies || "/strategies"
      : homeRoutes.setup || "/backtests/new";
  }
  return homeRoutes.dashboard || "/";
}

function renderSessionPreview(previewChart) {
  const chartNode = document.getElementById("session-preview-chart");
  if (!chartNode || !previewChart) {
    return;
  }

  chartNode.setAttribute("viewBox", `0 0 ${previewChart.width} ${previewChart.height}`);
  chartNode.replaceChildren();

  (previewChart.series || []).forEach((series) => {
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", series.points || "");
    polyline.setAttribute("stroke", series.color || "#3b82f6");
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-width", "3");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    chartNode.appendChild(polyline);
  });
}

function updateSessionWorkspace(pageConfig, sessionName, options = {}) {
  const { updateHistory = false } = options;
  const sessionItems = pageConfig?.sessionItems || [];
  const sessionItem = sessionItems.find((item) => item.name === sessionName) || sessionItems[0];
  if (!sessionItem) {
    return;
  }

  homeUiState.selectedSessionName = sessionItem.name;

  document.querySelectorAll("[data-session-selector]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.sessionSelector === sessionItem.name);
  });

  const summaryCard = document.getElementById("session-summary-card");
  summaryCard?.setAttribute("data-tone", sessionItem.tone || "neutral");

  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => {
    const node = byId(id);
    if (node) {
      node.textContent = value || "";
    }
  };

  setText("session-artifact-label", sessionItem.artifact_label);
  setText("session-title", sessionItem.title);
  setText("session-subtitle", sessionItem.subtitle);
  setText("session-stage-artifact", sessionItem.artifact_label);
  setText("session-stage-created", sessionItem.created_at_display);
  setText("session-metric-label", sessionItem.list_metric_label);
  setText("session-metric-value", sessionItem.list_metric);
  setText("session-period-label", sessionItem.period_label);
  setText("session-interval-label", `timeframe ${sessionItem.interval}`);
  setText("session-created-at", sessionItem.created_at_display);
  setText("session-description-interval", `timeframe ${sessionItem.interval}`);
  setText("session-description", sessionItem.description);
  setText("session-description-period", sessionItem.period_label);
  setText("session-description-created", sessionItem.created_at_display);
  setText("session-analytics-count", `${(sessionItem.metrics || []).length} metriche`);

  const openLink = byId("session-open-link");
  if (openLink) {
    openLink.textContent = sessionItem.open_label;
    openLink.setAttribute("href", sessionItem.open_url);
  }

  const resumeLink = byId("session-resume-link");
  if (resumeLink) {
    const hasResume = Boolean(sessionItem.resume_url);
    resumeLink.classList.toggle("is-hidden", !hasResume);
    resumeLink.setAttribute("href", hasResume ? sessionItem.resume_url : "#");
  }

  const metricsGrid = byId("session-metrics-grid");
  if (metricsGrid) {
    metricsGrid.replaceChildren();
    (sessionItem.metrics || []).forEach((metric) => {
      const article = document.createElement("article");
      article.className = "home-session-metric";

      const label = document.createElement("span");
      label.textContent = metric.label || "";
      const value = document.createElement("strong");
      value.textContent = metric.value || "";

      article.append(label, value);
      metricsGrid.appendChild(article);
    });
  }

  renderSessionPreview(sessionItem.preview_chart);

  if (updateHistory) {
    const nextUrl = `/history?session=${encodeURIComponent(sessionItem.name)}`;
    history.replaceState({ homeTab: "results" }, "", nextUrl);
  }
}

function activateHomeTab(tabName, pageConfig, options = {}) {
  const { updateHistory = false, explicitRoute = "" } = options;
  const nextTab = ["dashboard", "backtest", "results"].includes(tabName) ? tabName : "dashboard";
  const route = normalizeRelativeUrl(explicitRoute || routeForHomeTab(nextTab, pageConfig));

  document.querySelectorAll("[data-home-tab-button]").forEach((button) => {
    const isActive = button.dataset.homeTabButton === nextTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  document.querySelectorAll("[data-home-panel]").forEach((panel) => {
    const isActive = panel.dataset.homePanel === nextTab;
    panel.hidden = !isActive;
    panel.classList.toggle("is-active", isActive);
  });

  if (nextTab !== "backtest") {
    activateBacktestStage(homeUiState.currentBacktestStage);
  }

  if (updateHistory && route && route !== currentRelativeUrl()) {
    history.pushState({ homeTab: nextTab }, "", route);
  }
}

function bindGlobalHomeListeners(pageConfig) {
  if (!homeUiState.keydownBound) {
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") {
        return;
      }

      const strategyModal = document.getElementById("strategy-modal");
      if (!strategyModal || strategyModal.hidden) {
        return;
      }

      strategyModal.classList.remove("is-open");
      strategyModal.hidden = true;
      document.body.classList.remove("strategy-modal-open");
    });
    homeUiState.keydownBound = true;
  }

  if (!homeUiState.popstateBound) {
    window.addEventListener("popstate", () => {
      if (!getHomeShell()) {
        return;
      }
      activateBacktestStage(currentBacktestStageFromLocation());
      activateHomeTab(currentHomeTabFromLocation(), pageConfig, { updateHistory: false });
      const selectedSessionFromUrl = new URLSearchParams(window.location.search).get("session") || homeUiState.selectedSessionName;
      updateSessionWorkspace(pageConfig, selectedSessionFromUrl, { updateHistory: false });
    });
    homeUiState.popstateBound = true;
  }

  if (!history.state || !history.state.homeTab) {
    history.replaceState({ homeTab: currentHomeTabFromView(pageConfig?.currentHomeView) }, "", currentRelativeUrl());
  }
}

function bindHomeShellNavigation(pageConfig) {
  const shell = getHomeShell();
  if (!shell) {
    return;
  }

  const shellControls = Array.from(shell.querySelectorAll("[data-home-tab-button], [data-home-tab-trigger]"));

  shellControls.forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();

      const requestedTab = control.dataset.homeTabButton || control.dataset.homeTabTrigger || "dashboard";
      const normalizedTab = requestedTab === "setup" || requestedTab === "strategies" ? "backtest" : requestedTab;
      const requestedStage = control.dataset.homeBacktestStage || "";
      const explicitRoute = control.dataset.homeTabRoute || routeForHomeTab(normalizedTab, pageConfig);

      if (normalizedTab === "backtest" && requestedStage) {
        const stagePanel = requestedStage === "strategies"
          ? document.getElementById("home-panel-strategies")
          : document.getElementById("home-panel-setup");

        if (!stagePanel && explicitRoute) {
          window.location.assign(explicitRoute);
          return;
        }

        activateBacktestStage(requestedStage);
      }

      activateHomeTab(normalizedTab, pageConfig, {
        updateHistory: true,
        explicitRoute,
      });
    });
  });
}

function bindSessionWorkspace(pageConfig) {
  const selectors = Array.from(document.querySelectorAll("[data-session-selector]"));
  if (selectors.length === 0) {
    return;
  }

  selectors.forEach((button) => {
    button.addEventListener("click", () => {
      const openUrl = button.dataset.sessionOpenUrl || "";
      if (openUrl) {
        window.location.assign(openUrl);
        return;
      }

      updateSessionWorkspace(pageConfig, button.dataset.sessionSelector || "", { updateHistory: true });
    });
  });
}

function setupStrategyWorkspace(pageConfig) {
  const strategyCatalog = pageConfig?.strategies || {};
  const presetData = pageConfig?.strategyPresets || [];
  const intervalHints = pageConfig?.intervalHints || {};
  const intervalLookbackDays = pageConfig?.intervalLookbackDays || {};
  const presetsById = Object.fromEntries(presetData.map((preset) => [preset.id, preset]));

  const setupForm = document.getElementById("setup-form");
  const strategyForm = document.getElementById("strategy-form");
  const strategyToggles = Array.from(strategyForm?.querySelectorAll("[data-strategy-toggle]") || []);
  const strategySweepToggles = Array.from(strategyForm?.querySelectorAll("[data-strategy-sweep]") || []);
  const strategyToggleCards = Array.from(strategyForm?.querySelectorAll("[data-strategy-toggle-card]") || []);
  const strategyEditButtons = Array.from(strategyForm?.querySelectorAll("[data-strategy-edit]") || []);
  const hiddenActiveStrategies = document.getElementById("setup-hidden-active-strategies");
  const setupRunModeSelect = document.getElementById("setup-run-mode-select");
  const strategyRunModeSelect = document.getElementById("strategy-run-mode-select");
  const runModeSelect = strategyRunModeSelect || setupRunModeSelect;
  const setupRuleLogicSelect = document.getElementById("setup-rule-logic-select");
  const strategyRuleLogicSelect = document.getElementById("strategy-rule-logic-select");
  const ruleLogicSelect = strategyRuleLogicSelect || setupRuleLogicSelect;
  const submitButton = document.getElementById("submit-button");
  const intervalSelect = document.getElementById("setup-interval-select");
  const strategyIntervalInput = document.getElementById("strategy-interval-input");
  const presetSelect = document.getElementById("setup-preset-select");
  const ruleLogicHelp = document.getElementById("rule-logic-help");
  const strategyPickerLabel = document.getElementById("strategy-picker-label");
  const strategyPickerDescription = document.getElementById("strategy-picker-description");
  const strategyPickerChip = document.getElementById("strategy-picker-chip");
  const strategyPickerRules = document.getElementById("strategy-picker-rules");
  const currentBacktestLabel = document.getElementById("current-backtest-label");
  const currentBacktestMeta = document.getElementById("current-backtest-meta");
  const applyStrategyLabButton = document.getElementById("apply-strategy-lab");
  const strategyModal = document.getElementById("strategy-modal");
  const strategyModalTitle = document.getElementById("strategy-modal-title");
  const strategyModalCopy = document.getElementById("strategy-modal-copy");
  const strategyModalState = document.getElementById("strategy-modal-state");
  const strategyModalMode = document.getElementById("strategy-modal-mode");
  const strategyModalFooterNote = document.getElementById("strategy-modal-footer-note");
  const strategyDetailPanels = Array.from(document.querySelectorAll("[data-modal-strategy]"));
  const modalInputs = Array.from(document.querySelectorAll("[data-modal-input]"));
  const modalCloseButtons = Array.from(document.querySelectorAll("[data-close-strategy-modal]"));
  const sections = Array.from(strategyForm?.querySelectorAll(".strategy-fields[data-strategy]") || []);
  const sweepOption = runModeSelect?.querySelector('option[value="sweep"]') || null;
  const intervalHint = document.getElementById("interval-hint");
  const intervalAutoAdjustNote = document.getElementById("interval-auto-adjust-note");
  const symbolInput = setupForm?.querySelector('[name="symbol"]') || null;
  const startInput = setupForm?.querySelector('[name="start"]') || null;
  const endInput = setupForm?.querySelector('[name="end"]') || null;
  const initialCapitalInput = setupForm?.querySelector('[name="initial_capital"]') || null;
  const feeBpsInput = setupForm?.querySelector('[name="fee_bps"]') || null;
  let currentModalStrategyId = "";

  function namedFields(fieldName) {
    return Array.from(document.getElementsByName(fieldName));
  }

  function setNamedFieldValue(fieldName, value, sourceField = null) {
    namedFields(fieldName).forEach((field) => {
      if (field === sourceField || field.type === "checkbox" || field.type === "radio") {
        return;
      }
      field.value = value;
    });
  }

  function getSourceField(fieldName) {
    return strategyForm?.querySelector(`[name="${fieldName}"]`)
      || setupForm?.querySelector(`[name="${fieldName}"]`)
      || namedFields(fieldName)[0]
      || null;
  }

  function syncCoreFieldsFromSetup() {
    if (symbolInput) {
      setNamedFieldValue("symbol", symbolInput.value, symbolInput);
    }
    if (startInput) {
      setNamedFieldValue("start", startInput.value, startInput);
    }
    if (endInput) {
      setNamedFieldValue("end", endInput.value, endInput);
    }
    if (intervalSelect) {
      setNamedFieldValue("interval", intervalSelect.value, intervalSelect);
    }
    if (strategyIntervalInput && intervalSelect) {
      strategyIntervalInput.value = intervalSelect.value;
    }
    if (initialCapitalInput) {
      setNamedFieldValue("initial_capital", initialCapitalInput.value, initialCapitalInput);
    }
    if (feeBpsInput) {
      setNamedFieldValue("fee_bps", feeBpsInput.value, feeBpsInput);
    }

    const presetNameField = setupForm?.querySelector('[name="preset_name"]');
    if (presetNameField) {
      setNamedFieldValue("preset_name", presetNameField.value, presetNameField);
    }
    if (setupRunModeSelect) {
      setNamedFieldValue("run_mode", setupRunModeSelect.value, setupRunModeSelect);
    }
    if (setupRuleLogicSelect) {
      setNamedFieldValue("rule_logic", setupRuleLogicSelect.value, setupRuleLogicSelect);
    }
  }

  function syncCoreFieldsFromStrategy() {
    if (strategyRunModeSelect) {
      setNamedFieldValue("run_mode", strategyRunModeSelect.value, strategyRunModeSelect);
    }
    if (strategyRuleLogicSelect) {
      setNamedFieldValue("rule_logic", strategyRuleLogicSelect.value, strategyRuleLogicSelect);
    }
  }

  function uniqueStrategyIds(strategyIds) {
    const normalized = [];
    strategyIds.forEach((strategyId) => {
      const normalizedId = String(strategyId || "").trim();
      if (!normalizedId || normalized.includes(normalizedId)) {
        return;
      }
      normalized.push(normalizedId);
    });
    return normalized;
  }

  function hiddenActiveStrategyInputs() {
    return hiddenActiveStrategies
      ? Array.from(hiddenActiveStrategies.querySelectorAll("[data-hidden-active-strategy]"))
      : [];
  }

  function setHiddenActiveStrategies(strategyIds) {
    if (!hiddenActiveStrategies) {
      return;
    }

    hiddenActiveStrategies.replaceChildren();
    uniqueStrategyIds(strategyIds).forEach((strategyId) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "active_strategies";
      input.value = strategyId;
      input.dataset.hiddenActiveStrategy = "true";
      hiddenActiveStrategies.appendChild(input);
    });
  }

  function activeStrategyIds() {
    if (strategyToggles.length > 0) {
      return strategyToggles.filter((toggle) => toggle.checked).map((toggle) => toggle.value);
    }
    return hiddenActiveStrategyInputs().map((input) => input.value);
  }

  function setActiveStrategies(strategyIds) {
    const nextStrategyIds = uniqueStrategyIds(strategyIds);

    if (strategyToggles.length > 0) {
      strategyToggles.forEach((toggle) => {
        toggle.checked = nextStrategyIds.includes(toggle.value);
      });
    }

    setHiddenActiveStrategies(nextStrategyIds);
  }

  function ensureAtLeastOneActive(preferredStrategyId = "") {
    const currentlyActive = activeStrategyIds();
    if (currentlyActive.length > 0) {
      return currentlyActive;
    }

    const fallbackStrategyId = preferredStrategyId
      || strategyToggles[0]?.value
      || Object.keys(strategyCatalog)[0]
      || "";

    if (fallbackStrategyId) {
      setActiveStrategies([fallbackStrategyId]);
      return [fallbackStrategyId];
    }
    return [];
  }

  function setSectionInputsState(section, isEnabled) {
    section.querySelectorAll("input, select, textarea").forEach((field) => {
      field.disabled = !isEnabled;
    });
  }

  function activeRuleLabels() {
    return activeStrategyIds()
      .map((strategyId) => strategyCatalog[strategyId]?.label)
      .filter(Boolean);
  }

  function buildActiveRulePreview(labels) {
    if (labels.length <= 3) {
      return labels.join(", ");
    }
    return `${labels.slice(0, 3).join(", ")} + altre ${labels.length - 3}`;
  }

  function updateRuleLogicHelp() {
    if (!ruleLogicHelp || !ruleLogicSelect) {
      return;
    }

    ruleLogicHelp.textContent = ruleLogicSelect.value === "all"
      ? "AND: il test entra solo quando tutte le regole attive danno segnale insieme."
      : "OR: il test entra quando almeno una delle regole attive da segnale.";
  }

  function formatBacktestNumber(value) {
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
      return String(value || "").trim() || "n/d";
    }

    return new Intl.NumberFormat("it-IT", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(numericValue);
  }

  function syncCurrentBacktestCard() {
    if (!currentBacktestLabel || !currentBacktestMeta) {
      return;
    }

    const symbol = (symbolInput?.value || "").trim().toUpperCase() || "Simbolo";
    const interval = (intervalSelect?.value || "").trim() || "n/d";
    const start = (startInput?.value || "").trim() || "data iniziale";
    const end = (endInput?.value || "").trim() || "data finale";
    const capital = formatBacktestNumber(initialCapitalInput?.value);
    const feeBps = formatBacktestNumber(feeBpsInput?.value);

    currentBacktestLabel.textContent = `${symbol} - ${interval}`;
    currentBacktestMeta.textContent = `${start} -> ${end} - capitale ${capital} - fee ${feeBps} bps`;
  }

  function syncToggleCards() {
    const selectedIds = activeStrategyIds();
    strategyToggleCards.forEach((card) => {
      card.classList.toggle("is-active", selectedIds.includes(card.dataset.strategyToggleCard));
    });
  }

  function syncSweepControls(activeStrategyId, sweepActive) {
    strategySweepToggles.forEach((toggle) => {
      toggle.checked = sweepActive && toggle.dataset.strategySweep === activeStrategyId;
    });
  }

  function syncStrategyFields() {
    if (sections.length === 0 || !runModeSelect) {
      return;
    }

    const selectedIds = ensureAtLeastOneActive();
    const singleActiveStrategy = selectedIds.length === 1 ? selectedIds[0] : "";
    const activeSection = sections.find((section) => section.dataset.strategy === singleActiveStrategy);
    const sweepAvailable = Boolean(singleActiveStrategy && activeSection?.dataset.supportsSweep === "true");

    if (sweepOption) {
      sweepOption.disabled = !sweepAvailable;
      if (!sweepAvailable && runModeSelect.value === "sweep") {
        runModeSelect.value = "single";
      }
    }

    const selectedMode = runModeSelect.value;

    sections.forEach((section) => {
      const isActive = selectedIds.includes(section.dataset.strategy);
      const isSweepSection = section.dataset.strategy === singleActiveStrategy;
      section.classList.toggle("is-active", isActive);

      section.querySelectorAll("[data-parameter-input]").forEach((field) => {
        field.disabled = !isActive;
      });

      section.querySelectorAll("[data-sweep-block]").forEach((block) => {
        const isSweepActive = isActive && isSweepSection && selectedMode === "sweep" && sweepAvailable;
        block.classList.toggle("is-active", isSweepActive);
        setSectionInputsState(block, isSweepActive);
      });
    });

    strategyForm?.querySelectorAll("[data-strategy-mode-badge]").forEach((badge) => {
      badge.textContent = selectedMode === "sweep" && sweepAvailable ? "Sweep multiplo" : "Test singolo";
    });

    if (submitButton) {
      submitButton.textContent = selectedMode === "sweep" && sweepAvailable ? "Avvia sweep" : "Avvia backtest";
    }

    syncSweepControls(singleActiveStrategy, selectedMode === "sweep" && sweepAvailable);
    syncToggleCards();
  }

  function syncStrategyPickerCard() {
    if (!strategyPickerLabel || !strategyPickerDescription || !strategyPickerChip || !strategyPickerRules || !ruleLogicSelect) {
      return;
    }

    const selectedIds = ensureAtLeastOneActive();
    const labels = activeRuleLabels();
    const rulePreview = buildActiveRulePreview(labels);
    const usingAllRules = ruleLogicSelect.value === "all";

    if (selectedIds.length === 1) {
      const strategy = strategyCatalog[selectedIds[0]];
      strategyPickerLabel.textContent = strategy?.label || "1 regola attiva";
      strategyPickerDescription.textContent = "Regola singola: il test usa solo questa strategia per costruire il segnale.";
      strategyPickerChip.textContent = strategy?.supports_sweep ? "Sweep disponibile" : "Test singolo";
      strategyPickerChip.classList.toggle("strategy-chip-accent", Boolean(strategy?.supports_sweep));
      strategyPickerRules.textContent = `Attiva: ${rulePreview}.`;
      return;
    }

    strategyPickerLabel.textContent = `${selectedIds.length} regole attive`;
    strategyPickerDescription.textContent = usingAllRules
      ? "AND attivo: il test entra solo se tutte le regole selezionate sono vere nello stesso momento."
      : "OR attivo: il test entra se almeno una delle regole selezionate e vera.";
    strategyPickerChip.textContent = usingAllRules ? "Tutte richieste" : "Ne basta una";
    strategyPickerChip.classList.add("strategy-chip-accent");
    strategyPickerRules.textContent = `Regole selezionate: ${rulePreview}.`;
  }

  function resolveModalStrategyId(preferredStrategyId = "") {
    if (preferredStrategyId && strategyCatalog[preferredStrategyId]) {
      return preferredStrategyId;
    }
    if (currentModalStrategyId && strategyCatalog[currentModalStrategyId]) {
      return currentModalStrategyId;
    }
    return activeStrategyIds()[0] || Object.keys(strategyCatalog)[0] || "";
  }

  function syncStrategyModalState(preferredStrategyId = "") {
    if (!strategyModal || strategyDetailPanels.length === 0) {
      return;
    }

    const strategyId = resolveModalStrategyId(preferredStrategyId);
    const strategy = strategyCatalog[strategyId];
    const isActive = activeStrategyIds().includes(strategyId);
    currentModalStrategyId = strategyId;

    strategyDetailPanels.forEach((panel) => {
      const isVisible = panel.dataset.modalStrategy === strategyId;
      panel.classList.toggle("is-active", isVisible);
      panel.hidden = !isVisible;
    });

    if (strategyModalTitle) {
      strategyModalTitle.textContent = strategy?.label || "Editor strategia";
    }
    if (strategyModalCopy) {
      strategyModalCopy.textContent = strategy?.description || "Regola i parametri della strategia selezionata.";
    }
    if (strategyModalState) {
      strategyModalState.textContent = isActive ? "Regola attiva" : "Regola spenta";
      strategyModalState.classList.toggle("strategy-chip-accent", isActive);
    }
    if (strategyModalMode) {
      strategyModalMode.textContent = strategy?.supports_sweep ? "Supporta sweep" : "Solo test singolo";
    }
    if (strategyModalFooterNote) {
      strategyModalFooterNote.textContent = isActive
        ? "Modifichi direttamente i valori usati nel backtest corrente."
        : "La regola e spenta: i valori restano salvati e verranno usati solo se riattivi il toggle.";
    }
  }

  function syncModalValuesFromForm() {
    modalInputs.forEach((field) => {
      const sourceField = getSourceField(field.dataset.modalInput);
      if (sourceField) {
        field.value = sourceField.value;
      }
    });
  }

  function syncStrategyWorkspace() {
    ensureAtLeastOneActive();
    syncCurrentBacktestCard();
    updateRuleLogicHelp();
    syncStrategyFields();
    syncStrategyPickerCard();
    syncStrategyModalState();
  }

  function openStrategyLab(strategyId = "") {
    if (!strategyModal) {
      return;
    }

    syncStrategyWorkspace();
    syncModalValuesFromForm();
    syncStrategyModalState(strategyId);
    strategyModal.hidden = false;
    requestAnimationFrame(() => {
      strategyModal.classList.add("is-open");
      strategyDetailPanels
        .find((panel) => panel.dataset.modalStrategy === currentModalStrategyId)
        ?.querySelector("input, select, textarea")
        ?.focus({ preventScroll: true });
    });
    document.body.classList.add("strategy-modal-open");
  }

  function closeStrategyLab() {
    if (!strategyModal) {
      return;
    }

    strategyModal.classList.remove("is-open");
    strategyModal.hidden = true;
    document.body.classList.remove("strategy-modal-open");
  }

  function applyPreset(presetId) {
    const preset = presetsById[presetId];
    if (!preset) {
      return;
    }

    const presetStrategyIds = preset.active_strategy_ids
      || (preset.active_rules || []).map((rule) => rule.strategy)
      || [preset.strategy].filter(Boolean);

    setActiveStrategies(presetStrategyIds);
    ensureAtLeastOneActive(presetStrategyIds[0]);

    if (intervalSelect) {
      intervalSelect.value = preset.interval || intervalSelect.value;
    }
    setNamedFieldValue("rule_logic", preset.rule_logic || "all");
    setNamedFieldValue("run_mode", preset.run_mode || "single");
    setNamedFieldValue("preset_name", preset.name);
    if (initialCapitalInput) {
      initialCapitalInput.value = preset.initial_capital;
    }
    if (feeBpsInput) {
      feeBpsInput.value = preset.fee_bps;
    }

    const parameterGroups = preset.parameters_by_strategy || { [preset.strategy]: preset.parameters || {} };
    Object.entries(parameterGroups).forEach(([strategyId, parameters]) => {
      Object.entries(parameters || {}).forEach(([parameterName, parameterValue]) => {
        setNamedFieldValue(`${strategyId}__${parameterName}`, parameterValue);
      });
    });

    Object.entries(preset.sweep_settings || {}).forEach(([fieldName, fieldValue]) => {
      setNamedFieldValue(fieldName, fieldValue);
    });

    syncIntervalDateWindow({ announce: true });
    syncCoreFieldsFromSetup();
    syncCoreFieldsFromStrategy();
    syncStrategyWorkspace();
    syncModalValuesFromForm();
    syncIntervalHint();
  }

  function syncIntervalHint() {
    if (!intervalHint || !intervalSelect) {
      return;
    }

    intervalHint.textContent = intervalHints[intervalSelect.value] || "";
  }

  function parseDateInputValue(value) {
    const rawValue = String(value || "").trim();
    if (!rawValue) {
      return null;
    }

    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(rawValue);
    if (!match) {
      return null;
    }

    const parsed = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    parsed.setHours(0, 0, 0, 0);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatDateInputValue(dateValue) {
    const year = dateValue.getFullYear();
    const month = String(dateValue.getMonth() + 1).padStart(2, "0");
    const day = String(dateValue.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function resolveAllowedDateWindow(intervalValue) {
    const lookbackDays = Number(intervalLookbackDays[intervalValue]);
    if (!Number.isFinite(lookbackDays) || lookbackDays <= 0) {
      return null;
    }

    const referenceNow = new Date();
    const latestEnd = new Date(referenceNow.getFullYear(), referenceNow.getMonth(), referenceNow.getDate());
    const oldestAllowed = new Date(referenceNow.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
    const earliestStart = new Date(oldestAllowed.getFullYear(), oldestAllowed.getMonth(), oldestAllowed.getDate());
    if (
      oldestAllowed.getHours() !== 0
      || oldestAllowed.getMinutes() !== 0
      || oldestAllowed.getSeconds() !== 0
      || oldestAllowed.getMilliseconds() !== 0
    ) {
      earliestStart.setDate(earliestStart.getDate() + 1);
    }

    if (earliestStart >= latestEnd) {
      earliestStart.setDate(latestEnd.getDate() - 1);
    }

    return {
      lookbackDays,
      startDate: earliestStart,
      endDate: latestEnd,
      startValue: formatDateInputValue(earliestStart),
      endValue: formatDateInputValue(latestEnd),
    };
  }

  function setIntervalAutoAdjustMessage(message = "") {
    if (!intervalAutoAdjustNote) {
      return;
    }

    intervalAutoAdjustNote.textContent = message;
    intervalAutoAdjustNote.classList.toggle("is-hidden", !message);
  }

  function syncIntervalDateWindow(options = {}) {
    const { announce = false } = options;
    if (!intervalSelect || !startInput || !endInput) {
      return false;
    }

    const allowedWindow = resolveAllowedDateWindow(intervalSelect.value);
    if (!allowedWindow) {
      startInput.removeAttribute("min");
      startInput.removeAttribute("max");
      endInput.removeAttribute("min");
      endInput.removeAttribute("max");
      setIntervalAutoAdjustMessage("");
      return false;
    }

    startInput.min = allowedWindow.startValue;
    startInput.max = allowedWindow.endValue;
    endInput.min = allowedWindow.startValue;
    endInput.max = allowedWindow.endValue;

    const currentStart = parseDateInputValue(startInput.value);
    const currentEnd = parseDateInputValue(endInput.value);
    const needsAdjustment = !currentStart
      || !currentEnd
      || currentStart < allowedWindow.startDate
      || currentEnd > allowedWindow.endDate
      || currentEnd <= currentStart;

    if (!needsAdjustment) {
      setIntervalAutoAdjustMessage("");
      return false;
    }

    startInput.value = allowedWindow.startValue;
    endInput.value = allowedWindow.endValue;
    if (announce) {
      setIntervalAutoAdjustMessage(
        `Date aggiornate automaticamente su ${allowedWindow.startValue} -> ${allowedWindow.endValue} per il timeframe ${intervalSelect.value}.`,
      );
    }
    return true;
  }

  strategyToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      setHiddenActiveStrategies(strategyToggles.filter((field) => field.checked).map((field) => field.value));
      ensureAtLeastOneActive(toggle.value);
      syncStrategyWorkspace();
    });
  });

  strategySweepToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const strategyId = toggle.dataset.strategySweep || "";
      if (toggle.checked) {
        setActiveStrategies([strategyId]);
        if (runModeSelect) {
          runModeSelect.value = "sweep";
        }
        syncCoreFieldsFromStrategy();
      } else if (runModeSelect?.value === "sweep") {
        runModeSelect.value = "single";
        syncCoreFieldsFromStrategy();
      }
      ensureAtLeastOneActive(strategyId);
      syncStrategyWorkspace();
    });
  });

  setupForm?.addEventListener("submit", (event) => {
    const submitter = event.submitter;
    if (submitter?.getAttribute("formaction")) {
      return;
    }

    event.preventDefault();
    syncIntervalDateWindow({ announce: true });
    syncCoreFieldsFromSetup();
    activateBacktestStage("strategies");
    activateHomeTab("backtest", pageConfig, {
      updateHistory: true,
      explicitRoute: pageConfig?.homeRoutes?.strategies || "/strategies",
    });
    syncStrategyWorkspace();
    syncModalValuesFromForm();
  });

  setupRunModeSelect?.addEventListener("change", () => {
    syncCoreFieldsFromSetup();
    syncStrategyWorkspace();
  });
  strategyRuleLogicSelect?.addEventListener("change", () => {
    syncCoreFieldsFromStrategy();
    syncStrategyWorkspace();
  });
  strategyRunModeSelect?.addEventListener("change", () => {
    syncCoreFieldsFromStrategy();
    syncStrategyWorkspace();
  });
  intervalSelect?.addEventListener("change", () => {
    syncIntervalDateWindow({ announce: true });
    syncCoreFieldsFromSetup();
    syncIntervalHint();
    syncCurrentBacktestCard();
  });
  presetSelect?.addEventListener("change", (event) => applyPreset(event.target.value));

  [symbolInput, startInput, endInput, intervalSelect, initialCapitalInput, feeBpsInput].forEach((field) => {
    field?.addEventListener("input", () => {
      syncCoreFieldsFromSetup();
      syncCurrentBacktestCard();
    });
    field?.addEventListener("change", () => {
      syncCoreFieldsFromSetup();
      syncCurrentBacktestCard();
    });
  });

  strategyEditButtons.forEach((button) => {
    button.addEventListener("click", () => openStrategyLab(button.dataset.strategyEdit || ""));
  });

  applyStrategyLabButton?.addEventListener("click", closeStrategyLab);
  modalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeStrategyLab);
  });

  modalInputs.forEach((field) => {
    const updateSource = () => {
      setNamedFieldValue(field.dataset.modalInput, field.value);
      syncStrategyWorkspace();
      syncModalValuesFromForm();
    };
    field.addEventListener("input", updateSource);
    field.addEventListener("change", updateSource);
  });

  syncCoreFieldsFromSetup();
  syncCoreFieldsFromStrategy();
  syncIntervalDateWindow({ announce: false });
  syncCoreFieldsFromSetup();
  ensureAtLeastOneActive();
  syncStrategyWorkspace();
  syncModalValuesFromForm();
  syncIntervalHint();

  strategyForm?.addEventListener("submit", () => {
    syncIntervalDateWindow({ announce: false });
    syncCoreFieldsFromSetup();
  });
}

function mountHomePage() {
  const pageConfig = parseIndexConfig();
  if (!pageConfig) {
    return;
  }

  homeUiState.currentBacktestStage = pageConfig.currentHomeView === "strategies" ? "strategies" : "setup";
  homeUiState.selectedSessionName = pageConfig.selectedSessionName || "";
  activateBacktestStage(homeUiState.currentBacktestStage);
  activateHomeTab(currentHomeTabFromView(pageConfig.currentHomeView), pageConfig, { updateHistory: false });

  bindGlobalHomeListeners(pageConfig);
  bindHomeShellNavigation(pageConfig);
  bindSessionWorkspace(pageConfig);
  updateSessionWorkspace(pageConfig, homeUiState.selectedSessionName, { updateHistory: false });
  setupStrategyWorkspace(pageConfig);
}

document.addEventListener("DOMContentLoaded", mountHomePage);
