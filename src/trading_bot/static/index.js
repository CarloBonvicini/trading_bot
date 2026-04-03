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
  const runModeSelect = document.getElementById("run-mode-select");
  const submitButton = document.getElementById("submit-button");
  const intervalSelect = document.getElementById("interval-select");
  const presetSelect = document.getElementById("preset-select");
  const strategyPickerLabel = document.getElementById("strategy-picker-label");
  const strategyPickerDescription = document.getElementById("strategy-picker-description");
  const strategyPickerChip = document.getElementById("strategy-picker-chip");
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

  function syncStrategyFields() {
    const selectedStrategy = strategySelect.value;
    const activeSection = sections.find((section) => section.dataset.strategy === selectedStrategy);
    const sweepAvailable = activeSection?.dataset.supportsSweep === "true";

    sweepOption.disabled = !sweepAvailable;
    if (!sweepAvailable && runModeSelect.value === "sweep") {
      runModeSelect.value = "single";
    }

    const selectedMode = runModeSelect.value;

    sections.forEach((section) => {
      const isActive = section.dataset.strategy === selectedStrategy;
      section.classList.toggle("is-active", isActive);

      const modeSections = Array.from(section.querySelectorAll(".mode-fields"));
      if (modeSections.length === 0) {
        setSectionInputsState(section, isActive);
        return;
      }

      modeSections.forEach((modeSection) => {
        const isModeActive = isActive && modeSection.dataset.runMode === selectedMode;
        modeSection.classList.toggle("is-active", isModeActive);
        setSectionInputsState(modeSection, isModeActive);
      });
    });

    document.querySelectorAll("[id^='strategy-mode-badge-']").forEach((badge) => {
      badge.textContent = selectedMode === "sweep" ? "Sweep multiplo" : "Test singolo";
    });

    submitButton.textContent = selectedMode === "sweep" ? "Avvia sweep" : "Avvia backtest";
  }

  function getSourceField(fieldName) {
    return document.querySelector(`[name="${fieldName}"]`);
  }

  function syncStrategyPickerCard() {
    const strategy = strategyCatalog[strategySelect.value];
    if (!strategy) {
      return;
    }

    strategyPickerLabel.textContent = strategy.label;
    strategyPickerDescription.textContent = strategy.description;
    strategyPickerChip.textContent = strategy.supports_sweep ? "Sweep disponibile" : "Solo test singolo";
    strategyPickerChip.classList.toggle("strategy-chip-accent", Boolean(strategy.supports_sweep));
  }

  function syncStrategyModalPanels() {
    const selectedStrategy = strategySelect.value;
    strategyChoiceCards.forEach((card) => {
      card.classList.toggle("is-active", card.dataset.strategyChoice === selectedStrategy);
    });
    strategyDetailPanels.forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.modalStrategy === selectedStrategy);
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
    runModeSelect.value = preset.run_mode || "single";
    intervalSelect.value = preset.interval || intervalSelect.value;
    document.querySelector('[name="initial_capital"]').value = preset.initial_capital;
    document.querySelector('[name="fee_bps"]').value = preset.fee_bps;
    document.querySelector('[name="preset_name"]').value = preset.name;

    Object.entries(preset.parameters || {}).forEach(([parameterName, parameterValue]) => {
      const field = document.querySelector(`[name="${preset.strategy}__${parameterName}"]`);
      if (field) {
        field.value = parameterValue;
      }
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
