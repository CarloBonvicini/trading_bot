document.addEventListener("DOMContentLoaded", () => {
  const configNode = document.getElementById("index-page-config");
  if (!configNode) {
    return;
  }

  const pageConfig = JSON.parse(configNode.textContent);
  const strategyCatalog = pageConfig.strategies || {};
  const presetData = pageConfig.strategyPresets || [];
  const resumeBacktests = pageConfig.resumeBacktests || [];
  const intervalHints = pageConfig.intervalHints || {};
  const initialHomeTab = pageConfig.initialHomeTab || "dashboard";
  const presetsById = Object.fromEntries(presetData.map((preset) => [preset.id, preset]));
  const resumeBacktestsByName = Object.fromEntries(
    resumeBacktests.map((item) => [item.report_name, item]),
  );
  const homeTabTargetIds = {
    dashboard: "dashboard-home",
    setup: "launch-panel",
    strategies: "strategy-rules-panel",
    results: "saved-results-panel",
  };
  const homeTabPanels = Array.from(document.querySelectorAll("[data-home-tab-panel]"));
  const homeFormTabs = Array.from(document.querySelectorAll("[data-home-form-tab]"));

  const strategyToggles = Array.from(document.querySelectorAll("[data-strategy-toggle]"));
  const strategySweepToggles = Array.from(document.querySelectorAll("[data-strategy-sweep]"));
  const strategyToggleCards = Array.from(document.querySelectorAll("[data-strategy-toggle-card]"));
  const strategyEditButtons = Array.from(document.querySelectorAll("[data-strategy-edit]"));
  const resumeBacktestButtons = Array.from(document.querySelectorAll("[data-resume-backtest]"));
  const homeTabLinks = Array.from(document.querySelectorAll("[data-home-tab-link]"));
  const runModeSelect = document.getElementById("run-mode-select");
  const ruleLogicSelect = document.getElementById("rule-logic-select");
  const submitButton = document.getElementById("submit-button");
  const intervalSelect = document.getElementById("interval-select");
  const presetSelect = document.getElementById("preset-select");
  const continueToStrategiesButton = document.getElementById("continue-to-strategies");
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
  const sections = Array.from(document.querySelectorAll(".strategy-fields[data-strategy]"));
  const sweepOption = runModeSelect.querySelector('option[value="sweep"]');
  const intervalHint = document.getElementById("interval-hint");
  const symbolInput = document.querySelector('[name="symbol"]');
  const startInput = document.querySelector('[name="start"]');
  const endInput = document.querySelector('[name="end"]');
  const initialCapitalInput = document.querySelector('[name="initial_capital"]');
  const feeBpsInput = document.querySelector('[name="fee_bps"]');
  let currentModalStrategyId = "";

  function syncHomeFormTabs(tabId = "setup") {
    const activeFormTab = tabId === "strategies" ? "strategies" : "setup";
    const showFormTabs = tabId === "setup" || tabId === "strategies";

    homeFormTabs.forEach((panel) => {
      const isVisible = showFormTabs && panel.dataset.homeFormTab === activeFormTab;
      panel.hidden = !isVisible;
      panel.classList.toggle("is-active", isVisible);
    });
  }

  function activateHomeTab(tabId = "dashboard") {
    homeTabLinks.forEach((link) => {
      link.classList.toggle("is-active", link.dataset.homeTabLink === tabId);
      if (link.dataset.homeTabLink === tabId) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });

    homeTabPanels.forEach((panel) => {
      const visibleTabs = (panel.dataset.homeTabPanel || "").split(/\s+/).filter(Boolean);
      const isVisible = visibleTabs.includes(tabId);
      panel.hidden = !isVisible;
      panel.classList.toggle("is-active", isVisible);
    });

    syncHomeFormTabs(tabId);
  }

  function focusHomeTabTarget(tabId) {
    if (tabId === "setup") {
      symbolInput?.focus({ preventScroll: true });
      return;
    }
    if (tabId === "strategies") {
      const firstActiveToggle = strategyToggles.find((toggle) => toggle.checked);
      const focusTarget = firstActiveToggle || ruleLogicSelect;
      focusTarget?.focus({ preventScroll: true });
      return;
    }
    if (tabId === "results") {
      document.querySelector("#saved-results-panel .report-card")?.focus?.({ preventScroll: true });
    }
  }

  function scrollToHomeTab(tabId, { focus = false } = {}) {
    activateHomeTab(tabId);
    const targetId = homeTabTargetIds[tabId];
    if (window.history?.replaceState) {
      window.history.replaceState(null, "", `#${targetId}`);
    } else {
      window.location.hash = targetId;
    }

    if (focus) {
      window.setTimeout(() => focusHomeTabTarget(tabId), 220);
    }
  }

  function syncHomeTabFromHash() {
    const matchedTab = Object.entries(homeTabTargetIds).find(([, targetId]) => `#${targetId}` === window.location.hash)?.[0];
    activateHomeTab(matchedTab || initialHomeTab);
  }

  function getStrategyToggle(strategyId) {
    return strategyToggles.find((toggle) => toggle.value === strategyId) || null;
  }

  function setSectionInputsState(section, isEnabled) {
    section.querySelectorAll("input, select, textarea").forEach((field) => {
      field.disabled = !isEnabled;
    });
  }

  function activeStrategyIds() {
    return strategyToggles.filter((toggle) => toggle.checked).map((toggle) => toggle.value);
  }

  function ensureAtLeastOneActive(preferredStrategyId = "") {
    if (activeStrategyIds().length > 0) {
      return;
    }

    const fallbackToggle = getStrategyToggle(preferredStrategyId) || strategyToggles[0];
    if (fallbackToggle) {
      fallbackToggle.checked = true;
    }
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
    const previewLabels = labels.slice(0, 3).join(", ");
    return `${previewLabels} + altre ${labels.length - 3}`;
  }

  function updateRuleLogicHelp() {
    if (!ruleLogicHelp) {
      return;
    }

    if (ruleLogicSelect.value === "all") {
      ruleLogicHelp.textContent = "AND: il test entra solo quando tutte le regole attive danno segnale insieme.";
      return;
    }

    ruleLogicHelp.textContent = "OR: il test entra quando almeno una delle regole attive da' segnale.";
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

    currentBacktestLabel.textContent = `${symbol} • ${interval}`;
    currentBacktestMeta.textContent = `${start} -> ${end} • capitale ${capital} • fee ${feeBps} bps`;
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
    ensureAtLeastOneActive();
    const selectedIds = activeStrategyIds();
    const singleActiveStrategy = selectedIds.length === 1 ? selectedIds[0] : "";
    const activeSection = sections.find((section) => section.dataset.strategy === singleActiveStrategy);
    const sweepAvailable = Boolean(singleActiveStrategy && activeSection?.dataset.supportsSweep === "true");

    sweepOption.disabled = !sweepAvailable;
    if (!sweepAvailable && runModeSelect.value === "sweep") {
      runModeSelect.value = "single";
    }

    const selectedMode = runModeSelect.value;

    sections.forEach((section) => {
      const isActive = selectedIds.includes(section.dataset.strategy);
      const isSweepSection = section.dataset.strategy === singleActiveStrategy;
      section.classList.toggle("is-active", isActive);

      const parameterInputs = Array.from(section.querySelectorAll("[data-parameter-input]"));
      parameterInputs.forEach((field) => {
        field.disabled = !isActive;
      });

      const sweepBlocks = Array.from(section.querySelectorAll("[data-sweep-block]"));
      sweepBlocks.forEach((block) => {
        const isSweepActive = isActive && isSweepSection && selectedMode === "sweep" && sweepAvailable;
        block.classList.toggle("is-active", isSweepActive);
        setSectionInputsState(block, isSweepActive);
      });
    });

    document.querySelectorAll("[id^='strategy-mode-badge-']").forEach((badge) => {
      badge.textContent = selectedMode === "sweep" && sweepAvailable ? "Sweep multiplo" : "Test singolo";
    });

    submitButton.textContent = selectedMode === "sweep" && sweepAvailable ? "Avvia sweep" : "Avvia backtest";
    syncSweepControls(singleActiveStrategy, selectedMode === "sweep" && sweepAvailable);
    syncToggleCards();
  }

  function getSourceField(fieldName) {
    return document.querySelector(`[name="${fieldName}"]`);
  }

  function syncStrategyPickerCard() {
    ensureAtLeastOneActive();
    const selectedIds = activeStrategyIds();
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
    } else {
      strategyPickerLabel.textContent = `${selectedIds.length} regole attive`;
      strategyPickerDescription.textContent = usingAllRules
        ? "AND attivo: il test entra solo se tutte le regole selezionate sono vere nello stesso momento."
        : "OR attivo: il test entra se almeno una delle regole selezionate e' vera.";
      strategyPickerChip.textContent = usingAllRules ? "Tutte richieste" : "Ne basta una";
      strategyPickerChip.classList.add("strategy-chip-accent");
      strategyPickerRules.textContent = `Regole selezionate: ${rulePreview}.`;
    }
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
        : "La regola e' spenta: i valori restano salvati e verranno usati solo se riattivi il toggle.";
    }
  }

  function syncModalValuesFromForm() {
    modalInputs.forEach((field) => {
      const sourceField = getSourceField(field.dataset.modalInput);
      if (!sourceField) {
        return;
      }
      field.value = sourceField.value;
    });
  }

  function syncStrategyWorkspace() {
    syncCurrentBacktestCard();
    updateRuleLogicHelp();
    syncStrategyFields();
    syncStrategyPickerCard();
    syncStrategyModalState();
  }

  function openStrategyLab(strategyId = "") {
    const nextStrategyId = resolveModalStrategyId(strategyId);
    syncStrategyWorkspace();
    syncModalValuesFromForm();
    syncStrategyModalState(nextStrategyId);
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

    strategyToggles.forEach((toggle) => {
      toggle.checked = presetStrategyIds.includes(toggle.value);
    });
    ensureAtLeastOneActive(presetStrategyIds[0]);

    ruleLogicSelect.value = preset.rule_logic || "all";
    runModeSelect.value = preset.run_mode || "single";
    intervalSelect.value = preset.interval || intervalSelect.value;
    document.querySelector('[name="initial_capital"]').value = preset.initial_capital;
    document.querySelector('[name="fee_bps"]').value = preset.fee_bps;
    document.querySelector('[name="preset_name"]').value = preset.name;

    const parameterGroups = preset.parameters_by_strategy || { [preset.strategy]: preset.parameters || {} };
    Object.entries(parameterGroups).forEach(([strategyId, parameters]) => {
      Object.entries(parameters || {}).forEach(([parameterName, parameterValue]) => {
        const field = document.querySelector(`[name="${strategyId}__${parameterName}"]`);
        if (field) {
          field.value = parameterValue;
        }
      });
    });

    Object.entries(preset.sweep_settings || {}).forEach(([fieldName, fieldValue]) => {
      const field = document.querySelector(`[name="${fieldName}"]`);
      if (field) {
        field.value = fieldValue;
      }
    });

    syncStrategyWorkspace();
    syncModalValuesFromForm();
  }

  function applyFormSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== "object") {
      return;
    }

    presetSelect.value = "";

    Object.entries(snapshot).forEach(([fieldName, fieldValue]) => {
      if (fieldName === "active_strategies") {
        return;
      }

      const field = getSourceField(fieldName);
      if (!field || Array.isArray(fieldValue) || fieldValue === null || fieldValue === undefined) {
        return;
      }
      field.value = fieldValue;
    });

    const nextActiveIds = Array.isArray(snapshot.active_strategies) ? snapshot.active_strategies : [];
    strategyToggles.forEach((toggle) => {
      toggle.checked = nextActiveIds.includes(toggle.value);
    });
    ensureAtLeastOneActive(nextActiveIds[0]);

    syncStrategyWorkspace();
    syncModalValuesFromForm();
    syncIntervalHint();
  }

  function resumeBacktest(reportName) {
    const resumeItem = resumeBacktestsByName[reportName];
    if (!resumeItem) {
      return;
    }

    applyFormSnapshot(resumeItem.form_values || {});
    scrollToHomeTab("strategies", { focus: true });
  }

  function syncIntervalHint() {
    const selectedInterval = intervalSelect.value;
    intervalHint.textContent = intervalHints[selectedInterval] || "";
  }

  strategyToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      ensureAtLeastOneActive(toggle.value);
      syncStrategyWorkspace();
    });
  });
  strategySweepToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const strategyId = toggle.dataset.strategySweep || "";
      if (toggle.checked) {
        strategyToggles.forEach((strategyToggle) => {
          strategyToggle.checked = strategyToggle.value === strategyId;
        });
        runModeSelect.value = "sweep";
      } else if (runModeSelect.value === "sweep") {
        runModeSelect.value = "single";
      }
      ensureAtLeastOneActive(strategyId);
      syncStrategyWorkspace();
    });
  });
  ruleLogicSelect.addEventListener("change", syncStrategyWorkspace);
  runModeSelect.addEventListener("change", syncStrategyWorkspace);
  intervalSelect.addEventListener("change", syncIntervalHint);
  presetSelect.addEventListener("change", (event) => applyPreset(event.target.value));
  [symbolInput, startInput, endInput, intervalSelect, initialCapitalInput, feeBpsInput].forEach((field) => {
    field?.addEventListener("input", syncCurrentBacktestCard);
    field?.addEventListener("change", syncCurrentBacktestCard);
  });
  resumeBacktestButtons.forEach((button) => {
    button.addEventListener("click", () => resumeBacktest(button.dataset.resumeBacktest || ""));
  });
  homeTabLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      const tabId = link.dataset.homeTabLink || "dashboard";
      const href = link.getAttribute("href") || "";
      if (href.startsWith("#")) {
        event.preventDefault();
        scrollToHomeTab(tabId, { focus: tabId !== "dashboard" });
        return;
      }
      activateHomeTab(tabId);
    });
  });
  continueToStrategiesButton?.addEventListener("click", () => {
    scrollToHomeTab("strategies", { focus: true });
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
      const sourceField = getSourceField(field.dataset.modalInput);
      if (!sourceField) {
        return;
      }
      sourceField.value = field.value;
      syncStrategyWorkspace();
      syncModalValuesFromForm();
    };
    field.addEventListener("input", updateSource);
    field.addEventListener("change", updateSource);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !strategyModal.hidden) {
      closeStrategyLab();
    }
  });

  ensureAtLeastOneActive();
  syncStrategyWorkspace();
  syncModalValuesFromForm();
  syncIntervalHint();
  syncHomeTabFromHash();
  window.addEventListener("hashchange", syncHomeTabFromHash);
});
