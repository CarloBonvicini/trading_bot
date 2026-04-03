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

  const strategySelect = document.getElementById("strategy-select");
  const secondaryStrategySelect = document.getElementById("secondary-strategy-select");
  const tertiaryStrategySelect = document.getElementById("tertiary-strategy-select");
  const ruleLogicSelect = document.getElementById("rule-logic-select");
  const runModeSelect = document.getElementById("run-mode-select");
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
  const strategyChoiceCards = Array.from(document.querySelectorAll("[data-strategy-choice]"));
  const strategyDetailPanels = Array.from(document.querySelectorAll("[data-modal-strategy]"));
  const modalInputs = Array.from(document.querySelectorAll("[data-modal-input]"));
  const modalCloseButtons = Array.from(document.querySelectorAll("[data-close-strategy-modal]"));
  const sections = Array.from(document.querySelectorAll(".strategy-fields[data-strategy]"));
  const sweepOption = runModeSelect.querySelector('option[value="sweep"]');
  const intervalHint = document.getElementById("interval-hint");

  function setSectionInputsState(section, isEnabled) {
    section.querySelectorAll("input, select, textarea").forEach((field) => {
      field.disabled = !isEnabled;
    });
  }

  function selectedStrategyIds() {
    const ids = [strategySelect.value, secondaryStrategySelect.value, tertiaryStrategySelect.value].filter(Boolean);
    return ids.filter((strategyId, index) => ids.indexOf(strategyId) === index);
  }

  function normalizeStrategySelections() {
    if (secondaryStrategySelect.value && secondaryStrategySelect.value === strategySelect.value) {
      secondaryStrategySelect.value = "";
    }
    if (
      tertiaryStrategySelect.value
      && (
        tertiaryStrategySelect.value === strategySelect.value
        || tertiaryStrategySelect.value === secondaryStrategySelect.value
      )
    ) {
      tertiaryStrategySelect.value = "";
    }
  }

  function activeRuleLabels() {
    return selectedStrategyIds()
      .map((strategyId) => strategyCatalog[strategyId]?.label)
      .filter(Boolean);
  }

  function syncStrategyFields() {
    const selectedStrategy = strategySelect.value;
    const activeSections = selectedStrategyIds();
    const activeSection = sections.find((section) => section.dataset.strategy === selectedStrategy);
    const hasCompositeRules = activeSections.length > 1;
    const sweepAvailable = activeSection?.dataset.supportsSweep === "true" && !hasCompositeRules;

    sweepOption.disabled = !sweepAvailable;
    if (!sweepAvailable && runModeSelect.value === "sweep") {
      runModeSelect.value = "single";
    }

    const selectedMode = runModeSelect.value;

    sections.forEach((section) => {
      const isActive = activeSections.includes(section.dataset.strategy);
      const isPrimary = section.dataset.strategy === selectedStrategy;
      section.classList.toggle("is-active", isActive);

      const parameterInputs = Array.from(section.querySelectorAll("[data-parameter-input]"));
      parameterInputs.forEach((field) => {
        field.disabled = !isActive;
      });

      const sweepBlocks = Array.from(section.querySelectorAll("[data-sweep-block]"));
      sweepBlocks.forEach((block) => {
        const isSweepActive = isPrimary && selectedMode === "sweep" && sweepAvailable;
        block.classList.toggle("is-active", isSweepActive);
        setSectionInputsState(block, isSweepActive);
      });

      const slotBadge = section.querySelector("[data-strategy-slot-badge]");
      if (slotBadge) {
        if (section.dataset.strategy === strategySelect.value) {
          slotBadge.textContent = "Regola primaria";
        } else if (section.dataset.strategy === secondaryStrategySelect.value) {
          slotBadge.textContent = "Regola aggiuntiva 2";
        } else if (section.dataset.strategy === tertiaryStrategySelect.value) {
          slotBadge.textContent = "Regola aggiuntiva 3";
        } else {
          slotBadge.textContent = "Regola attiva";
        }
      }
    });

    document.querySelectorAll("[id^='strategy-mode-badge-']").forEach((badge) => {
      badge.textContent = selectedMode === "sweep" && sweepAvailable ? "Sweep multiplo" : "Test singolo";
    });

    submitButton.textContent = selectedMode === "sweep" && sweepAvailable ? "Avvia sweep" : "Avvia backtest";
  }

  function getSourceField(fieldName) {
    return document.querySelector(`[name="${fieldName}"]`);
  }

  function syncStrategyPickerCard() {
    const strategy = strategyCatalog[strategySelect.value];
    if (!strategy) {
      return;
    }
    const labels = activeRuleLabels();
    const hasCompositeRules = labels.length > 1;

    strategyPickerLabel.textContent = strategy.label;
    strategyPickerDescription.textContent = strategy.description;
    strategyPickerChip.textContent = hasCompositeRules
      ? `Regole combinate ${ruleLogicSelect.value.toUpperCase()}`
      : strategy.supports_sweep
        ? "Sweep disponibile"
        : "Solo test singolo";
    strategyPickerChip.classList.toggle("strategy-chip-accent", Boolean(strategy.supports_sweep || hasCompositeRules));
    strategyPickerRules.textContent = hasCompositeRules
      ? `Attive insieme: ${labels.join(" + ")}.`
      : "Usi una sola regola. Aggiungi conferme qui sotto se vuoi filtrare meglio gli ingressi.";
  }

  function syncStrategyModalPanels() {
    const selectedStrategies = selectedStrategyIds();
    strategyChoiceCards.forEach((card) => {
      card.classList.toggle("is-active", selectedStrategies.includes(card.dataset.strategyChoice));
    });
    strategyDetailPanels.forEach((panel) => {
      panel.classList.toggle("is-active", selectedStrategies.includes(panel.dataset.modalStrategy));
    });
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
    normalizeStrategySelections();
    syncStrategyFields();
    syncStrategyPickerCard();
    syncStrategyModalPanels();
  }

  function openStrategyLab() {
    syncStrategyWorkspace();
    syncModalValuesFromForm();
    strategyModal.hidden = false;
    requestAnimationFrame(() => strategyModal.classList.add("is-open"));
    document.body.classList.add("strategy-modal-open");
  }

  function closeStrategyLab() {
    strategyModal.classList.remove("is-open");
    strategyModal.hidden = true;
    document.body.classList.remove("strategy-modal-open");
  }

  function selectStrategy(strategyId) {
    if (!strategyCatalog[strategyId]) {
      return;
    }

    strategySelect.value = strategyId;
    syncStrategyWorkspace();
    syncModalValuesFromForm();
  }

  function applyPreset(presetId) {
    const preset = presetsById[presetId];
    if (!preset) {
      return;
    }

    strategySelect.value = preset.strategy;
    secondaryStrategySelect.value = preset.secondary_strategy || "";
    tertiaryStrategySelect.value = preset.tertiary_strategy || "";
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

  strategySelect.addEventListener("change", syncStrategyWorkspace);
  secondaryStrategySelect.addEventListener("change", syncStrategyWorkspace);
  tertiaryStrategySelect.addEventListener("change", syncStrategyWorkspace);
  ruleLogicSelect.addEventListener("change", syncStrategyPickerCard);
  runModeSelect.addEventListener("change", syncStrategyWorkspace);
  intervalSelect.addEventListener("change", syncIntervalHint);
  presetSelect.addEventListener("change", (event) => applyPreset(event.target.value));

  openStrategyLabButton.addEventListener("click", openStrategyLab);
  applyStrategyLabButton.addEventListener("click", closeStrategyLab);
  modalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeStrategyLab);
  });
  strategyChoiceCards.forEach((card) => {
    card.addEventListener("click", () => selectStrategy(card.dataset.strategyChoice));
  });
  modalInputs.forEach((field) => {
    const updateSource = () => {
      const sourceField = getSourceField(field.dataset.modalInput);
      if (!sourceField) {
        return;
      }
      sourceField.value = field.value;
      if (["strategy", "secondary_strategy", "tertiary_strategy", "rule_logic", "run_mode"].includes(field.dataset.modalInput)) {
        syncStrategyWorkspace();
        syncModalValuesFromForm();
      }
    };
    field.addEventListener("input", updateSource);
    field.addEventListener("change", updateSource);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !strategyModal.hidden) {
      closeStrategyLab();
    }
  });

  syncStrategyWorkspace();
  syncModalValuesFromForm();
  syncIntervalHint();
});
