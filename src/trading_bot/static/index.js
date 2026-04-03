document.addEventListener("DOMContentLoaded", () => {
  const configNode = document.getElementById("index-page-config");
  if (!configNode) {
    return;
  }

  const pageConfig = JSON.parse(configNode.textContent);
  const strategyCatalog = pageConfig.strategies || {};
  const presetData = pageConfig.strategyPresets || [];
  const intervalHints = pageConfig.intervalHints || {};
  const presetsById = Object.fromEntries(presetData.map((preset) => [preset.id, preset]));

  const strategyToggles = Array.from(document.querySelectorAll("[data-strategy-toggle]"));
  const strategyToggleCards = Array.from(document.querySelectorAll("[data-strategy-toggle-card]"));
  const strategyEditButtons = Array.from(document.querySelectorAll("[data-strategy-edit]"));
  const runModeSelect = document.getElementById("run-mode-select");
  const ruleLogicSelect = document.getElementById("rule-logic-select");
  const submitButton = document.getElementById("submit-button");
  const intervalSelect = document.getElementById("interval-select");
  const presetSelect = document.getElementById("preset-select");
  const strategyPickerLabel = document.getElementById("strategy-picker-label");
  const strategyPickerDescription = document.getElementById("strategy-picker-description");
  const strategyPickerChip = document.getElementById("strategy-picker-chip");
  const strategyPickerRules = document.getElementById("strategy-picker-rules");
  const openStrategyLabButton = document.getElementById("open-strategy-lab");
  const applyStrategyLabButton = document.getElementById("apply-strategy-lab");
  const strategyModal = document.getElementById("strategy-modal");
  const strategyModalSummary = document.getElementById("strategy-modal-summary");
  const strategyChoiceCards = Array.from(document.querySelectorAll("[data-strategy-choice]"));
  const strategyDetailPanels = Array.from(document.querySelectorAll("[data-modal-strategy]"));
  const modalInputs = Array.from(document.querySelectorAll("[data-modal-input]"));
  const modalCloseButtons = Array.from(document.querySelectorAll("[data-close-strategy-modal]"));
  const sections = Array.from(document.querySelectorAll(".strategy-fields[data-strategy]"));
  const sweepOption = runModeSelect.querySelector('option[value="sweep"]');
  const intervalHint = document.getElementById("interval-hint");

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

  function toggleStrategyActivation(strategyId) {
    const toggle = getStrategyToggle(strategyId);
    if (!toggle) {
      return;
    }

    const selectedIds = activeStrategyIds();
    if (toggle.checked && selectedIds.length === 1) {
      return;
    }

    toggle.checked = !toggle.checked;
    ensureAtLeastOneActive(strategyId);
    syncStrategyWorkspace();
    syncModalValuesFromForm();
  }

  function syncToggleCards() {
    const selectedIds = activeStrategyIds();

    strategyToggleCards.forEach((card) => {
      card.classList.toggle("is-active", selectedIds.includes(card.dataset.strategyToggleCard));
    });
    strategyChoiceCards.forEach((card) => {
      card.classList.toggle("is-active", selectedIds.includes(card.dataset.strategyChoice));
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
    syncToggleCards();
  }

  function getSourceField(fieldName) {
    return document.querySelector(`[name="${fieldName}"]`);
  }

  function syncStrategyPickerCard() {
    ensureAtLeastOneActive();
    const selectedIds = activeStrategyIds();
    const labels = activeRuleLabels();

    if (selectedIds.length === 1) {
      const strategy = strategyCatalog[selectedIds[0]];
      strategyPickerLabel.textContent = strategy?.label || "1 regola attiva";
      strategyPickerDescription.textContent = strategy?.description || "";
      strategyPickerChip.textContent = strategy?.supports_sweep ? "Sweep disponibile" : "Test singolo";
      strategyPickerChip.classList.toggle("strategy-chip-accent", Boolean(strategy?.supports_sweep));
      strategyPickerRules.textContent = `Regola attiva: ${labels.join(", ")}.`;
    } else {
      strategyPickerLabel.textContent = `${selectedIds.length} regole attive`;
      strategyPickerDescription.textContent = "Il segnale verra' costruito combinando tutte le strategie attive che hai acceso con i toggle.";
      strategyPickerChip.textContent = `Combinazione ${ruleLogicSelect.value.toUpperCase()}`;
      strategyPickerChip.classList.add("strategy-chip-accent");
      strategyPickerRules.textContent = `Attive insieme: ${labels.join(" + ")}.`;
    }
  }

  function syncStrategyModalPanels() {
    const selectedIds = activeStrategyIds();
    strategyDetailPanels.forEach((panel) => {
      panel.classList.toggle("is-active", selectedIds.includes(panel.dataset.modalStrategy));
    });

    if (strategyModalSummary) {
      const labels = activeRuleLabels();
      strategyModalSummary.textContent = labels.length > 1
        ? `Regole attive: ${labels.join(" + ")}. La combinazione attuale e' ${ruleLogicSelect.value.toUpperCase()}.`
        : `Regola attiva: ${labels[0] || "nessuna"}.`;
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
    syncStrategyFields();
    syncStrategyPickerCard();
    syncStrategyModalPanels();
  }

  function focusStrategyInModal(strategyId) {
    if (!strategyId) {
      return;
    }

    strategyChoiceCards.forEach((card) => {
      card.classList.toggle("is-focused", card.dataset.strategyChoice === strategyId);
    });
    strategyDetailPanels.forEach((panel) => {
      panel.classList.toggle("is-focused", panel.dataset.modalStrategy === strategyId);
    });

    const focusedPanel = strategyDetailPanels.find(
      (panel) => panel.dataset.modalStrategy === strategyId && panel.classList.contains("is-active"),
    );
    if (focusedPanel) {
      focusedPanel.scrollIntoView({ block: "start", behavior: "smooth" });
      return;
    }

    const focusedChoice = strategyChoiceCards.find((card) => card.dataset.strategyChoice === strategyId);
    focusedChoice?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function openStrategyLab(strategyId = "") {
    syncStrategyWorkspace();
    syncModalValuesFromForm();
    strategyModal.hidden = false;
    requestAnimationFrame(() => {
      strategyModal.classList.add("is-open");
      focusStrategyInModal(strategyId);
    });
    document.body.classList.add("strategy-modal-open");
  }

  function closeStrategyLab() {
    strategyModal.classList.remove("is-open");
    strategyModal.hidden = true;
    document.body.classList.remove("strategy-modal-open");
    strategyChoiceCards.forEach((card) => card.classList.remove("is-focused"));
    strategyDetailPanels.forEach((panel) => panel.classList.remove("is-focused"));
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
  ruleLogicSelect.addEventListener("change", syncStrategyWorkspace);
  runModeSelect.addEventListener("change", syncStrategyWorkspace);
  intervalSelect.addEventListener("change", syncIntervalHint);
  presetSelect.addEventListener("change", (event) => applyPreset(event.target.value));

  openStrategyLabButton.addEventListener("click", openStrategyLab);
  strategyEditButtons.forEach((button) => {
    button.addEventListener("click", () => openStrategyLab(button.dataset.strategyEdit || ""));
  });
  applyStrategyLabButton.addEventListener("click", closeStrategyLab);
  modalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeStrategyLab);
  });
  strategyChoiceCards.forEach((card) => {
    card.addEventListener("click", () => toggleStrategyActivation(card.dataset.strategyChoice));
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
});
