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
  const comparisonPlaceholder = document.querySelector("[data-comparison-placeholder]");
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

  // ── Stato gruppi ──────────────────────────────────────────────────
  // strategyGroupState:   { strategyId → groupNumber (1-based) }
  // groupLogicState:      { groupNumber → "all" | "any" }  — logica interna al gruppo
  // interGroupLogics:     { groupNumber → "all" | "any" }  — op PRIMA di questo gruppo (gn >= 2)
  // topLevelLogic:        default fallback per nuovi inter-op
  const strategyGroupState = {};
  const groupLogicState = {};
  const interGroupLogics = {};
  const boundPairs = new Set(); // gn in boundPairs → gn e il gruppo precedente formano un sotto-nodo (parentesi)
  let topLevelLogic = ruleLogicSelect?.value || config.rule_logic || "all";
  let isDraggingCard = false; // true mentre si trascina una carta dalla griglia

  const groupDndSection = document.querySelector("[data-group-dnd-section]");
  const ruleLogicLabelNode = document.querySelector("[data-rule-logic-label]");

  function _initGroupsFromConfig(groups) {
    if (!Array.isArray(groups) || groups.length < 2) return;
    // Se ogni gruppo contiene esattamente 1 strategia, è equivalente a flat mode: ignoriamo.
    const allSingles = groups.every((g) => (g.strategies || []).length === 1);
    if (allSingles) return;
    groups.forEach((group, idx) => {
      const gn = idx + 1;
      groupLogicState[gn] = group.logic || "all";
      if (gn >= 2) interGroupLogics[gn] = group.op_before || topLevelLogic;
      (group.strategies || []).forEach((sid) => {
        strategyGroupState[sid] = gn;
      });
    });
  }
  _initGroupsFromConfig(config.groups || []);

  // Palette colori per i gruppi (si ripete ciclicamente oltre il sesto)
  const GROUP_COLORS = ["#10b981", "#38bdf8", "#fb923c", "#a78bfa", "#f472b6", "#facc15"];
  function groupColor(gn) {
    return GROUP_COLORS[(gn - 1) % GROUP_COLORS.length];
  }

  const initialState = captureState();
  setComparisonState(false);          // nessuna preview attiva al caricamento
  // Nasconde i marker di ingresso/uscita del report originale: il grafico parte pulito
  window.tradingBotChartTerminal?.setLayerVisible("entry", false);
  window.tradingBotChartTerminal?.setLayerVisible("exit", false);
  renderValidationCards(config.validation_cards || []);
  renderValidationChecks(config.validation_checks || []);
  renderTradePreview(config.trade_preview || []);
  renderIndicatorPanels(currentIndicatorPayload, currentIndicatorLabel, currentChartPayload);
  syncSections();
  syncRuleSummary();

  strategyToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => {
      // Se la strategia è stata appena attivata e la scansione ha trovato parametri ottimali, applicali
      // prima di avviare la preview — così i numeri nel pannello confronto corrispondono al badge.
      if (toggle.checked) {
        const sid = toggle.value;
        const best = scanBestParams[sid];
        if (best) {
          Object.entries(best).forEach(([paramName, value]) => {
            const fieldName = `${sid}__${paramName}`;
            const input = parameterInputs.find((el) => el.name === fieldName);
            if (input) input.value = value;
          });
        }
      }
      syncSections();
      schedulePreview();
    });
  });

  // Doppio clic su una card → apre l'Analisi parametri per quella strategia
  strategyCards.forEach((card) => {
    card.addEventListener("dblclick", () => {
      const strategyId = card.dataset.chartStrategyCard;
      const label = config.strategies?.[strategyId]?.label || strategyId;
      // Dopo il doppio clic la checkbox è tornata allo stato originale (due toggle).
      // Se la strategia non era attiva, la attiviamo esplicitamente.
      const toggle = strategyToggles.find((t) => t.value === strategyId);
      if (toggle && !toggle.checked) {
        toggle.checked = true;
        syncSections();
        schedulePreview();
      }
      openAutosettingModal(strategyId, label);
    });
  });

  // Il selettore ruleLogicSelect nel toolbar è ora nascosto — la logica inter-gruppo
  // si sceglie tramite il toggle AND/OR inline nella sezione DnD.
  // Teniamo il listener per retrocompatibilità con ripristini esterni.
  ruleLogicSelect?.addEventListener("change", () => {
    topLevelLogic = ruleLogicSelect.value;
    renderGroupDndSection();
    schedulePreview();
  });

  // Previene che il click sul badge-indicatore attivi/disattivi la card
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-group-badge]")) {
      e.preventDefault();
      e.stopPropagation();
    }
  });

  // ── Drag dalle carte nella griglia ───────────────────────────────
  // Le carte sono draggable; il drop avviene nella sezione DnD sotto.
  const strategyCardGrid = document.querySelector(".chart-live-toggle-grid");

  strategyCardGrid?.addEventListener("dragstart", (e) => {
    const card = e.target.closest("[data-chart-strategy-card]");
    if (!card) return;
    const sid = card.dataset.chartStrategyCard;
    isDraggingCard = true;
    _dragSid = sid;
    e.dataTransfer.setData("text/plain", sid);
    e.dataTransfer.effectAllowed = "move";
    card.classList.add("is-card-dragging");
    // Mostra la sezione DnD anche se c'è solo 1 strategia attiva
    renderGroupDndSection();
  });

  strategyCardGrid?.addEventListener("dragend", (e) => {
    const card = e.target.closest("[data-chart-strategy-card]");
    if (card) card.classList.remove("is-card-dragging");
    isDraggingCard = false;
    _dragSid = null;
    renderGroupDndSection();
  });

  // ── Drag & drop per i gruppi ─────────────────────────────────────
  let _dragSid = null;

  if (groupDndSection) {
    groupDndSection.addEventListener("dragstart", (e) => {
      const chip = e.target.closest("[data-chip-strategy]");
      if (!chip) return;
      _dragSid = chip.dataset.chipStrategy;
      e.dataTransfer.setData("text/plain", _dragSid);
      e.dataTransfer.effectAllowed = "move";
      chip.classList.add("is-dragging");
      // Mostra la zona "nuovo gruppo" anche quando si trascina un chip già in un bucket
      isDraggingCard = true;
      renderGroupDndSection();
    });

    groupDndSection.addEventListener("dragend", (e) => {
      const chip = e.target.closest("[data-chip-strategy]");
      if (chip) chip.classList.remove("is-dragging");
      _dragSid = null;
      isDraggingCard = false;
      renderGroupDndSection();
    });

    groupDndSection.addEventListener("dragover", (e) => {
      const bucket = e.target.closest("[data-group-bucket]");
      if (bucket) e.preventDefault();
    });

    groupDndSection.addEventListener("dragenter", (e) => {
      const bucket = e.target.closest("[data-group-bucket]");
      if (bucket) bucket.classList.add("drag-over");
    });

    groupDndSection.addEventListener("dragleave", (e) => {
      const bucket = e.target.closest("[data-group-bucket]");
      if (bucket && !bucket.contains(e.relatedTarget)) {
        bucket.classList.remove("drag-over");
      }
    });

    groupDndSection.addEventListener("drop", (e) => {
      const bucket = e.target.closest("[data-group-bucket]");
      if (!bucket) return;
      e.preventDefault();
      bucket.classList.remove("drag-over");
      const sid = e.dataTransfer.getData("text/plain") || _dragSid;
      if (!sid) return;

      const rawGn = bucket.dataset.groupBucket;
      let targetGn;

      if (rawGn === "new") {
        // Nuovo gruppo = massimo corrente + 1 (nessun tetto fisso)
        const active = activeStrategyIds();
        const occupied = active.map((s) => strategyGroupState[s] ?? 1);
        const maxGn = occupied.length > 0 ? Math.max(...occupied) : 1;
        targetGn = maxGn + 1;
        // Inizializza l'operatore inter-gruppo con il default corrente
        if (!(targetGn in interGroupLogics)) {
          interGroupLogics[targetGn] = topLevelLogic;
        }
      } else {
        targetGn = parseInt(rawGn, 10);
        if (isNaN(targetGn)) return;
      }

      // Attiva la strategia se era inattiva (drag da carta inattiva)
      const toggle = strategyToggles.find((t) => t.value === sid);
      if (toggle && !toggle.checked) {
        toggle.checked = true;
      }

      strategyGroupState[sid] = targetGn;
      syncSections();
      syncRuleSummary();
      schedulePreview();
    });

    groupDndSection.addEventListener("change", (e) => {
      // Selettore logica interna di un gruppo
      const sel = e.target.closest("[data-group-logic-select]");
      if (sel) {
        const gn = parseInt(sel.dataset.groupLogicSelect, 10);
        groupLogicState[gn] = sel.value;
        syncRuleSummary();
        schedulePreview();
      }
    });

    // Toggle AND/OR tra gruppi + reset gruppi (click inline)
    groupDndSection.addEventListener("click", (e) => {
      const interOpBtn = e.target.closest("[data-inter-op-gn]");
      if (interOpBtn) {
        const gn = parseInt(interOpBtn.dataset.interOpGn, 10);
        interGroupLogics[gn] = (interGroupLogics[gn] ?? topLevelLogic) === "all" ? "any" : "all";
        renderGroupDndSection();
        syncRuleSummary();
        schedulePreview();
        return;
      }
      const boundToggle = e.target.closest("[data-bound-toggle]");
      if (boundToggle) {
        const gn = parseInt(boundToggle.dataset.boundToggle, 10);
        if (boundPairs.has(gn)) boundPairs.delete(gn);
        else boundPairs.add(gn);
        renderGroupDndSection();
        syncRuleSummary();
        schedulePreview();
        return;
      }
      if (e.target.closest("[data-group-reset]")) {
        // Riporta tutte le strategie al gruppo 1
        Object.keys(strategyGroupState).forEach((k) => delete strategyGroupState[k]);
        Object.keys(groupLogicState).forEach((k) => delete groupLogicState[k]);
        Object.keys(interGroupLogics).forEach((k) => delete interGroupLogics[k]);
        boundPairs.clear();
        renderGroupDndSection();
        updateGroupBadges();
        syncRuleSummary();
        schedulePreview();
      }
    });
  }

  parameterInputs.forEach((input) => {
    input.addEventListener("input", schedulePreview);
    input.addEventListener("change", schedulePreview);
  });

  // I campi rischio aggiornano la preview al cambio
  document.querySelectorAll("[data-chart-risk-input]").forEach((el) => {
    el.addEventListener("input", schedulePreview);
    el.addEventListener("change", schedulePreview);
  });

  resetButton?.addEventListener("click", (event) => {
    event.preventDefault();
    restoreInitialState();
  });

  // ── Salva preset ──────────────────────────────────────────────────
  const saveBtn = document.querySelector("[data-chart-save-btn]");
  const savePopover = document.querySelector("[data-chart-save-popover]");
  const saveNameInput = document.querySelector("[data-chart-save-name]");
  const saveConfirmBtn = document.querySelector("[data-chart-save-confirm]");
  const saveCancelBtn = document.querySelector("[data-chart-save-cancel]");
  const saveMsgNode = document.querySelector("[data-chart-save-msg]");

  function openSavePopover() {
    if (!savePopover) return;
    if (saveMsgNode) { saveMsgNode.hidden = true; saveMsgNode.textContent = ""; }
    savePopover.hidden = false;
    saveNameInput?.focus();
  }

  function closeSavePopover() {
    if (savePopover) savePopover.hidden = true;
  }

  async function confirmSave() {
    if (!config.save_endpoint) return;
    const name = (saveNameInput?.value || "").trim();
    if (!name) {
      if (saveMsgNode) { saveMsgNode.textContent = "Inserisci un nome."; saveMsgNode.hidden = false; }
      saveNameInput?.focus();
      return;
    }

    if (saveConfirmBtn) saveConfirmBtn.disabled = true;

    const payload = buildPayload();
    const body = {
      name,
      symbol: config.report_symbol || "",
      start: config.report_start || "",
      end: config.report_end || "",
      interval: config.report_interval || "1d",
      active_strategies: payload.active_strategies || [],
      rule_logic: payload.rule_logic || "all",
    };
    // Aggiunge i parametri per strategia (chiavi con __)
    for (const [k, v] of Object.entries(payload)) {
      if (k.includes("__")) body[k] = v;
    }

    try {
      const resp = await fetch(config.save_endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Errore salvataggio");
      if (saveMsgNode) {
        saveMsgNode.textContent = `✓ Preset "${data.name}" salvato.`;
        saveMsgNode.className = "chart-save-popover-msg chart-save-popover-msg-ok";
        saveMsgNode.hidden = false;
      }
      if (saveNameInput) saveNameInput.value = "";
      setTimeout(closeSavePopover, 1800);
    } catch (err) {
      if (saveMsgNode) {
        saveMsgNode.textContent = err.message || "Errore.";
        saveMsgNode.className = "chart-save-popover-msg chart-save-popover-msg-err";
        saveMsgNode.hidden = false;
      }
    } finally {
      if (saveConfirmBtn) saveConfirmBtn.disabled = false;
    }
  }

  saveBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    savePopover?.hidden ? openSavePopover() : closeSavePopover();
  });
  saveCancelBtn?.addEventListener("click", closeSavePopover);
  saveConfirmBtn?.addEventListener("click", confirmSave);
  saveNameInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); confirmSave(); }
    if (e.key === "Escape") closeSavePopover();
  });
  document.addEventListener("click", (e) => {
    if (savePopover && !savePopover.hidden && !savePopover.contains(e.target) && e.target !== saveBtn) {
      closeSavePopover();
    }
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

  // ── Correlazione strategie ──────────────────────────────────────
  const correlationBtn = document.querySelector("[data-correlation-btn]");
  const correlationModal = document.getElementById("correlation-modal");

  correlationBtn?.addEventListener("click", openCorrelationModal);
  correlationModal?.querySelectorAll("[data-correlation-modal-close]").forEach((el) => {
    el.addEventListener("click", closeCorrelationModal);
  });

  function openCorrelationModal() {
    if (!correlationModal || !config.correlation_endpoint) return;
    const loadingNode = correlationModal.querySelector("[data-correlation-loading]");
    const contentNode = correlationModal.querySelector("[data-correlation-content]");
    if (loadingNode) { loadingNode.hidden = false; loadingNode.innerHTML = '<div class="autosetting-loading-spinner"></div><span>Calcolo segnali in corso...</span>'; }
    if (contentNode) contentNode.hidden = true;
    correlationModal.hidden = false;
    document.body.classList.add("autosetting-modal-open");
    fetchCorrelationData();
  }

  function closeCorrelationModal() {
    if (!correlationModal) return;
    correlationModal.hidden = true;
    document.body.classList.remove("autosetting-modal-open");
  }

  async function fetchCorrelationData() {
    try {
      const response = await fetch(config.correlation_endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Correlazione non disponibile.");
      renderCorrelationHeatmap(data);
    } catch (error) {
      const loadingNode = correlationModal?.querySelector("[data-correlation-loading]");
      if (loadingNode) loadingNode.innerHTML = `<span style="color:#ef4444">Errore: ${escapeHtml(error.message)}</span>`;
    }
  }

  function renderCorrelationHeatmap(data) {
    const chartNode = correlationModal?.querySelector("[data-correlation-chart]");
    const hintNode  = correlationModal?.querySelector("[data-correlation-hint]");
    const loadingNode  = correlationModal?.querySelector("[data-correlation-loading]");
    const contentNode  = correlationModal?.querySelector("[data-correlation-content]");
    if (!chartNode || typeof Plotly === "undefined") return;

    if (loadingNode) loadingNode.hidden = true;
    if (contentNode) contentNode.hidden = false;

    const labels = data.labels || [];
    const matrix = data.matrix || [];

    // Abbreviazioni leggibili per etichette di asse
    const short = labels.map((l) =>
      l.replace(" Crossover", "").replace(" Mean Reversion", "").replace(" Reversion", "")
       .replace(" Trend Filter", "").replace(" Trend", "").replace(" Breakout", "").replace(" Momentum", "")
    );

    const textMatrix = matrix.map((row) => row.map((v) => (typeof v === "number" ? v.toFixed(2) : "—")));

    const colorscale = [
      [0.00, "#7f1d1d"],
      [0.20, "#dc2626"],
      [0.40, "#374151"],
      [0.50, "#1e293b"],
      [0.60, "#374151"],
      [0.80, "#059669"],
      [1.00, "#064e3b"],
    ];

    Plotly.react(
      chartNode,
      [{
        type: "heatmap",
        z: matrix,
        x: short,
        y: short,
        colorscale,
        zmin: -1,
        zmax: 1,
        text: textMatrix,
        texttemplate: "%{text}",
        textfont: { size: 9, color: "#cbd5e1" },
        showscale: true,
        colorbar: {
          tickcolor: "#9ba7c2",
          tickfont: { color: "#9ba7c2", size: 10 },
          bgcolor: "transparent",
          bordercolor: "rgba(163,177,204,0.12)",
          thickness: 14,
        },
        hoverongaps: false,
        hovertemplate: "<b>%{y} × %{x}</b><br>Correlazione: <b>%{z:.3f}</b><extra></extra>",
      }],
      {
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        margin: { t: 8, r: 70, b: 130, l: 130 },
        xaxis: {
          tickangle: -42,
          tickfont: { size: 10, color: "#9ba7c2" },
          gridcolor: "rgba(163,177,204,0.07)",
          linecolor: "rgba(163,177,204,0.1)",
        },
        yaxis: {
          tickfont: { size: 10, color: "#9ba7c2" },
          gridcolor: "rgba(163,177,204,0.07)",
          linecolor: "rgba(163,177,204,0.1)",
          autorange: "reversed",
        },
      },
      { responsive: true, displaylogo: false, displayModeBar: false },
    );

    if (hintNode) {
      if (data.failed_strategies?.length) {
        hintNode.textContent = `${data.failed_strategies.length} strateg${data.failed_strategies.length === 1 ? "ia esclusa" : "ie escluse"} per dati mancanti (high/low/volume non presenti nel dataset).`;
        hintNode.hidden = false;
      } else {
        hintNode.hidden = true;
      }
    }
  }

  // ── Scansione (rapida / media / lunga) ───────────────────────────
  const scanAllBtn = document.querySelector("[data-scan-all-btn]");
  const scanModeToggle = document.querySelector("[data-scan-mode-toggle]");
  const scanModeMenu = document.querySelector("[data-scan-mode-menu]");
  const scanModeOptions = Array.from(document.querySelectorAll("[data-scan-mode]"));
  let currentScanMode = "rapida";
  // Parametri ottimali trovati dalla scansione, per strategia: { strategyId → best_params }
  const scanBestParams = {};

  // Apre/chiude il menu di selezione modalità
  scanModeToggle?.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !scanModeMenu.hidden;
    scanModeMenu.hidden = isOpen;
    scanModeToggle.setAttribute("aria-expanded", String(!isOpen));
  });

  // Seleziona una modalità dal menu
  scanModeOptions.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      currentScanMode = btn.dataset.scanMode;
      scanModeOptions.forEach((b) => b.classList.remove("is-selected"));
      btn.classList.add("is-selected");
      scanModeMenu.hidden = true;
      scanModeToggle.setAttribute("aria-expanded", "false");
    });
  });

  // Chiude il menu cliccando fuori
  document.addEventListener("click", () => {
    if (scanModeMenu && !scanModeMenu.hidden) {
      scanModeMenu.hidden = true;
      scanModeToggle?.setAttribute("aria-expanded", "false");
    }
  });

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

    const modeLabel = { rapida: "Rapida", media: "Media", lunga: "Lunga", xl: "XL" }[currentScanMode] || "Rapida";
    scanAllBtn.disabled = true;
    scanAllBtn.textContent = `Scansione ${modeLabel}…`;

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
        statusNode.innerHTML = `<span class="preview-spinner"></span>`;
      }

      try {
        const response = await fetch(config.autosetting_endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy_id: strategyId, fee_bps: feeValue, scan_mode: currentScanMode }),
        });
        const data = await response.json();

        if (!response.ok || typeof data.sharpe_in_sample !== "number") {
          throw new Error(data.error || "errore");
        }

        const sharpe = data.sharpe_in_sample;
        const ret = typeof data.total_return_pct === "number" ? data.total_return_pct : null;
        // Salva i parametri ottimali trovati: verranno applicati quando l'utente attiva la strategia
        if (data.best_params) scanBestParams[strategyId] = data.best_params;
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
    scanAllBtn.textContent = "Scansione";
    if (statusNode) statusNode.innerHTML = "";
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
    updateGroupBadges();
    renderGroupDndSection();
    syncRuleSummary();
  }

  function syncRuleSummary(previewLabel = config.baseline_label || "Setup iniziale del report") {
    if (!ruleSummaryNode) return;
    const topLogicLabel = topLevelLogic === "any" ? "OR" : "AND";

    // Descrizione testuale dell'espressione corrente (con parentesi se presenti)
    function exprDescription() {
      const active = activeStrategyIds();
      const byGroup = {};
      for (const sid of active) {
        const gn = strategyGroupState[sid] ?? 1;
        (byGroup[gn] = byGroup[gn] || []).push(sid);
      }
      const gnList = Object.keys(byGroup).map(Number).sort((a, b) => a - b);
      if (gnList.length <= 1) return null;

      // Cluster (come nel rendering)
      const clusters = [];
      let cur = [gnList[0]];
      for (let i = 1; i < gnList.length; i++) {
        if (boundPairs.has(gnList[i])) cur.push(gnList[i]);
        else { clusters.push(cur); cur = [gnList[i]]; }
      }
      clusters.push(cur);

      function gnLabel(gn) {
        const members = byGroup[gn] || [];
        const logic = groupLogicState[gn] === "any" ? "OR" : "AND";
        const labels = members.map((sid) => config.strategies?.[sid]?.label || sid);
        return labels.length > 1 ? `(${labels.join(` ${logic} `)})` : labels[0] || "?";
      }

      function clusterLabel(cluster) {
        if (cluster.length === 1) return gnLabel(cluster[0]);
        const parts = [gnLabel(cluster[0])];
        for (let i = 1; i < cluster.length; i++) {
          parts.push((interGroupLogics[cluster[i]] ?? topLevelLogic) === "any" ? "OR" : "AND");
          parts.push(gnLabel(cluster[i]));
        }
        return `(${parts.join(" ")})`;
      }

      const clusterParts = [clusterLabel(clusters[0])];
      for (let i = 1; i < clusters.length; i++) {
        clusterParts.push((interGroupLogics[clusters[i][0]] ?? topLevelLogic) === "any" ? "OR" : "AND");
        clusterParts.push(clusterLabel(clusters[i]));
      }
      return clusterParts.join(" ");
    }

    const desc = exprDescription();
    if (desc) {
      const origin = config.baseline_label || "Setup iniziale del report";
      ruleSummaryNode.textContent = origin !== desc ? `Config: ${origin} · ${desc}` : `Config: ${desc}`;
      return;
    }

    const labels = activeStrategyIds()
      .map((strategyId) => config.strategies?.[strategyId]?.label)
      .filter(Boolean);
    if (labels.length > 1) {
      ruleSummaryNode.textContent = `Config: ${previewLabel} · ${labels.join(" + ")} (${topLogicLabel})`;
      return;
    }
    ruleSummaryNode.textContent = `Config: ${previewLabel} · ${labels[0] || "nessuna"}`;
  }

  function schedulePreview() {
    if (statusNode) {
      statusNode.innerHTML = '<span class="preview-spinner"></span>';
    }
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(runPreview, 260);
  }

  async function runPreview() {
    if (activeStrategyIds().length === 0) {
      if (statusNode) statusNode.innerHTML = "";
      // Nessuna strategia attiva: nascondi il confronto e riporta il grafico allo stato pulito
      setComparisonState(false);
      window.tradingBotChartTerminal?.clearPreview();
      window.tradingBotChartTerminal?.setLayerVisible("entry", false);
      window.tradingBotChartTerminal?.setLayerVisible("exit", false);
      return;
    }

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
        statusNode.innerHTML = `<span class="preview-error-text">Errore preview${httpStatus}: ${msg}</span>`;
      }
    }
  }

  function buildPayload() {
    const payload = {
      active_strategies: activeStrategyIds(),
      rule_logic: topLevelLogic,
    };
    // Se ci sono parentesi usa l'albero di espressione, altrimenti la lista gruppi piatta
    if (boundPairs.size > 0) {
      const expr = buildExpressionPayload();
      if (expr) payload.expression = expr;
    } else {
      const groups = buildGroupsPayload();
      if (groups) payload.groups = groups;
    }
    parameterInputs.forEach((input) => {
      payload[input.name] = input.value;
    });
    // Parametri di gestione del rischio (SL/TP, sizing)
    const riskInputs = Array.from(document.querySelectorAll("[data-chart-risk-input]"));
    riskInputs.forEach((input) => {
      const val = input.value;
      if (input.name === "sizing_method") {
        payload.sizing_method = val;
      } else if (input.name === "sizing_param") {
        payload.sizing_param = val ? parseFloat(val) : 100.0;
      } else if (input.name === "sl_pct") {
        payload.sl_pct = val ? parseFloat(val) : null;
      } else if (input.name === "tp_pct") {
        payload.tp_pct = val ? parseFloat(val) : null;
      }
    });
    return payload;
  }

  // Costruisce un albero di espressione ricorsivo (per gestire la precedenza via parentesi).
  // Ogni nodo è { strategies, logic } (foglia) oppure { op, children } (nodo composito).
  function buildExpressionPayload() {
    const active = activeStrategyIds();
    if (active.length === 0) return null;
    const byGroup = {};
    for (const sid of active) {
      const gn = strategyGroupState[sid] ?? 1;
      (byGroup[gn] = byGroup[gn] || []).push(sid);
    }
    const gnList = Object.keys(byGroup).map(Number).sort((a, b) => a - b);
    if (gnList.length <= 1) return null;

    // Stessa logica di cluster usata nel rendering
    const clusters = [];
    let cur = [gnList[0]];
    for (let i = 1; i < gnList.length; i++) {
      if (boundPairs.has(gnList[i])) cur.push(gnList[i]);
      else { clusters.push(cur); cur = [gnList[i]]; }
    }
    clusters.push(cur);

    const gnToLeaf = (gn) => ({ strategies: byGroup[gn], logic: groupLogicState[gn] ?? "all" });

    function clusterToNode(cluster) {
      if (cluster.length === 1) return gnToLeaf(cluster[0]);
      let node = gnToLeaf(cluster[0]);
      for (let i = 1; i < cluster.length; i++) {
        node = { op: interGroupLogics[cluster[i]] ?? topLevelLogic, children: [node, gnToLeaf(cluster[i])] };
      }
      return node;
    }

    if (clusters.length === 1) return clusterToNode(clusters[0]);
    let result = clusterToNode(clusters[0]);
    for (let i = 1; i < clusters.length; i++) {
      result = { op: interGroupLogics[clusters[i][0]] ?? topLevelLogic, children: [result, clusterToNode(clusters[i])] };
    }
    return result;
  }

  function buildGroupsPayload() {
    const active = activeStrategyIds();
    if (active.length === 0) return null;
    const byGroup = {};
    for (const sid of active) {
      const gn = strategyGroupState[sid] ?? 1;
      if (!byGroup[gn]) byGroup[gn] = [];
      byGroup[gn].push(sid);
    }
    const groupNums = Object.keys(byGroup).map(Number).sort((a, b) => a - b);
    if (groupNums.length <= 1) return null;
    return groupNums.map((gn, i) => {
      const entry = {
        strategies: byGroup[gn],
        logic: groupLogicState[gn] ?? "all",
      };
      // op_before: operatore tra il gruppo precedente e questo (solo da gn >= 2)
      if (i > 0) entry.op_before = interGroupLogics[gn] ?? topLevelLogic;
      return entry;
    });
  }

  function updateGroupBadges() {
    const active = new Set(activeStrategyIds());
    document.querySelectorAll("[data-group-badge]").forEach((badge) => {
      const sid = badge.dataset.groupBadge;
      const gn = strategyGroupState[sid] ?? 1;
      const color = groupColor(gn);
      badge.textContent = String(gn);
      badge.dataset.group = String(gn);
      badge.style.visibility = active.has(sid) ? "" : "hidden";
      // Colore dinamico da palette: G1 resta neutro, G2+ si colorano
      if (gn > 1) {
        badge.style.borderColor = color + "99";
        badge.style.background = color + "22";
        badge.style.color = color;
        badge.style.opacity = "1";
      } else {
        badge.style.borderColor = "";
        badge.style.background = "";
        badge.style.color = "";
        badge.style.opacity = "";
      }
    });
  }

  function renderGroupDndSection() {
    if (!groupDndSection) return;

    const active = activeStrategyIds();
    const byGroup = {};
    for (const sid of active) {
      const gn = strategyGroupState[sid] ?? 1;
      (byGroup[gn] = byGroup[gn] || []).push(sid);
    }

    const occupiedNums = Object.keys(byGroup).map(Number).sort((a, b) => a - b);
    const hasMultipleGroups = occupiedNums.length > 1;

    if (active.length < 2 && !isDraggingCard) {
      groupDndSection.innerHTML = "";
      if (ruleLogicLabelNode) ruleLogicLabelNode.textContent = "Combina le regole";
      return;
    }

    const maxGn = occupiedNums.length > 0 ? Math.max(...occupiedNums) : 1;
    const canAddGroup = occupiedNums.length < active.length;

    const headerHtml = hasMultipleGroups
      ? `<button class="group-reset-btn" data-group-reset title="Rimuovi tutti i gruppi">✕ Azzera gruppi</button>`
      : "";

    // ── Helper: singolo bucket ──────────────────────────────────────
    function renderBucket(gn) {
      const members = byGroup[gn] || [];
      const color = groupColor(gn);
      const currentLogic = groupLogicState[gn] ?? "all";
      const chips = members.map((sid) => {
        const label = escapeHtml(config.strategies?.[sid]?.label || sid);
        return `<div class="group-dnd-chip" draggable="true" data-chip-strategy="${escapeHtml(sid)}"
                    style="border-color:${color}55;background:${color}12;">${label}</div>`;
      }).join("");
      const logicSel = members.length > 1
        ? `<select class="group-dnd-logic-sel" data-group-logic-select="${gn}">
             <option value="all"${currentLogic === "all" ? " selected" : ""}>AND</option>
             <option value="any"${currentLogic === "any" ? " selected" : ""}>OR</option>
           </select>`
        : `<span class="group-dnd-single-hint">+ trascina</span>`;
      return `<div class="group-dnd-bucket" data-group-bucket="${gn}" style="--gcolor:${color}">
        <div class="group-dnd-bucket-head">
          <span class="group-dnd-bucket-label" style="color:${color}">G${gn}</span>
          ${logicSel}
        </div>
        <div class="group-dnd-chips">${chips}</div>
      </div>`;
    }

    // ── Helper: operatore inter-gruppo con bottone () ───────────────
    // isBound: il bottone serve a "sbindare" (siamo dentro un cluster)
    function renderInterOp(rightGn, isBound) {
      const op = interGroupLogics[rightGn] ?? topLevelLogic;
      const opLabel = op === "any" ? "OR" : "AND";
      const boundClass = isBound ? " is-bound" : "";
      const boundTitle = isBound ? "Rimuovi parentesi" : "Aggiungi parentesi";
      return `<div class="group-inter-op-wrapper">
        <button class="group-inter-op-inline" data-inter-op-gn="${rightGn}">${opLabel}</button>
        <button class="group-bound-toggle${boundClass}" data-bound-toggle="${rightGn}" title="${boundTitle}">()</button>
      </div>`;
    }

    // ── Costruisce i cluster da boundPairs ──────────────────────────
    // Un cluster è una sequenza consecutiva di gn dove ogni gn (tranne il primo) è in boundPairs.
    const clusters = [];
    let currentCluster = [occupiedNums[0]];
    for (let i = 1; i < occupiedNums.length; i++) {
      const gn = occupiedNums[i];
      if (boundPairs.has(gn)) {
        currentCluster.push(gn);
      } else {
        clusters.push(currentCluster);
        currentCluster = [gn];
      }
    }
    clusters.push(currentCluster);

    // ── Render di un cluster ────────────────────────────────────────
    function renderCluster(cluster) {
      if (cluster.length === 1) return renderBucket(cluster[0]);
      // Più gruppi parentesizzati insieme
      let inner = renderBucket(cluster[0]);
      for (let i = 1; i < cluster.length; i++) {
        inner += renderInterOp(cluster[i], true);   // isBound=true: mostra "sbinda"
        inner += renderBucket(cluster[i]);
      }
      return `<div class="group-bound-cluster">${inner}</div>`;
    }

    // ── Track completo: cluster separati da inter-op con () ─────────
    let trackHtml = renderCluster(clusters[0]);
    for (let i = 1; i < clusters.length; i++) {
      trackHtml += renderInterOp(clusters[i][0], false);   // isBound=false: mostra "binda"
      trackHtml += renderCluster(clusters[i]);
    }

    // Zona "Nuovo gruppo" (solo durante drag)
    const newGn = maxGn + 1;
    const newColor = groupColor(newGn);
    const newGroupHtml = canAddGroup && isDraggingCard
      ? `<div class="group-dnd-bucket is-new-group" data-group-bucket="new" style="--gcolor:${newColor}">
           <div class="group-dnd-bucket-head">
             <span class="group-dnd-bucket-label" style="color:${newColor}">+ G${newGn}</span>
           </div>
           <div class="group-dnd-chips"><div class="group-dnd-empty">nuovo gruppo</div></div>
         </div>`
      : "";

    groupDndSection.innerHTML = `
      <div class="group-dnd-header">${headerHtml}</div>
      <div class="group-dnd-track">${trackHtml}${newGroupHtml}</div>`;
  }

  function applyPreviewResponse(data) {
    currentIndicatorPayload = data.indicator_payload || data.chart_payload?.indicators || [];
    currentIndicatorLabel = data.preview_label || "Configurazione attuale";
    currentChartPayload = data.chart_payload || initialChartPayload;
    setComparisonState(true);
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
      badgeNode.innerHTML = "";
    }
    if (statusNode) {
      statusNode.innerHTML = "";
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
    topLevelLogic = initialState.ruleLogic || "all";
    if (ruleLogicSelect) ruleLogicSelect.value = topLevelLogic;
    parameterInputs.forEach((input) => {
      if (Object.prototype.hasOwnProperty.call(initialState.parameters, input.name)) {
        input.value = initialState.parameters[input.name];
      }
    });
    // Ripristina campi di gestione del rischio
    Array.from(document.querySelectorAll("[data-chart-risk-input]")).forEach((el) => {
      if (Object.prototype.hasOwnProperty.call(initialState.riskValues || {}, el.name)) {
        el.value = initialState.riskValues[el.name];
        el.dispatchEvent(new Event("change"));
      }
    });
    // Ripristina stato gruppi
    Object.keys(strategyGroupState).forEach((k) => delete strategyGroupState[k]);
    Object.keys(groupLogicState).forEach((k) => delete groupLogicState[k]);
    Object.assign(strategyGroupState, initialState.strategyGroups || {});
    Object.assign(groupLogicState, initialState.groupLogics || {});
    Object.assign(interGroupLogics, initialState.interGroupLogics || {});
    boundPairs.clear();
    (initialState.boundPairsSnapshot || []).forEach((gn) => boundPairs.add(gn));
    currentIndicatorPayload = Array.isArray(config.indicator_payload) ? config.indicator_payload : [];
    currentIndicatorLabel = config.baseline_label || "Setup iniziale del report";
    currentChartPayload = initialChartPayload;
    syncSections();
    setComparisonState(false);
    renderValidationCards(config.validation_cards || []);
    renderValidationChecks(config.validation_checks || []);
    renderTradePreview(config.trade_preview || []);
    renderIndicatorPanels(
      filterIndicatorsByActiveStrategies(currentIndicatorPayload, activeStrategyIds()),
      currentIndicatorLabel,
      currentChartPayload,
    );
    if (badgeNode) {
      badgeNode.innerHTML = "";
    }
    if (statusNode) {
      statusNode.innerHTML = "";
    }
    syncRuleSummary(config.baseline_label || "Setup iniziale del report");
    window.tradingBotChartTerminal?.clearPreview();
    // Mantiene i marker del report originale nascosti anche dopo il reset
    window.tradingBotChartTerminal?.setLayerVisible("entry", false);
    window.tradingBotChartTerminal?.setLayerVisible("exit", false);
  }

  function captureState() {
    const parameters = {};
    parameterInputs.forEach((input) => {
      parameters[input.name] = input.value;
    });
    const riskValues = {};
    Array.from(document.querySelectorAll("[data-chart-risk-input]")).forEach((el) => {
      riskValues[el.name] = el.value;
    });
    return {
      activeStrategyIds: activeStrategyIds(),
      ruleLogic: topLevelLogic,
      parameters,
      riskValues,
      strategyGroups: { ...strategyGroupState },
      groupLogics: { ...groupLogicState },
      interGroupLogics: { ...interGroupLogics },
      boundPairsSnapshot: [...boundPairs],
    };
  }

  function setComparisonState(hasPreview) {
    if (comparisonPlaceholder) comparisonPlaceholder.hidden = hasPreview;
    if (comparisonGrid) comparisonGrid.hidden = !hasPreview;
  }

  function renderComparisonCards(cards) {
    if (!comparisonGrid) {
      return;
    }

    comparisonGrid.innerHTML = cards.map((card) => {
      const tone = card.tone ? ` report-tone-${escapeHtml(card.tone)}` : "";
      const hint = card.hint ? `<span>${escapeHtml(card.hint)}</span>` : "";
      return `
        <article class="terminal-metric-card${tone}">
          <p>${escapeHtml(card.label ?? "")}</p>
          ${hint}
          <strong>${escapeHtml(card.value ?? "")}</strong>
        </article>
      `;
    }).join("");
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
    if (statusNode) statusNode.innerHTML = '<span class="preview-spinner"></span>';

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
      renderAutosettingEquity(data);
      updateAutosettingSelectedLabel(data.best_params, data);

      if (autosettingApplyBtn) autosettingApplyBtn.disabled = false;

      // Status bar aggiornato
      const isStr = typeof data.sharpe_in_sample === "number" ? data.sharpe_in_sample.toFixed(2) : "—";
      const oosStr = typeof data.sharpe_out_of_sample === "number" ? data.sharpe_out_of_sample.toFixed(2) : "—";
      if (statusNode) {
        statusNode.innerHTML = "";
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Analisi non disponibile.";
      if (autosettingLoadingNode) {
        autosettingLoadingNode.innerHTML = `<span style="color:#ef4444">Errore: ${escapeHtml(msg)}</span>`;
      }
      if (statusNode) statusNode.innerHTML = `<span class="preview-error-text">Errore analisi: ${escapeHtml(msg)}</span>`;
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

  function renderAutosettingEquity(data) {
    const section   = autosettingModal?.querySelector("[data-autosetting-equity-section]");
    const chartNode = autosettingModal?.querySelector("[data-autosetting-equity-chart]");
    if (!section || !chartNode || typeof Plotly === "undefined") return;

    const is  = data.equity_is;
    const oos = data.equity_oos;

    if (!is?.dates?.length && !oos?.dates?.length) {
      section.hidden = true;
      return;
    }

    section.hidden = false;

    const traces = [];

    if (is?.dates?.length) {
      traces.push({
        type: "scatter", mode: "lines",
        x: is.dates, y: is.values,
        name: `In-sample (${data.train_bars ?? "?"} barre)`,
        line: { color: "#10b981", width: 1.6 },
        hovertemplate: "%{x}<br><b>%{y:.1f}%</b><extra>In-sample</extra>",
      });
    }

    if (oos?.dates?.length) {
      traces.push({
        type: "scatter", mode: "lines",
        x: oos.dates, y: oos.values,
        name: `Out-of-sample (${data.test_bars ?? "?"} barre)`,
        line: { color: "#38bdf8", width: 1.6 },
        hovertemplate: "%{x}<br><b>%{y:.1f}%</b><extra>Out-of-sample</extra>",
      });
    }

    const splitDate = oos?.dates?.[0] ?? null;
    const shapes = [];
    const annotations = [];

    if (splitDate && is?.dates?.length && oos?.dates?.length) {
      // Shading IS
      shapes.push({
        type: "rect", xref: "x", yref: "paper",
        x0: is.dates[0], x1: splitDate, y0: 0, y1: 1,
        fillcolor: "rgba(16,185,129,0.05)", line: { width: 0 },
      });
      // Shading OOS
      shapes.push({
        type: "rect", xref: "x", yref: "paper",
        x0: splitDate, x1: oos.dates[oos.dates.length - 1], y0: 0, y1: 1,
        fillcolor: "rgba(56,189,248,0.05)", line: { width: 0 },
      });
      // Linea di split
      shapes.push({
        type: "line", xref: "x", yref: "paper",
        x0: splitDate, x1: splitDate, y0: 0, y1: 1,
        line: { color: "rgba(163,177,204,0.4)", width: 1, dash: "dash" },
      });
      annotations.push({
        x: splitDate, y: 1, xref: "x", yref: "paper",
        text: "split", showarrow: false, xanchor: "left", yanchor: "top",
        font: { color: "#9ba7c2", size: 9.5 },
      });
    }

    Plotly.react(
      chartNode,
      traces,
      {
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        margin: { t: 8, r: 16, b: 44, l: 52 },
        legend: { font: { color: "#9ba7c2", size: 10 }, bgcolor: "transparent", orientation: "h", x: 0, y: -0.18 },
        xaxis: { tickfont: { size: 9.5, color: "#9ba7c2" }, gridcolor: "rgba(163,177,204,0.07)", linecolor: "rgba(163,177,204,0.1)", showgrid: true },
        yaxis: { tickfont: { size: 9.5, color: "#9ba7c2" }, gridcolor: "rgba(163,177,204,0.07)", linecolor: "rgba(163,177,204,0.1)", ticksuffix: "%" },
        hovermode: "x unified",
        hoverlabel: { bgcolor: "#0f172a", font: { color: "#e2e8f0", size: 11 }, bordercolor: "rgba(163,177,204,0.2)" },
        shapes,
        annotations,
      },
      { responsive: true, displaylogo: false, displayModeBar: false },
    );
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
      statusNode.innerHTML = '<span class="preview-spinner"></span>';
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
