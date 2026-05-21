(() => {
  // ─── Setup e guard ────────────────────────────────────────────────────────────
  const dataNode        = document.getElementById("chart-window-data");
  const tradeTableDataNode = document.getElementById("chart-trade-table-data");
  const root            = document.getElementById("interactive-chart-root");

  if (!dataNode || !root || typeof LightweightCharts === "undefined") {
    const diagnostics = {
      dataNode:     Boolean(dataNode),
      root:         Boolean(root),
      lwcLoaded:    typeof LightweightCharts !== "undefined",
      lwcVersion:   typeof LightweightCharts !== "undefined" ? (LightweightCharts.version || "?") : null,
    };
    console.error("Inizializzazione grafico fallita", diagnostics);
    if (root) {
      root.innerHTML = `
        <div class="chart-error">
          <strong>Impossibile caricare il grafico</strong>
          <p>Controlla la console per gli errori JS.</p>
          <pre>${Object.entries(diagnostics).map(([k, v]) => `${k}: ${v}`).join("\n")}</pre>
        </div>
      `;
    }
    return;
  }

  const { createChart, CrosshairMode, LineStyle, PriceScaleMode } = LightweightCharts;

  // ─── Definizioni intervallo ───────────────────────────────────────────────────
  const intervalDefinitions = {
    "1m":  { key: "1m",  label: "1m",  unit: "minute", minutes: 1 },
    "2m":  { key: "2m",  label: "2m",  unit: "minute", minutes: 2 },
    "5m":  { key: "5m",  label: "5m",  unit: "minute", minutes: 5 },
    "15m": { key: "15m", label: "15m", unit: "minute", minutes: 15 },
    "30m": { key: "30m", label: "30m", unit: "minute", minutes: 30 },
    "1h":  { key: "1h",  label: "1h",  unit: "minute", minutes: 60 },
    "4h":  { key: "4h",  label: "4h",  unit: "minute", minutes: 240 },
    "90m": { key: "90m", label: "90m", unit: "minute", minutes: 90 },
    "1d":  { key: "1d",  label: "1g",  unit: "day",    minutes: 24 * 60 },
    "1wk": { key: "1wk", label: "1w",  unit: "week",   minutes: 7 * 24 * 60 },
    "1mo": { key: "1mo", label: "1mo", unit: "month",  minutes: 30 * 24 * 60 },
  };
  const candleControlOrder = ["1m", "2m", "5m", "30m", "1h", "4h", "1d", "1wk"];

  // ─── Payload e dati trade ─────────────────────────────────────────────────────
  const rawPayload   = normalizePayload(JSON.parse(dataNode.textContent || "{}"));
  const rawTradeRows = JSON.parse(tradeTableDataNode?.textContent || "[]");
  const tradeRows    = Array.isArray(rawTradeRows) ? rawTradeRows : [];

  const tradeIndexByEntryRaw = new Map();
  const tradeIndexByExitRaw  = new Map();
  tradeRows.forEach((trade, index) => {
    const entryKey = normalizeSignalTimestamp(trade?.entry_raw);
    const exitKey  = normalizeSignalTimestamp(trade?.exit_raw);
    if (entryKey) tradeIndexByEntryRaw.set(entryKey, index);
    if (exitKey)  tradeIndexByExitRaw.set(exitKey, index);
  });

  if (!rawPayload.dates.length) {
    console.warn("Payload grafico senza date", rawPayload);
    return;
  }

  // ─── DOM refs ─────────────────────────────────────────────────────────────────
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const dom = {
    start: $("[data-series-start]"),
    startLabel: $("[data-series-start-label]"),
    startDate: $("[data-series-start-date]"),
    seg: $("[data-segment-length]"),
    win: $("[data-visible-window]"),
    step: $("[data-playback-step]"),
    speed: $("[data-playback-speed]"),
    speedBadge: $("[data-playback-speed-badge]"),
    progress: $("[data-playback-progress]"),
    progressLabel: $("[data-playback-progress-label]"),
    progressDate: $("[data-playback-progress-date]"),
    toggleLabel: $("[data-playback-toggle-label]"),
    close: $("[data-market-close]"),
    closePanel: $("[data-market-close-panel]"),
    change: $("[data-market-change]"),
    changePct: $("[data-market-change-pct]"),
    timestamp: $("[data-market-timestamp]"),
    volume: $("[data-market-volume]"),
    open: $("[data-market-open]"),
    high: $("[data-market-high]"),
    low: $("[data-market-low]"),
    indicatorModal: $("[data-chart-indicator-modal]"),
    indicatorSearch: $("[data-chart-indicator-search]"),
    indicatorEmpty: $("[data-chart-indicator-empty]"),
    indicatorCount: $("[data-chart-indicator-count]"),
    candleControls: $("[data-candle-controls]"),
    signalPopupHost: $("[data-signal-popup-host]"),
    signalPopup: $("[data-signal-popup]"),
    signalPopupTitle: $("[data-signal-popup-title]"),
    signalPopupEntry: $("[data-signal-popup-entry]"),
    signalPopupExit: $("[data-signal-popup-exit]"),
    signalPopupTabs: $$("[data-signal-popup-tab]"),
    signalPopupStatus: $("[data-signal-popup-status]"),
    signalPopupCopy: $("[data-signal-popup-copy]"),
    tradeTable: $("[data-chart-trade-table]"),
    tradeControls: $("[data-chart-trade-controls]"),
    tradeSummary: $("[data-chart-trade-summary]"),
    tradePrev: $("[data-chart-trade-prev]"),
    tradeNext: $("[data-chart-trade-next]"),
    tradePageLabel: $("[data-chart-trade-page-label]"),
    tradeDetailModal: $("[data-chart-trade-detail-modal]"),
    tradeDetailTitle: $("[data-chart-trade-detail-title]"),
    tradeDetailSummary: $("[data-chart-trade-detail-summary]"),
    tradeDetailEntry: $("[data-chart-trade-detail-entry]"),
    tradeDetailExit: $("[data-chart-trade-detail-exit]"),
  };
  const hasWindowControl = Boolean(dom.win);
  const baselinePreviewLabel = document.querySelector('[data-chart-status="preview"]')?.textContent || "Setup iniziale del report";
  const tradePageSize = 50;

  window.addEventListener("error", (event) => {
    console.error("Chart window JS error", event.error || event.message, event);
  });
  window.addEventListener("unhandledrejection", (event) => {
    console.error("Chart window unhandled rejection", event.reason, event);
  });

  // ─── Profili di focus (pesi relativi per altezze pannelli) ───────────────────
  const focusProfiles = {
    all:      { price: 5.2, equity: 2.05, drawdown: 1.25 },
    price:    { price: 7.4, equity: 0.95, drawdown: 0.65 },
    equity:   { price: 4.4, equity: 3.1,  drawdown: 0.75 },
    drawdown: { price: 3.9, equity: 2.35, drawdown: 1.9  },
  };

  // ─── Dataset e catalogo candele ───────────────────────────────────────────────
  const candleControlOptions   = buildSupportedCandleOptions(rawPayload.interval);
  const supportedCandleOptions = candleControlOptions.filter((o) => o.enabled);
  const fallbackCandleOption   = intervalDefinitions[canonicalIntervalKey(rawPayload.interval)] || intervalDefinitions["1d"];
  const datasetOptions         = supportedCandleOptions.length ? supportedCandleOptions : [{ ...fallbackCandleOption, enabled: true }];
  const datasetCatalog         = new Map(
    datasetOptions.map((option) => [
      option.key,
      option.key === rawPayload.interval ? rawPayload : aggregatePayload(rawPayload, option.key),
    ]),
  );
  const defaultCandle  = datasetCatalog.has(rawPayload.interval) ? rawPayload.interval : datasetOptions[0]?.key || rawPayload.interval;
  const initialDataset = datasetCatalog.get(defaultCandle) || rawPayload;
  const initialTotal   = initialDataset.dates.length;

  // ─── Stato ────────────────────────────────────────────────────────────────────
  const state = {
    focus:  focusProfiles[rawPayload.focus] ? rawPayload.focus : "price",
    candle: defaultCandle,
    drag:   "pan",  // solo UI, LWC non distingue modalità
    timer:  null,
    mode:   "all",
    start:  0,
    seg:    "all",
    win:    hasWindowControl ? coerceVisibleWindowForInterval(defaultCandle, parseLen(dom.win.value)) : "all",
    step:   1,
    speed:  6,
    progress: Math.max(initialTotal - 1, 0),
    visible: {
      price:           true,
      volume:          false,
      entry:           hasValues(rawPayload.entry_markers?.x),
      exit:            hasValues(rawPayload.exit_markers?.x),
      strategy:        false,
      benchmark:       false,
      gross:           false,
      drawdown:        false,
      preview_entry:   false,
      preview_exit:    false,
      preview_strategy: false,
      preview_drawdown: false,
    },
    previewRawPayload:      null,
    previewIndicatorFilter: null,
    previewAvailable: {
      preview_entry:    false,
      preview_exit:     false,
      preview_strategy: false,
      preview_drawdown: false,
    },
    selectedTradeIndex: -1,
    viewport: {
      locked:       false,
      logicalRange: null,   // {from, to} in indici LWC (float)
    },
  };

  let signalPopupText   = "";
  let signalPopupTab    = "entry";
  let signalPopupPanels = { entry: "", exit: "" };
  let tradePage         = 0;

  // ─── Istanze LWC (inizializzate in initializeChart) ──────────────────────────
  const charts = { price: null, equity: null, drawdown: null };
  const series = {
    candle:          null,
    close:           null,
    volume:          null,
    strategy:        null,
    benchmark:       null,
    gross:           null,
    drawdown:        null,
    previewStrategy: null,
    previewDrawdown: null,
  };
  let lwcPriceLine = null;

  // Indice veloce time(sec) → posizione nell'array del dataset attivo
  const timeIndex = new Map();
  // Set di tempi (sec) per rilevamento click marker
  const entryTimeToIdx = new Map();
  const exitTimeToIdx  = new Map();

  // Flag per distinguere aggiornamenti programmatici dello zoom da quelli utente
  let isProgrammaticViewport = false;
  let isSyncingTimeScale     = false;

  // ─── Avvio ────────────────────────────────────────────────────────────────────
  renderCandleControls();
  syncInputs();
  renderTradeTape();

  if (root.getBoundingClientRect().width > 0 && root.getBoundingClientRect().height > 0) {
    initializeChart();
  } else {
    window.requestAnimationFrame(initializeChart);
  }

  // ─── Inizializzazione grafico LWC ─────────────────────────────────────────────
  function initializeChart() {
    const rootRect = root.getBoundingClientRect();
    if (rootRect.width === 0 || rootRect.height === 0) {
      window.setTimeout(initializeChart, 50);
      return;
    }

    console.info("Inizializzo grafico LWC", {
      interval:   rawPayload.interval,
      date:       rawPayload.dates.length,
      hasCandles: rawPayload.market?.has_candles,
      rootRect,
    });

    // Costruisce i div pannello dentro root
    root.innerHTML = "";
    root.style.cssText = "display:flex;flex-direction:column;gap:0;overflow:hidden;";

    const pricePane    = mkPane("lwc-price-pane");
    const equityPane   = mkPane("lwc-equity-pane");
    const drawdownPane = mkPane("lwc-drawdown-pane");
    root.append(pricePane, equityPane, drawdownPane);

    // Opzioni base condivise
    const commonOpts = {
      layout: {
        background:  { color: "#05070b" },
        textColor:   "#8d98b2",
        fontFamily:  "Aptos, Segoe UI Variable, sans-serif",
        fontSize:    11,
      },
      grid: {
        vertLines: { color: "rgba(171,184,214,0.04)" },
        horzLines: { color: "rgba(171,184,214,0.05)" },
      },
      crosshair: {
        mode:     CrosshairMode.Normal,
        vertLine: { color: "rgba(171,184,214,0.3)", width: 1, style: LineStyle.Dashed, labelVisible: true },
        horzLine: { color: "rgba(171,184,214,0.3)", width: 1, style: LineStyle.Dashed, labelVisible: true },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale:  { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      timeScale: {
        borderColor:    "rgba(171,184,214,0.15)",
        timeVisible:    true,
        secondsVisible: false,
        fixLeftEdge:    true,
        fixRightEdge:   true,
        rightOffset:    2,
        lockVisibleTimeRangeOnResize: true,
      },
      rightPriceScale: {
        borderColor:   "rgba(171,184,214,0.15)",
        scaleMargins:  { top: 0.08, bottom: 0.08 },
        entireTextOnly: true,
      },
      leftPriceScale: { visible: false },
    };

    // Grafico prezzi (sempre visibile, time labels nascosti — li mostra il pannello più in basso)
    charts.price = createChart(pricePane, {
      ...commonOpts,
      width:  pricePane.clientWidth  || rootRect.width,
      height: 400,
      timeScale: { ...commonOpts.timeScale, visible: true },
    });

    // Grafico equity (mostrato solo quando almeno una curva equity è attiva)
    charts.equity = createChart(equityPane, {
      ...commonOpts,
      width:  equityPane.clientWidth || rootRect.width,
      height: 200,
      timeScale: { ...commonOpts.timeScale, visible: false },
    });

    // Grafico drawdown (mostrato solo quando drawdown è attivo)
    charts.drawdown = createChart(drawdownPane, {
      ...commonOpts,
      width:  drawdownPane.clientWidth || rootRect.width,
      height: 150,
      timeScale: { ...commonOpts.timeScale, visible: true },
    });

    // ── Serie prezzi ──────────────────────────────────────────────────────────
    if (rawPayload.market?.has_candles) {
      series.candle = charts.price.addCandlestickSeries({
        upColor:        "#26d0a8",
        downColor:      "#ff5f73",
        borderUpColor:  "#26d0a8",
        borderDownColor: "#ff5f73",
        wickUpColor:    "#26d0a8",
        wickDownColor:  "#ff5f73",
        priceLineVisible: false,
        lastValueVisible: false,
      });
    } else {
      series.close = charts.price.addLineSeries({
        color:            "#7dd3fc",
        lineWidth:        2,
        priceScaleId:     "right",
        priceLineVisible: false,
        lastValueVisible: false,
      });
    }

    // Volume sovrapposto al pannello prezzi (scala separata, parte bassa)
    series.volume = charts.price.addHistogramSeries({
      priceFormat:      { type: "volume" },
      priceScaleId:     "volume",
      lastValueVisible: false,
    });
    charts.price.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
    });

    // ── Serie equity ──────────────────────────────────────────────────────────
    series.strategy = charts.equity.addLineSeries({
      color:            "#4ade80",
      lineWidth:        2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    series.benchmark = charts.equity.addLineSeries({
      color:            "#60a5fa",
      lineWidth:        2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.gross = charts.equity.addLineSeries({
      color:            "#fbbf24",
      lineWidth:        2,
      lineStyle:        LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Preview equity/drawdown (sovrapposti ai grafici principali)
    series.previewStrategy = charts.equity.addLineSeries({
      color:            "#f59e0b",
      lineWidth:        2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.previewDrawdown = charts.drawdown.addAreaSeries({
      lineColor:   "#f97316",
      topColor:    "rgba(249,115,22,0.18)",
      bottomColor: "rgba(249,115,22,0.02)",
      lineWidth:        2,
      lineStyle:        LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // ── Serie drawdown ────────────────────────────────────────────────────────
    series.drawdown = charts.drawdown.addAreaSeries({
      lineColor:        "#ff6b7b",
      topColor:         "rgba(255,107,123,0.22)",
      bottomColor:      "rgba(255,107,123,0.02)",
      lineWidth:        2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    // ── Sincronizzazione time scale ───────────────────────────────────────────
    bindTimeScaleSync();

    // ── Events ───────────────────────────────────────────────────────────────
    bind();

    // ── Carica dati e layout ─────────────────────────────────────────────────
    updateChartData();
    applyPanelVisibility();
    applyReplay();
    syncUi();
  }

  // ─── Bind eventi UI ───────────────────────────────────────────────────────────
  function bind() {
    $$("[data-focus-view]").forEach((b) => b.addEventListener("click", () => {
      const nextFocus = b.dataset.focusView || "all";
      if (nextFocus === state.focus) { syncUi(); return; }
      resetViewportLock();
      state.focus = nextFocus;
      rerenderChart();
    }));

    $$("[data-chart-action]").forEach((b) => b.addEventListener("click", () => chartAction(b.dataset.chartAction || "")));
    $$("[data-chart-indicator-open]").forEach((b) => b.addEventListener("click", openIndicatorModal));
    $$("[data-chart-indicator-close]").forEach((b) => b.addEventListener("click", closeIndicatorModal));

    $$("[data-trace-toggle]").forEach((b) => {
      if (b.dataset.locked === "true") return;
      b.addEventListener("click", () => {
        const key = b.dataset.traceToggle;
        if (!key) return;
        state.visible[key] = !state.visible[key];
        // Tutti i toggle ricalcolano le serie (le visibility panel sono gestite internamente)
        resetViewportLock();
        rerenderChart();
      });
    });

    $$("[data-playback-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.playbackMode || "all")));
    $$("[data-playback-action]").forEach((b) => b.addEventListener("click", () => playbackAction(b.dataset.playbackAction || "")));
    dom.start?.addEventListener("input",  () => { state.start = Math.max(Number(dom.start.value) - 1, 0); clamp(true); applyReplay(); });
    dom.seg?.addEventListener("change",   () => { state.seg = parseLen(dom.seg.value); clamp(true); applyReplay(); });
    dom.win?.addEventListener("change",   () => { state.win = parseLen(dom.win.value); clamp(); applyReplay(); });
    dom.step?.addEventListener("change",  () => { state.step = Math.max(Number(dom.step.value) || 1, 1); syncUi(); });
    dom.speed?.addEventListener("input",  () => { state.speed = Math.max(Number(dom.speed.value) || 1, 1); if (state.timer) restartTimer(); syncUi(); });
    dom.progress?.addEventListener("input", () => { stopTimer(); setMode("replay"); state.progress = Math.max(Number(dom.progress.value) - 1, 0); clamp(); applyReplay(); });
    dom.indicatorSearch?.addEventListener("input", filterIndicatorCatalog);
    dom.signalPopupCopy?.addEventListener("click", copySignalPopupText);
    dom.signalPopupTabs.forEach((button) => {
      button.addEventListener("click", () => setSignalPopupTab(button.dataset.signalPopupTab || "entry"));
    });
    dom.tradePrev?.addEventListener("click", () => moveTradePage(-1));
    dom.tradeNext?.addEventListener("click", () => moveTradePage(1));
    dom.tradeTable?.addEventListener("click",   onTradeTableClick);
    dom.tradeTable?.addEventListener("keydown", onTradeTableKeydown);
    $$("[data-chart-trade-detail-close]").forEach((button) => button.addEventListener("click", closeTradeDetailModal));
    document.addEventListener("keydown", onKeydown);

    // Click e crosshair LWC
    charts.price?.subscribeClick(onLwcPriceClick);
    charts.price?.subscribeCrosshairMove(onLwcCrosshairMove);
    charts.equity?.subscribeClick(() => hideSignalPopup());
    charts.drawdown?.subscribeClick(() => hideSignalPopup());

    window.addEventListener("resize", onWindowResize);
  }

  // ─── Sincronizzazione time scale multi-pannello ───────────────────────────────
  function bindTimeScaleSync() {
    const all = [charts.price, charts.equity, charts.drawdown];

    all.forEach((source, i) => {
      if (!source) return;
      source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (isSyncingTimeScale || range === null) return;
        isSyncingTimeScale = true;
        try {
          all.forEach((target, j) => {
            if (i !== j && target) target.timeScale().setVisibleLogicalRange(range);
          });
          // Cattura viewport solo per input utente
          if (!isProgrammaticViewport) {
            state.viewport.locked = true;
            state.viewport.logicalRange = { from: range.from, to: range.to };
          }
        } finally {
          isSyncingTimeScale = false;
        }
      });
    });
  }

  // ─── Aggiornamento dati su tutti i grafici ────────────────────────────────────
  function updateChartData() {
    const data        = activePayload();
    const previewData = activePreviewPayload();

    rebuildTimeIndex(data);
    rebuildMarkerSets(data);

    // Candele o linea prezzo
    const barData = buildBarData(data);
    if (series.candle) {
      series.candle.setData(barData);
    } else if (series.close) {
      series.close.setData(buildLineData(data.dates, data.market?.close));
    }

    // Volume
    series.volume?.setData(state.visible.volume ? buildVolumeData(data) : []);

    // Equity
    series.strategy?.setData(state.visible.strategy ? buildLineData(data.dates, data.equity?.strategy) : []);
    series.benchmark?.setData(state.visible.benchmark ? buildLineData(data.dates, data.equity?.benchmark) : []);
    series.gross?.setData(state.visible.gross ? buildLineData(data.dates, data.equity?.gross) : []);

    // Preview equity
    series.previewStrategy?.setData(
      (state.visible.preview_strategy && previewData)
        ? buildLineData(previewData.dates, previewData.equity?.strategy)
        : [],
    );

    // Drawdown
    series.drawdown?.setData(
      state.visible.drawdown ? buildAreaData(data.dates, data.drawdown_pct) : [],
    );

    // Preview drawdown
    series.previewDrawdown?.setData(
      (state.visible.preview_drawdown && previewData)
        ? buildAreaData(previewData.dates, previewData.drawdown_pct)
        : [],
    );

    // Marker entry/exit (+ preview + evidenziazione trade selezionato)
    updateAllMarkers(data, previewData);

    // Linea prezzo corrente
    const bounds = resolveVisibleBounds(data);
    updatePriceLine(bounds.current, data);
  }

  // ─── Ricostruzione marker su tutti i grafici ──────────────────────────────────
  function updateAllMarkers(data = activePayload(), previewData = activePreviewPayload()) {
    const markers = [];

    if (state.visible.entry) {
      const em = data.entry_markers;
      em.x.forEach((label, i) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "belowBar", color: "#21c98b", shape: "arrowUp",   size: 1.5 });
      });
    }

    if (state.visible.exit) {
      const xm = data.exit_markers;
      xm.x.forEach((label, i) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "aboveBar", color: "#ff5f73", shape: "arrowDown", size: 1.5 });
      });
    }

    if (state.visible.preview_entry && previewData) {
      previewData.entry_markers.x.forEach((label) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "belowBar", color: "#f59e0b", shape: "square",    size: 1.2 });
      });
    }

    if (state.visible.preview_exit && previewData) {
      previewData.exit_markers.x.forEach((label) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "aboveBar", color: "#fb7185", shape: "square",    size: 1.2 });
      });
    }

    // Trade selezionato: aggiunge un cerchio evidenziato
    if (state.selectedTradeIndex >= 0) {
      const overlay = buildSelectedTradeOverlay(data);
      overlay.entry.x.forEach((label) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "belowBar", color: "#34e6b8", shape: "circle",   size: 2.5 });
      });
      overlay.exit.x.forEach((label) => {
        const t = toLwcTime(label);
        if (t !== null) markers.push({ time: t, position: "aboveBar", color: "#ff8fa0", shape: "circle",   size: 2.5 });
      });
    }

    // I marker devono essere ordinati per time
    markers.sort((a, b) => Number(a.time) - Number(b.time));

    const activeSeries = series.candle || series.close;
    activeSeries?.setMarkers(markers);
  }

  // ─── Linea prezzo corrente ────────────────────────────────────────────────────
  function updatePriceLine(index, data) {
    const activeSeries = series.candle || series.close;
    if (!activeSeries) return;
    const close = val(data.market?.close, index);
    if (close === null) return;
    const prev  = index > 0 ? val(data.market?.close, index - 1) : close;
    const color = close >= prev ? "rgba(38,208,168,0.6)" : "rgba(255,95,115,0.6)";

    if (!lwcPriceLine) {
      lwcPriceLine = activeSeries.createPriceLine({
        price:             close,
        color,
        lineWidth:         1,
        lineStyle:         LineStyle.Dotted,
        axisLabelVisible:  true,
        title:             "",
      });
    } else {
      lwcPriceLine.applyOptions({ price: close, color });
    }
  }

  // ─── Visibilità e altezze pannelli ────────────────────────────────────────────
  function applyPanelVisibility() {
    const showEquity    = Boolean(state.visible.strategy || state.visible.benchmark || state.visible.gross || state.visible.preview_strategy);
    const showDrawdown  = Boolean(state.visible.drawdown || state.visible.preview_drawdown);

    const equityPane    = root.querySelector(".lwc-equity-pane");
    const drawdownPane  = root.querySelector(".lwc-drawdown-pane");
    if (equityPane)   equityPane.hidden   = !showEquity;
    if (drawdownPane) drawdownPane.hidden = !showDrawdown;

    computeAndApplyPanelHeights(showEquity, showDrawdown);
  }

  function computeAndApplyPanelHeights(showEquity, showDrawdown) {
    // Usa l'altezza minima CSS (640px) come fallback se il root è 0
    const totalHeight = Math.max(root.clientHeight || 640, 480);
    const profile     = focusProfiles[state.focus] || focusProfiles.all;

    const weights = { price: profile.price };
    if (showEquity)   weights.equity    = profile.equity;
    if (showDrawdown) weights.drawdown  = profile.drawdown;
    const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);

    const priceH    = Math.round(totalHeight * weights.price  / totalWeight);
    const equityH   = showEquity    ? Math.round(totalHeight * weights.equity   / totalWeight) : 0;
    const drawdownH = showDrawdown  ? Math.round(totalHeight * weights.drawdown / totalWeight) : 0;

    const pricePane    = root.querySelector(".lwc-price-pane");
    const equityPane   = root.querySelector(".lwc-equity-pane");
    const drawdownPane = root.querySelector(".lwc-drawdown-pane");
    const w = root.clientWidth || 800;

    if (pricePane)    { pricePane.style.height    = `${priceH}px`;    charts.price?.applyOptions({ width: w, height: priceH }); }
    if (equityPane)   { equityPane.style.height   = `${equityH}px`;   charts.equity?.applyOptions({ width: w, height: equityH }); }
    if (drawdownPane) { drawdownPane.style.height = `${drawdownH}px`; charts.drawdown?.applyOptions({ width: w, height: drawdownH }); }
  }

  // ─── Re-render completo (sostituisce Plotly.react) ────────────────────────────
  function rerenderChart() {
    hideSignalPopup();
    updateChartData();
    applyPanelVisibility();

    if (state.viewport.locked && state.viewport.logicalRange) {
      setRangeProgrammatically(state.viewport.logicalRange);
    } else {
      applyReplay({ preserveViewport: false });
    }
    syncUi();
  }

  // ─── Applica il range visibile (viewport) ─────────────────────────────────────
  function applyReplay(options = {}) {
    const preserveViewport = Boolean(options.preserveViewport || state.viewport.locked);
    const data = activePayload();
    clamp();
    const bounds = resolveVisibleBounds(data);

    updateMarket(bounds.current);
    updateReplayInfo(bounds.current);
    updatePriceLine(bounds.current, data);

    if (!preserveViewport && charts.price) {
      const initialWindow = defaultVisibleWindow(state.candle);
      const useDateRange  = initialWindow !== "all" && data.dates.length > Number(initialWindow);

      if (useDateRange) {
        // Finestra iniziale: mostra le ultime N candele
        const rightIdx = data.dates.length - 1;
        const leftIdx  = Math.max(0, rightIdx - Number(initialWindow));
        const fromTime = toLwcTime(data.dates[leftIdx]);
        const toTime   = toLwcTime(data.dates[rightIdx]);
        if (fromTime !== null && toTime !== null) {
          setRangeProgrammatically(null, { from: fromTime, to: toTime });
          return;
        }
      }
      // Mostra tutto
      charts.price.timeScale().fitContent();
      charts.equity?.timeScale().fitContent();
      charts.drawdown?.timeScale().fitContent();
    }
    syncUi();
  }

  // ─── Imposta range programmaticamente (senza catturare viewport utente) ───────
  function setRangeProgrammatically(logicalRange = null, timeRange = null) {
    isProgrammaticViewport = true;
    isSyncingTimeScale     = true;
    try {
      const all = [charts.price, charts.equity, charts.drawdown];
      if (logicalRange) {
        all.forEach((c) => c?.timeScale().setVisibleLogicalRange(logicalRange));
      } else if (timeRange) {
        all.forEach((c) => c?.timeScale().setVisibleRange(timeRange));
      }
    } finally {
      isSyncingTimeScale     = false;
      isProgrammaticViewport = false;
    }
  }

  // ─── Azioni toolbar ───────────────────────────────────────────────────────────
  function chartAction(action) {
    if (action === "pan" || action === "zoom") {
      state.drag = action;
      // In LWC pan e zoom coesistono nativamente; aggiorniamo solo l'UI
      return syncUi();
    }
    if (action === "reset") return resetChart();
    if (action === "export") return exportChart();
    if (action === "fullscreen") {
      if (document.fullscreenElement) {
        document.exitFullscreen?.();
      } else {
        document.documentElement.requestFullscreen().catch(() => {});
      }
    }
  }

  function resetChart() {
    stopTimer();
    hideSignalPopup();
    resetViewportLock();
    isProgrammaticViewport = true;
    isSyncingTimeScale     = true;
    try {
      charts.price?.timeScale().fitContent();
      charts.equity?.timeScale().fitContent();
      charts.drawdown?.timeScale().fitContent();
    } finally {
      isSyncingTimeScale     = false;
      isProgrammaticViewport = false;
    }
    applyReplay({ preserveViewport: false });
    syncUi();
  }

  function exportChart() {
    // Canvas LWC si trova nel pane prezzi
    const canvas = root.querySelector(".lwc-price-pane canvas");
    if (!canvas) return;
    const link      = document.createElement("a");
    link.download   = "trading-bot-chart.png";
    link.href       = canvas.toDataURL("image/png");
    link.click();
  }

  // ─── Viewport ─────────────────────────────────────────────────────────────────
  function resetViewportLock() {
    state.viewport.locked       = false;
    state.viewport.logicalRange = null;
  }

  // ─── Resize finestra ──────────────────────────────────────────────────────────
  function onWindowResize() {
    const showEquity   = Boolean(state.visible.strategy || state.visible.benchmark || state.visible.gross || state.visible.preview_strategy);
    const showDrawdown = Boolean(state.visible.drawdown || state.visible.preview_drawdown);
    computeAndApplyPanelHeights(showEquity, showDrawdown);
  }

  // ─── Click su grafico prezzi ──────────────────────────────────────────────────
  function onLwcPriceClick(param) {
    if (!param.time) {
      hideSignalPopup();
      return;
    }

    const t    = Number(param.time);
    const data = activePayload();
    let signalSide = null;
    let markerIdx  = -1;

    // Exit ha la precedenza su entry se entrambi allo stesso time
    if (state.visible.exit && exitTimeToIdx.has(t)) {
      signalSide = "exit";
      markerIdx  = exitTimeToIdx.get(t);
    } else if (state.visible.entry && entryTimeToIdx.has(t)) {
      signalSide = "entry";
      markerIdx  = entryTimeToIdx.get(t);
    }

    if (signalSide === null) {
      hideSignalPopup();
      return;
    }

    const markers   = signalSide === "entry" ? data.entry_markers : data.exit_markers;
    const hoverText = markers.text?.[markerIdx] || "";

    // Costruisce un oggetto compatibile con showSignalPopup (stessa interfaccia del vecchio Plotly)
    const pricePane = root.querySelector(".lwc-price-pane");
    const paneRect  = pricePane?.getBoundingClientRect() || { left: 0, top: 0 };
    const mockPoint = {
      data:      { name: signalSide === "entry" ? "Ingresso" : "Uscita" },
      x:         markers.x?.[markerIdx] || "",
      hovertext: hoverText,
      event: {
        clientX: paneRect.left + (param.point?.x || 0),
        clientY: paneRect.top  + (param.point?.y || 0),
      },
    };
    showSignalPopup(mockPoint);
  }

  // ─── Crosshair: aggiorna OHLCV nel DOM ───────────────────────────────────────
  function onLwcCrosshairMove(param) {
    if (!param.time) return;
    const index = timeIndex.get(Number(param.time));
    if (index !== undefined) updateMarket(index);
  }

  // ─── Cambio dimensione candela ────────────────────────────────────────────────
  function setCandleSize(intervalKey) {
    const nextKey = canonicalIntervalKey(intervalKey);
    if (!datasetCatalog.has(nextKey) || nextKey === state.candle) return;
    stopTimer();
    resetViewportLock();
    state.candle = nextKey;
    state.win    = hasWindowControl ? coerceVisibleWindowForInterval(nextKey, state.win) : "all";
    syncPreviewAvailability();
    // Ricarica dati per il nuovo intervallo
    updateChartData();
    applyReplay({ preserveViewport: false });
    syncUi();
  }

  // ─── Playback (replay mode) ───────────────────────────────────────────────────
  function playbackAction(action) {
    if (action === "restart")        { stopTimer(); setMode("replay"); state.progress = 0; return applyReplay(); }
    if (action === "step-back")      { stopTimer(); setMode("replay"); return move(-state.step); }
    if (action === "step-forward")   { stopTimer(); setMode("replay"); return move(state.step); }
    if (action === "toggle-play") {
      if (state.timer) return stopTimer();
      setMode("replay");
      if (state.progress >= segLen() - 1) state.progress = 0;
      restartTimer();
    }
  }

  function restartTimer() {
    stopTimer();
    state.timer = window.setInterval(() => { if (!move(state.step)) stopTimer(); }, Math.max(1000 / state.speed, 80));
    syncUi();
  }

  function stopTimer() {
    if (state.timer) { window.clearInterval(state.timer); state.timer = null; }
    syncUi();
  }

  function setMode(mode) {
    state.mode = mode === "replay" ? "replay" : "all";
    if (state.mode === "all") state.progress = segLen() - 1;
    syncUi();
  }

  function move(delta) {
    const next = Math.min(Math.max(state.progress + delta, 0), segLen() - 1);
    if (next === state.progress) return false;
    state.progress = next;
    applyReplay();
    return true;
  }

  function applyFocus() { syncUi(); }

  // ─── Sinc UI ──────────────────────────────────────────────────────────────────
  function syncInputs() {
    if (dom.start)    { dom.start.min = "1"; dom.start.max = String(maxStart() + 1); dom.start.value = String(state.start + 1); }
    if (dom.seg)      dom.seg.value   = String(state.seg);
    if (dom.win)      dom.win.value   = String(state.win);
    if (dom.step)     dom.step.value  = String(state.step);
    if (dom.speed)    dom.speed.value = String(state.speed);
    if (dom.progress) { dom.progress.min = "1"; dom.progress.max = String(segLen()); dom.progress.value = String(state.progress + 1); dom.progress.disabled = state.mode === "all"; }
  }

  function syncUi() {
    $$("[data-focus-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.focusView === state.focus));
    $$("[data-candle-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.candleView === state.candle));
    $$("[data-chart-action]").forEach((b) => b.classList.toggle("is-active", b.dataset.chartAction === state.drag));
    $$("[data-trace-toggle]").forEach((b) => { const k = b.dataset.traceToggle || ""; b.classList.toggle("is-on", !!state.visible[k]); });
    $$("[data-playback-mode]").forEach((b) => b.classList.toggle("is-active", b.dataset.playbackMode === state.mode));
    if (dom.toggleLabel) dom.toggleLabel.textContent = state.timer ? "Pausa" : "Play";
    if (dom.speedBadge)  dom.speedBadge.textContent  = `${state.speed}x/sec`;
    setStatus("mode",     state.drag === "zoom" ? "Zoom" : "Pan");
    setStatus("focus",    ({ all: "Multi panel", price: "Prezzo", equity: "Equity", drawdown: "Drawdown" }[state.focus]) || state.focus);
    setStatus("candle",   candleLabel(state.candle));
    setStatus("playback", state.mode === "replay" ? "Replay" : "Tutto subito");
    setStatus("speed",    `${state.speed}x/sec`);
    updatePreviewLayerButtons();
    updateIndicatorSummary();
    filterIndicatorCatalog();
  }

  function updateReplayInfo(current) {
    const data = activePayload();
    if (dom.startLabel)    dom.startLabel.textContent    = `Da candle ${state.start + 1}`;
    if (dom.startDate)     dom.startDate.textContent     = data.dates[state.start] || "-";
    if (dom.progressLabel) dom.progressLabel.textContent = `Candle ${current + 1} / ${totalPoints()}`;
    if (dom.progressDate)  dom.progressDate.textContent  = data.dates[current] || "-";
  }

  function updateMarket(i) {
    const data = activePayload();
    const close = val(data.market?.close, i), open = val(data.market?.open, i), high = val(data.market?.high, i), low = val(data.market?.low, i), prev = i > 0 ? val(data.market?.close, i - 1) : open, volume = val(data.market?.volume, i);
    text(dom.open, fmt(open)); text(dom.high, fmt(high)); text(dom.low, fmt(low)); text(dom.close, fmt(close)); text(dom.closePanel, fmt(close)); text(dom.timestamp, data.dates[i] || "-"); if (volume !== null) text(dom.volume, compact(volume));
    if (close === null || prev === null || prev === 0) return setChange("neutral", "n/a", "n/a");
    const delta = close - prev, pct = (delta / prev) * 100, cls = delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral";
    setChange(cls, signed(delta), signedPct(pct));
  }

  function setChange(cls, a, b) {
    [dom.change, dom.changePct].forEach((n) => { if (!n) return; n.classList.remove("terminal-change-positive", "terminal-change-negative", "terminal-change-neutral"); n.classList.add(`terminal-change-${cls}`); });
    text(dom.change, a); text(dom.changePct, b);
  }

  // ─── Conversione dati → formato LWC ──────────────────────────────────────────
  function toLwcTime(label) {
    const parsed = parseChartDateLabel(label);
    if (!parsed) return null;
    return Math.floor(parsed.getTime() / 1000); // Unix secondi
  }

  function buildBarData(data) {
    const result = [];
    (data.dates || []).forEach((label, i) => {
      const t = toLwcTime(label);
      const o = val(data.market?.open,  i);
      const h = val(data.market?.high,  i);
      const l = val(data.market?.low,   i);
      const c = val(data.market?.close, i);
      if (t !== null && o !== null && h !== null && l !== null && c !== null) {
        result.push({ time: t, open: o, high: h, low: l, close: c });
      }
    });
    return result;
  }

  function buildLineData(dates, values) {
    const result = [];
    (dates || []).forEach((label, i) => {
      const t = toLwcTime(label);
      const v = (values || [])[i];
      if (t !== null && v !== null && Number.isFinite(v)) {
        result.push({ time: t, value: v });
      }
    });
    return result;
  }

  // Come buildLineData ma colorato per area series (drawdown, valori ≤ 0)
  function buildAreaData(dates, values) {
    return buildLineData(dates, values);
  }

  function buildVolumeData(data) {
    const result = [];
    (data.dates || []).forEach((label, i) => {
      const t = toLwcTime(label);
      const v = val(data.market?.volume, i);
      const c = val(data.market?.close,  i);
      const o = val(data.market?.open,   i) ?? (i > 0 ? val(data.market?.close, i - 1) : c);
      if (t !== null && v !== null) {
        result.push({
          time:  t,
          value: v,
          color: c !== null && o !== null && c >= o ? "rgba(38,208,168,0.45)" : "rgba(255,95,115,0.45)",
        });
      }
    });
    return result;
  }

  // ─── Indici veloci ────────────────────────────────────────────────────────────
  function rebuildTimeIndex(data) {
    timeIndex.clear();
    (data.dates || []).forEach((label, i) => {
      const t = toLwcTime(label);
      if (t !== null) timeIndex.set(t, i);
    });
  }

  function rebuildMarkerSets(data) {
    entryTimeToIdx.clear();
    exitTimeToIdx.clear();
    (data.entry_markers?.x || []).forEach((label, i) => {
      const t = toLwcTime(label);
      if (t !== null && !entryTimeToIdx.has(t)) entryTimeToIdx.set(t, i);
    });
    (data.exit_markers?.x || []).forEach((label, i) => {
      const t = toLwcTime(label);
      if (t !== null && !exitTimeToIdx.has(t)) exitTimeToIdx.set(t, i);
    });
  }

  // ─── Utility DOM ─────────────────────────────────────────────────────────────
  function mkPane(className) {
    const div = document.createElement("div");
    div.className    = className;
    div.style.cssText = "width:100%;overflow:hidden;";
    return div;
  }

  function createElement(tag, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  // ─── buildChartStructure (semplificato per LWC) ───────────────────────────────
  function buildChartStructure() {
    const showEquityPanel   = Boolean(state.visible.strategy || state.visible.benchmark || state.visible.gross || state.visible.preview_strategy);
    const showDrawdownPanel = Boolean(state.visible.drawdown || state.visible.preview_drawdown);
    return { showEquityPanel, showDrawdownPanel };
  }

  // ─── buildSelectedTradeOverlay ────────────────────────────────────────────────
  function buildSelectedTradeOverlay(data = activePayload()) {
    const empty = { entry: { x: [], y: [], visible: false }, exit: { x: [], y: [], visible: false } };
    if (!Number.isInteger(state.selectedTradeIndex) || state.selectedTradeIndex < 0) return empty;
    const trade = tradeRows[state.selectedTradeIndex];
    if (!trade) return empty;

    const entryPoint = resolveTradeMarkerPoint({ markers: data.entry_markers, rawTimestamp: trade.entry_raw, expectedPrice: trade.entry_price_display, intervalKey: data.interval });
    const exitPoint  = resolveTradeMarkerPoint({ markers: data.exit_markers,  rawTimestamp: trade.exit_raw,  expectedPrice: trade.exit_price_display,  intervalKey: data.interval });

    if (entryPoint) empty.entry = { x: [entryPoint.x], y: [entryPoint.y], visible: true };
    if (exitPoint)  empty.exit  = { x: [exitPoint.x],  y: [exitPoint.y],  visible: true };
    return empty;
  }

  function resolveTradeMarkerPoint({ markers, rawTimestamp, expectedPrice, intervalKey }) {
    if (!markers || !rawTimestamp) return null;
    const markerLabels = Array.isArray(markers.x) ? markers.x : [];
    const markerPrices = Array.isArray(markers.y) ? markers.y : [];
    const targetLabel  = signalBucketLabel(rawTimestamp, intervalKey);
    if (!targetLabel) return null;

    const candidateIndexes = [];
    markerLabels.forEach((label, index) => {
      if (normalizeSignalTimestamp(label) === normalizeSignalTimestamp(targetLabel)) candidateIndexes.push(index);
    });
    if (!candidateIndexes.length) return null;

    const expected = parseSignalPrice(expectedPrice);
    let chosenIndex = candidateIndexes[0];
    if (Number.isFinite(expected)) {
      chosenIndex = candidateIndexes.reduce((best, current) => {
        const bestDistance    = Math.abs(Number(markerPrices[best]    ?? Number.POSITIVE_INFINITY) - expected);
        const currentDistance = Math.abs(Number(markerPrices[current] ?? Number.POSITIVE_INFINITY) - expected);
        return currentDistance < bestDistance ? current : best;
      }, chosenIndex);
    }
    const xValue = markerLabels[chosenIndex];
    const yValue = Number(markerPrices[chosenIndex]);
    if (!xValue || !Number.isFinite(yValue)) return null;
    return { x: String(xValue), y: yValue };
  }

  function signalBucketLabel(rawTimestamp, intervalKey) {
    const parsed = parseChartDateLabel(rawTimestamp);
    if (!parsed) return normalizeSignalTimestamp(rawTimestamp);
    const bucketDate = floorToBucket(parsed, intervalKey);
    return formatBucketLabel(bucketDate, intervalKey);
  }

  function parseSignalPrice(rawValue) {
    const parsed = Number(String(rawValue || "").replace(/[^0-9.+-]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  // ─── Funzioni di utilità ──────────────────────────────────────────────────────
  function segLen() { return state.seg === "all" ? Math.max(totalPoints() - state.start, 1) : Math.max(Math.min(Number(state.seg) || 1, totalPoints() - state.start), 1); }
  function winLen() { return state.win === "all" ? segLen() : Math.max(Math.min(Number(state.win) || 1, segLen()), 1); }
  function maxStart() { return state.seg === "all" ? Math.max(totalPoints() - 1, 0) : Math.max(totalPoints() - (Number(state.seg) || 1), 0); }

  function resolveVisibleBounds(data = activePayload()) {
    const total     = Array.isArray(data?.dates) ? data.dates.length : totalPoints();
    const segLength = state.seg === "all" ? Math.max(total - state.start, 1) : Math.max(Math.min(Number(state.seg) || 1, total - state.start), 1);
    const end       = state.mode === "all" ? state.start + segLength - 1 : state.start + state.progress;
    const current   = Math.min(Math.max(end, state.start), Math.max(total - 1, 0));
    const windowLength = state.win === "all" ? segLength : Math.max(Math.min(Number(state.win) || 1, segLength), 1);
    const first     = windowLength >= segLength ? state.start : Math.max(state.start, current - windowLength + 1);
    const left      = Math.max(first - 1, 0);
    const right     = Math.min(current + 1, Math.max(total - 1, 0));
    return { left, right, current };
  }

  function slicePayloadWindow(payload, left, right) {
    const start = Math.max(Number(left) || 0, 0);
    const end   = Math.max(Number(right) || start, start);
    const slice = (values) => (Array.isArray(values) ? values.slice(start, end + 1) : []);
    return {
      ...payload,
      dates:       slice(payload?.dates),
      parsedDates: slice(payload?.parsedDates),
      market: {
        has_candles: Boolean(payload?.market?.has_candles),
        open:   slice(payload?.market?.open),
        high:   slice(payload?.market?.high),
        low:    slice(payload?.market?.low),
        close:  slice(payload?.market?.close),
        volume: slice(payload?.market?.volume),
      },
      equity: {
        strategy:  slice(payload?.equity?.strategy),
        gross:     slice(payload?.equity?.gross),
        benchmark: slice(payload?.equity?.benchmark),
      },
      drawdown_pct:   slice(payload?.drawdown_pct),
      indicators:     payload?.indicators,
      entry_markers:  payload?.entry_markers,
      exit_markers:   payload?.exit_markers,
    };
  }

  function sliceMarkersByWindow(markers, leftLabel, rightLabel) {
    const result = { x: [], y: [], text: [] };
    if (!markers || !Array.isArray(markers.x) || !Array.isArray(markers.y)) return result;
    const left = String(leftLabel || ""); const right = String(rightLabel || "");
    markers.x.forEach((label, index) => {
      const markerLabel = String(label || "");
      if (left && markerLabel < left) return;
      if (right && markerLabel > right) return;
      result.x.push(markerLabel);
      result.y.push(Number(markers.y[index]));
      result.text.push(String(markers.text?.[index] || ""));
    });
    return result;
  }

  function defaultVisibleWindow(intervalKey) {
    const minutes = intervalToMinutes(intervalKey);
    if (!Number.isFinite(minutes)) return "all";
    if (minutes <= 1)   return 390;
    if (minutes <= 2)   return 300;
    if (minutes <= 5)   return 180;
    if (minutes <= 30)  return 100;
    if (minutes <= 60)  return 84;
    if (minutes <= 240) return 72;
    return "all";
  }

  function coerceVisibleWindowForInterval(intervalKey, currentWindow) {
    const preferred = defaultVisibleWindow(intervalKey);
    if (preferred === "all") return currentWindow;
    if (currentWindow === "all") return preferred;
    const preferredNumber = Number(preferred), currentNumber = Number(currentWindow);
    if (!Number.isFinite(preferredNumber) || !Number.isFinite(currentNumber)) return preferred;
    return currentNumber > (preferredNumber * 2) ? preferred : currentNumber;
  }

  function parseLen(v)   { return v === "all" ? "all" : Math.max(Number(v) || 1, 1); }
  function val(arr, i)   { return Array.isArray(arr) && arr[i] != null ? Number(arr[i]) : null; }
  function text(node, v) { if (node) node.textContent = v; }
  function fmt(v)        { return v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(3).replace(/\.?0+$/, ""); }
  function signed(v)     { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${Number(v).toFixed(3).replace(/\.?0+$/, "")}`; }
  function signedPct(v)  { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`; }
  function compact(v)    { const a = Math.abs(v); if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`; if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`; if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`; return `${Math.round(v)}`; }
  function setStatus(k, v) { const n = document.querySelector(`[data-chart-status="${k}"]`); if (n) n.textContent = v; }
  function hasValues(arr)  { return Array.isArray(arr) && arr.some((v) => v !== null && v !== undefined); }
  function totalPoints()   { return activePayload().dates.length; }
  function activePayload() { return datasetCatalog.get(state.candle) || rawPayload; }
  function activePreviewPayload() {
    if (!state.previewRawPayload) return null;
    const filteredPayload = filterPreviewPayload(state.previewRawPayload, state.previewIndicatorFilter);
    return aggregatePayload(filteredPayload, state.candle);
  }
  function intervalToMinutes(interval) { return intervalDefinitions[canonicalIntervalKey(interval)]?.unit === "minute" ? intervalDefinitions[canonicalIntervalKey(interval)].minutes : null; }
  function candleLabel(interval) { return intervalDefinitions[canonicalIntervalKey(interval)]?.label || String(interval || "").trim() || "n/d"; }

  function canonicalIntervalKey(interval) {
    const raw = String(interval || "").trim().toLowerCase();
    if (raw === "60m")  return "1h";
    if (raw === "240m") return "4h";
    if (raw === "1g")   return "1d";
    if (raw === "1w")   return "1wk";
    return intervalDefinitions[raw]?.key || "1d";
  }

  // ─── Controlli candele ────────────────────────────────────────────────────────
  function buildSupportedCandleOptions(baseInterval) {
    const baseKey        = canonicalIntervalKey(baseInterval);
    const baseDefinition = intervalDefinitions[baseKey] || intervalDefinitions["1d"];
    const preferred      = candleControlOrder.map((key) => intervalDefinitions[key]).filter(Boolean).map((candidate) => ({ ...candidate, enabled: canUseCandleSize(baseDefinition, candidate) }));
    if (!preferred.some((c) => c.key === baseDefinition.key)) return [{ ...baseDefinition, enabled: true }, ...preferred];
    if (preferred.length) return preferred;
    return [{ ...baseDefinition, enabled: true }];
  }

  function canUseCandleSize(baseDefinition, candidate) {
    if (!baseDefinition || !candidate) return false;
    if (candidate.minutes < baseDefinition.minutes) return false;
    if (baseDefinition.unit === "minute" && candidate.unit === "minute") return candidate.minutes >= baseDefinition.minutes;
    if (baseDefinition.unit === "day")   return candidate.unit === "day" || candidate.unit === "week" || candidate.unit === "month";
    if (baseDefinition.unit === "week")  return candidate.unit === "week" || candidate.unit === "month";
    if (baseDefinition.unit === "month") return candidate.unit === "month";
    return true;
  }

  function renderCandleControls() {
    if (!dom.candleControls) return;
    dom.candleControls.innerHTML = candleControlOptions.map((option) => `
      <button
        type="button"
        class="terminal-chip${option.key === state.candle ? " is-active" : ""}${option.enabled ? "" : " is-disabled"}"
        data-candle-view="${option.key}"
        ${option.enabled ? "" : "disabled aria-disabled=\"true\" title=\"Timeframe non disponibile su questo dataset\""}
      >
        ${option.label}
      </button>
    `).join("");
    $$("[data-candle-view]").forEach((button) => {
      if (button.disabled) return;
      button.addEventListener("click", () => setCandleSize(button.dataset.candleView || rawPayload.interval));
    });
  }

  // ─── Parsing e normalizzazione ────────────────────────────────────────────────
  function parseChartDateLabel(label) {
    if (typeof label === "number" && Number.isFinite(label)) {
      const fromEpoch = new Date(label);
      return Number.isNaN(fromEpoch.getTime()) ? null : fromEpoch;
    }
    const raw = String(label || "").trim();
    if (!raw) return null;
    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
    if (!match) {
      const fallback = new Date(raw);
      return Number.isNaN(fallback.getTime()) ? null : fallback;
    }
    const [, year, month, day, hours = "00", minutes = "00", seconds = "00"] = match;
    const parsed = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hours), Number(minutes), Number(seconds)));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function normalizePayload(payload, fallbackInterval = "1d") {
    const dates = Array.isArray(payload?.dates) ? payload.dates.map((value) => String(value || "")) : [];
    return {
      focus:    payload?.focus || "price",
      interval: canonicalIntervalKey(payload?.interval || fallbackInterval || "1d"),
      dates,
      parsedDates: dates.map(parseChartDateLabel).filter((value) => value),
      market: {
        has_candles: Boolean(payload?.market?.has_candles),
        open:   normalizeSeries(payload?.market?.open),
        high:   normalizeSeries(payload?.market?.high),
        low:    normalizeSeries(payload?.market?.low),
        close:  normalizeSeries(payload?.market?.close),
        volume: normalizeSeries(payload?.market?.volume),
      },
      equity: {
        strategy:  normalizeSeries(payload?.equity?.strategy),
        gross:     normalizeSeries(payload?.equity?.gross),
        benchmark: normalizeSeries(payload?.equity?.benchmark),
      },
      drawdown_pct:  normalizeSeries(payload?.drawdown_pct),
      entry_markers: normalizeMarkers(payload?.entry_markers),
      exit_markers:  normalizeMarkers(payload?.exit_markers),
      indicators:    normalizeIndicators(payload?.indicators),
    };
  }

  function normalizeSeries(values) {
    return Array.isArray(values) ? values.map((value) => (value == null || Number.isNaN(Number(value)) ? null : Number(value))) : [];
  }

  function normalizeMarkers(markers) {
    return {
      x:    Array.isArray(markers?.x)    ? markers.x.map((value) => String(value || "")) : [],
      y:    Array.isArray(markers?.y)    ? markers.y.map((value) => (value == null || Number.isNaN(Number(value)) ? null : Number(value))) : [],
      text: Array.isArray(markers?.text) ? markers.text.map((value) => String(value || "")) : [],
    };
  }

  function normalizeIndicators(indicators) {
    return Array.isArray(indicators)
      ? indicators.map((indicator) => ({
        key:         String(indicator?.key || ""),
        label:       String(indicator?.label || ""),
        description: String(indicator?.description || ""),
        placement:   String(indicator?.placement || "panel"),
        series: Array.isArray(indicator?.series)
          ? indicator.series.map((series) => ({
            key:    String(series?.key || ""),
            label:  String(series?.label || ""),
            color:  String(series?.color || "#60a5fa"),
            dash:   String(series?.dash || "solid"),
            values: normalizeSeries(series?.values),
          }))
          : [],
        thresholds: Array.isArray(indicator?.thresholds)
          ? indicator.thresholds.map((threshold) => ({
            label: String(threshold?.label || ""),
            value: threshold?.value == null || Number.isNaN(Number(threshold.value)) ? null : Number(threshold.value),
            color: String(threshold?.color || "#94a3b8"),
            dash:  String(threshold?.dash || "dot"),
          })).filter((threshold) => threshold.value !== null)
          : [],
      }))
      : [];
  }

  function filterPreviewPayload(payload, indicatorFilter) {
    if (!payload || !Array.isArray(payload.indicators)) return payload;
    if (!Array.isArray(indicatorFilter) || indicatorFilter.length === 0) return payload;
    const allowed = new Set(indicatorFilter.map((value) => String(value || "").trim()).filter(Boolean));
    return { ...payload, indicators: payload.indicators.filter((indicator) => allowed.has(String(indicator.key || "").trim())) };
  }

  function aggregatePayload(payload, targetInterval) {
    const targetKey = canonicalIntervalKey(targetInterval);
    if (!payload?.dates?.length || payload.interval === targetKey) return payload;
    const buckets = []; const bucketByKey = new Map();
    payload.dates.forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      if (!parsedDate) return;
      const bucketDate = floorToBucket(parsedDate, targetKey);
      const bucketKey  = bucketDate.toISOString();
      let bucket       = bucketByKey.get(bucketKey);
      if (!bucket) {
        bucket = { date: bucketDate, label: formatBucketLabel(bucketDate, targetKey), market: { open: null, high: null, low: null, close: null, volume: 0 }, equity: { strategy: null, gross: null, benchmark: null }, drawdown: null };
        bucketByKey.set(bucketKey, bucket);
        buckets.push(bucket);
      }
      updateBucket(bucket, payload, index);
    });
    buckets.sort((a, b) => a.date.getTime() - b.date.getTime());
    return {
      focus:       payload.focus,
      interval:    targetKey,
      dates:       buckets.map((bucket) => bucket.label),
      parsedDates: buckets.map((bucket) => bucket.date),
      market: {
        has_candles: payload.market?.has_candles,
        open:   buckets.map((bucket) => bucket.market.open),
        high:   buckets.map((bucket) => bucket.market.high),
        low:    buckets.map((bucket) => bucket.market.low),
        close:  buckets.map((bucket) => bucket.market.close),
        volume: buckets.map((bucket) => bucket.market.volume || null),
      },
      equity: {
        strategy:  buckets.map((bucket) => bucket.equity.strategy),
        gross:     buckets.map((bucket) => bucket.equity.gross),
        benchmark: buckets.map((bucket) => bucket.equity.benchmark),
      },
      drawdown_pct:  buckets.map((bucket) => bucket.drawdown),
      entry_markers: aggregateMarkers(payload.entry_markers, targetKey),
      exit_markers:  aggregateMarkers(payload.exit_markers, targetKey),
      indicators:    aggregateIndicators(payload.indicators, payload.dates, targetKey),
    };
  }

  function updateBucket(bucket, payload, index) {
    const open      = val(payload.market?.open, index);
    const high      = val(payload.market?.high, index);
    const low       = val(payload.market?.low,  index);
    const close     = val(payload.market?.close, index);
    const volume    = val(payload.market?.volume, index);
    const strategy  = val(payload.equity?.strategy,  index);
    const gross     = val(payload.equity?.gross,      index);
    const benchmark = val(payload.equity?.benchmark,  index);
    const drawdown  = val(payload.drawdown_pct,       index);

    if (bucket.market.open === null) bucket.market.open = open ?? close;
    if (high  !== null) bucket.market.high = bucket.market.high === null ? high  : Math.max(bucket.market.high, high);
    if (low   !== null) bucket.market.low  = bucket.market.low  === null ? low   : Math.min(bucket.market.low,  low);
    if (close !== null) bucket.market.close = close;
    if (volume !== null) bucket.market.volume += volume;
    if (strategy  !== null) bucket.equity.strategy  = strategy;
    if (gross     !== null) bucket.equity.gross     = gross;
    if (benchmark !== null) bucket.equity.benchmark = benchmark;
    if (drawdown  !== null) bucket.drawdown = bucket.drawdown === null ? drawdown : Math.min(bucket.drawdown, drawdown);
  }

  function aggregateMarkers(markers, targetInterval) {
    const aggregated = { x: [], y: [], text: [] };
    const targetKey  = canonicalIntervalKey(targetInterval);
    markers?.x?.forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      const price      = markers?.y?.[index];
      if (!parsedDate || price == null) return;
      const bucketDate = floorToBucket(parsedDate, targetKey);
      aggregated.x.push(formatBucketLabel(bucketDate, targetKey));
      aggregated.y.push(Number(price));
      aggregated.text.push(String(markers?.text?.[index] || ""));
    });
    return aggregated;
  }

  function aggregateIndicators(indicators, dates, targetInterval) {
    if (!Array.isArray(indicators) || indicators.length === 0) return [];
    return indicators.map((indicator) => ({
      ...indicator,
      series: Array.isArray(indicator.series)
        ? indicator.series.map((series) => ({ ...series, values: aggregateIndicatorSeries(series.values, dates, targetInterval) }))
        : [],
    }));
  }

  function aggregateIndicatorSeries(values, dates, targetInterval) {
    if (!Array.isArray(values) || values.length === 0) return [];
    const bucketByKey = new Map();
    (Array.isArray(dates) ? dates : []).forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      if (!parsedDate) return;
      const bucketDate = floorToBucket(parsedDate, targetInterval);
      bucketByKey.set(bucketDate.toISOString(), val(values, index));
    });
    return Array.from(bucketByKey.entries()).sort((a, b) => a[0].localeCompare(b[0])).map(([, bucketValue]) => bucketValue);
  }

  function floorToBucket(dateValue, intervalKey) {
    const definition = intervalDefinitions[canonicalIntervalKey(intervalKey)] || intervalDefinitions["1d"];
    if (definition.unit === "minute") {
      const totalMinutes  = (dateValue.getUTCHours() * 60) + dateValue.getUTCMinutes();
      const bucketMinutes = Math.floor(totalMinutes / definition.minutes) * definition.minutes;
      return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), dateValue.getUTCDate(), Math.floor(bucketMinutes / 60), bucketMinutes % 60, 0));
    }
    if (definition.unit === "day") return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), dateValue.getUTCDate()));
    if (definition.unit === "week") {
      const monday = new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), dateValue.getUTCDate()));
      const delta  = (monday.getUTCDay() + 6) % 7;
      monday.setUTCDate(monday.getUTCDate() - delta);
      return monday;
    }
    return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), 1));
  }

  function formatBucketLabel(dateValue, intervalKey) {
    const definition = intervalDefinitions[canonicalIntervalKey(intervalKey)] || intervalDefinitions["1d"];
    if (definition.unit === "minute") {
      return `${dateValue.getUTCFullYear()}-${pad(dateValue.getUTCMonth() + 1)}-${pad(dateValue.getUTCDate())} ${pad(dateValue.getUTCHours())}:${pad(dateValue.getUTCMinutes())}`;
    }
    return `${dateValue.getUTCFullYear()}-${pad(dateValue.getUTCMonth() + 1)}-${pad(dateValue.getUTCDate())}`;
  }

  function pad(value) { return String(value).padStart(2, "0"); }

  // ─── Preview indicator layer buttons ─────────────────────────────────────────
  function updatePreviewLayerButtons() {
    document.querySelectorAll("[data-preview-layer]").forEach((button) => {
      const key       = button.dataset.traceToggle || "";
      const available = Boolean(state.previewAvailable[key]);
      button.hidden   = !available;
      if (available) button.classList.toggle("is-on", Boolean(state.visible[key]));
    });
  }

  function syncPreviewAvailability() {
    const previewData = activePreviewPayload();
    state.previewAvailable.preview_entry    = hasValues(previewData?.entry_markers?.x);
    state.previewAvailable.preview_exit     = hasValues(previewData?.exit_markers?.x);
    state.previewAvailable.preview_strategy = hasValues(previewData?.equity?.strategy);
    state.previewAvailable.preview_drawdown = hasValues(previewData?.drawdown_pct);
    Object.keys(state.previewAvailable).forEach((key) => {
      if (key === "preview_strategy" || key === "preview_drawdown") { state.visible[key] = false; return; }
      state.visible[key] = state.previewAvailable[key];
    });
  }

  function updateIndicatorSummary() {
    const activeCount      = Object.entries(state.visible).filter(([, enabled]) => enabled).length;
    const liveIndicatorCount = Array.isArray(activePreviewPayload()?.indicators) ? activePreviewPayload().indicators.length : 0;
    const totalCount       = activeCount + liveIndicatorCount;
    if (dom.indicatorCount) dom.indicatorCount.textContent = String(totalCount);
    $$("[data-chart-indicator-open]").forEach((button) => button.classList.toggle("is-on", totalCount > 0));
  }

  // ─── Modale indicatori ────────────────────────────────────────────────────────
  function openIndicatorModal() {
    if (!dom.indicatorModal) return;
    dom.indicatorModal.hidden = false;
    document.body.classList.add("chart-indicator-modal-open");
    filterIndicatorCatalog();
    window.requestAnimationFrame(() => { dom.indicatorSearch?.focus(); });
  }

  function closeIndicatorModal() {
    if (!dom.indicatorModal) return;
    dom.indicatorModal.hidden = true;
    document.body.classList.remove("chart-indicator-modal-open");
    if (dom.indicatorSearch) dom.indicatorSearch.value = "";
    filterIndicatorCatalog();
  }

  function filterIndicatorCatalog() {
    const query  = String(dom.indicatorSearch?.value || "").trim().toLowerCase();
    let visibleItems = 0;
    $$("[data-chart-indicator-item]").forEach((item) => {
      const available  = !item.hidden;
      const haystack   = String(item.dataset.chartIndicatorSearch || item.textContent || "").toLowerCase();
      const matches    = !query || haystack.includes(query);
      const isHidden   = available && !matches;
      item.classList.toggle("is-search-hidden", isHidden);
      if (available && matches) visibleItems += 1;
    });
    if (dom.indicatorEmpty) dom.indicatorEmpty.hidden = visibleItems !== 0;
  }

  // ─── Keyboard ─────────────────────────────────────────────────────────────────
  function onKeydown(event) {
    if (event.key !== "Escape") return;
    if (dom.tradeDetailModal?.hidden === false) { closeTradeDetailModal(); return; }
    if (dom.indicatorModal?.hidden === false)   { closeIndicatorModal();   return; }
    if (dom.signalPopup?.hidden === false)       hideSignalPopup();
  }

  // ─── Signal popup ─────────────────────────────────────────────────────────────
  function showSignalPopup(point) {
    if (!dom.signalPopup || !dom.signalPopupEntry || !dom.signalPopupExit) return;
    const payload = buildSignalPopupPayload(point);
    const hasEntry = Boolean(String(payload.entryText || "").trim());
    const hasExit  = Boolean(String(payload.exitText  || "").trim());
    if (!hasEntry && !hasExit) return;

    state.selectedTradeIndex = Number.isInteger(payload.tradeIndex) ? payload.tradeIndex : -1;
    signalPopupPanels = { entry: String(payload.entryText || ""), exit: String(payload.exitText || "") };
    dom.signalPopup.hidden = false;
    if (dom.signalPopupTitle) dom.signalPopupTitle.textContent = payload.title;
    dom.signalPopupEntry.textContent = signalPopupPanels.entry || "Dettaglio ingresso non disponibile.";
    dom.signalPopupExit.textContent  = signalPopupPanels.exit  || "Dettaglio uscita non disponibile.";
    setSignalPopupTab(payload.activeTab || "entry", { force: true });
    if (dom.signalPopupStatus) dom.signalPopupStatus.textContent = payload.status;
    positionSignalPopup(point);
    updateAllMarkers();
  }

  function hideSignalPopup() {
    state.selectedTradeIndex = -1;
    signalPopupPanels = { entry: "", exit: "" };
    signalPopupText   = "";
    if (dom.signalPopup) dom.signalPopup.hidden = true;
    setSignalPopupTab("entry", { force: true });
    updateAllMarkers();
  }

  function buildSignalPopupPayload(point) {
    const traceName  = String(point?.data?.name || "Segnale");
    const fallbackText = extractSignalPopupText(point);
    const signalSide = traceName.toLowerCase().includes("uscita") ? "exit" : "entry";
    const signalTime = extractSignalTimestamp(point, fallbackText);
    const tradeIndex = resolveTradeIndex(signalSide, signalTime);

    if (tradeIndex < 0 || !tradeRows[tradeIndex]) {
      const isPreview = traceName.toLowerCase().includes("preview");
      return {
        title:      traceName,
        entryText:  signalSide === "entry" ? (fallbackText || "Dettaglio ingresso non disponibile.") : "Ingresso collegato non disponibile.",
        exitText:   signalSide === "exit"  ? (fallbackText || "Dettaglio uscita non disponibile.")   : "Uscita collegata non disponibile.",
        activeTab:  signalSide,
        tradeIndex: -1,
        status: isPreview
          ? "Segnale preview: l'abbinamento ingresso/uscita è disponibile solo quando il trade esiste nel report base."
          : "Clicca un marker Ingresso/Uscita del report per vedere la coppia completa.",
      };
    }

    const trade    = tradeRows[tradeIndex];
    const sequence = Number.isFinite(Number(trade.sequence)) ? Number(trade.sequence) : tradeIndex + 1;
    const tradeHeader = `Trade #${sequence} (${String(trade.status_label || "-")})`;
    const entryBlock  = String(trade.entry_detail_text || "").trim() || "INGRESSO | Dettaglio non disponibile.";
    const exitBlock   = String(trade.exit_detail_text  || "").trim() || "USCITA | Dettaglio non disponibile.";
    const isOpenTrade = !String(trade.exit_raw || "").trim();
    return {
      title:      isOpenTrade ? "Ingresso (trade aperto)" : "Ingresso + Uscita",
      entryText:  `${tradeHeader}\n\n${entryBlock}`,
      exitText:   `${tradeHeader}\n\n${exitBlock}`,
      activeTab:  signalSide,
      tradeIndex,
      status: isOpenTrade
        ? "Trade ancora aperto: la sezione EXIT viene aggiornata quando arriva la chiusura."
        : "Coppia completa mostrata: stessa operazione (entry + exit).",
    };
  }

  function setSignalPopupTab(nextTab, options = {}) {
    const tab   = nextTab === "exit" ? "exit" : "entry";
    const force = Boolean(options.force);
    if (!force && signalPopupTab === tab) return;
    signalPopupTab = tab;
    dom.signalPopupTabs.forEach((button) => {
      const isActive = (button.dataset.signalPopupTab || "entry") === tab;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    if (dom.signalPopupEntry) dom.signalPopupEntry.hidden = tab !== "entry";
    if (dom.signalPopupExit)  dom.signalPopupExit.hidden  = tab !== "exit";
    signalPopupText = tab === "exit"
      ? (signalPopupPanels.exit   || signalPopupPanels.entry || "")
      : (signalPopupPanels.entry  || signalPopupPanels.exit  || "");
  }

  function extractSignalPopupText(point) {
    const hoverText = point?.hovertext;
    if (typeof hoverText === "string" && hoverText.trim()) return hoverText.trim();
    const traceHoverText = point?.data?.hovertext;
    if (Array.isArray(traceHoverText) && traceHoverText[point.pointNumber]) return String(traceHoverText[point.pointNumber] || "").trim();
    return "";
  }

  function extractSignalTimestamp(point, fallbackText = "") {
    const lines = String(fallbackText || "").split("\n");
    const firstLine = String(lines[0] || "").trim();
    const match = firstLine.match(/^(?:ENTRY|EXIT)\s*\|\s*(.+)$/i);
    if (match && match[1]) return normalizeSignalTimestamp(match[1]);
    return normalizeSignalTimestamp(point?.x);
  }

  function resolveTradeIndex(signalSide, signalTime) {
    if (!signalTime) return -1;
    if (signalSide === "exit") return tradeIndexByExitRaw.has(signalTime)  ? Number(tradeIndexByExitRaw.get(signalTime))  : -1;
    return                          tradeIndexByEntryRaw.has(signalTime) ? Number(tradeIndexByEntryRaw.get(signalTime)) : -1;
  }

  function normalizeSignalTimestamp(rawValue) {
    const raw = String(rawValue || "").trim();
    if (!raw) return "";
    const match = raw.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2})?)?$/);
    if (!match) return raw;
    const [, datePart, hours = "", minutes = ""] = match;
    return hours ? `${datePart} ${hours}:${minutes}` : datePart;
  }

  function positionSignalPopup(point) {
    if (!dom.signalPopupHost || !dom.signalPopup) return;
    const hostRect   = dom.signalPopupHost.getBoundingClientRect();
    const popupRect  = dom.signalPopup.getBoundingClientRect();
    const event      = point?.event;
    const anchorX    = Number(event?.clientX || (hostRect.left + hostRect.width - 24));
    const anchorY    = Number(event?.clientY || (hostRect.top + 24));
    const padding    = 14;
    const preferred  = 18;
    const maxLeft    = Math.max(hostRect.width  - popupRect.width  - padding, padding);
    const maxTop     = Math.max(hostRect.height - popupRect.height - padding, padding);

    let left = anchorX - hostRect.left + preferred;
    let top  = anchorY - hostRect.top  - Math.min(popupRect.height * 0.3, 54);

    if ((left + popupRect.width + padding) > hostRect.width) left = anchorX - hostRect.left - popupRect.width - preferred;
    if (left < padding) left = padding;
    if (top  < padding) top  = padding;
    if (top  > maxTop)  top  = maxTop;

    dom.signalPopup.style.left = `${Math.min(left, maxLeft)}px`;
    dom.signalPopup.style.top  = `${Math.min(top,  maxTop)}px`;
  }

  async function copySignalPopupText() {
    if (!signalPopupText) return;
    const copyText = signalPopupText;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(copyText);
      } else {
        const helper = document.createElement("textarea");
        helper.value = copyText;
        helper.setAttribute("readonly", "readonly");
        helper.style.position = "absolute";
        helper.style.left     = "-9999px";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      if (dom.signalPopupStatus) dom.signalPopupStatus.textContent = "Copiato negli appunti.";
    } catch {
      if (dom.signalPopupStatus) dom.signalPopupStatus.textContent = "Copia non riuscita. Puoi comunque selezionare il testo.";
    }
  }

  // ─── Trade tape ───────────────────────────────────────────────────────────────
  function moveTradePage(delta) {
    const nextPage = Math.min(Math.max(tradePage + delta, 0), tradePageCount() - 1);
    if (nextPage === tradePage) return;
    tradePage = nextPage;
    renderTradeTape();
  }

  function tradePageCount() { return Math.max(Math.ceil(tradeRows.length / tradePageSize), 1); }

  function renderTradeTape() {
    if (!dom.tradeTable) return;
    if (!Array.isArray(tradeRows) || tradeRows.length === 0) {
      if (dom.tradeControls) dom.tradeControls.hidden = true;
      dom.tradeTable.innerHTML = `<div class="empty-state"><p>Nessun trade disponibile per questo chart.</p></div>`;
      return;
    }
    const totalPages  = tradePageCount();
    tradePage         = Math.min(Math.max(tradePage, 0), totalPages - 1);
    const start       = tradePage * tradePageSize;
    const end         = Math.min(start + tradePageSize, tradeRows.length);
    const visibleRows = tradeRows.slice(start, end);

    if (dom.tradeControls)  dom.tradeControls.hidden  = false;
    if (dom.tradeSummary)   dom.tradeSummary.textContent    = `Finestra ${start + 1}-${end} di ${tradeRows.length} operazioni.`;
    if (dom.tradePageLabel) dom.tradePageLabel.textContent  = `Pagina ${tradePage + 1} / ${totalPages}`;
    if (dom.tradePrev)      dom.tradePrev.disabled          = tradePage === 0;
    if (dom.tradeNext)      dom.tradeNext.disabled          = tradePage >= totalPages - 1;

    dom.tradeTable.innerHTML = `
      <div class="table-wrap trade-table-wrap">
        <table class="trade-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Esito</th>
              <th>Entrata</th>
              <th>Uscita</th>
              <th>PnL</th>
              <th>Durata</th>
            </tr>
          </thead>
          <tbody>
            ${visibleRows.map((trade, index) => `
              <tr class="chart-trade-row" tabindex="0" data-chart-trade-index="${start + index}">
                <td class="trade-sequence-cell">${escapeHtml(String(trade.sequence ?? ""))}</td>
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

  function onTradeTableClick(event) {
    const row = event.target instanceof Element ? event.target.closest("[data-chart-trade-index]") : null;
    if (!row) return;
    openTradeDetailModal(Number(row.getAttribute("data-chart-trade-index")));
  }

  function onTradeTableKeydown(event) {
    if (!(event.target instanceof Element)) return;
    const row = event.target.closest("[data-chart-trade-index]");
    if (!row) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openTradeDetailModal(Number(row.getAttribute("data-chart-trade-index")));
  }

  function openTradeDetailModal(index) {
    const trade = tradeRows[index];
    if (!trade || !dom.tradeDetailModal) return;
    if (dom.tradeDetailTitle) dom.tradeDetailTitle.textContent = trade.detail_title || `Operazione #${trade.sequence || index + 1}`;
    if (dom.tradeDetailSummary) {
      dom.tradeDetailSummary.innerHTML = `
        <article class="terminal-metric-card"><p>Esito</p><strong>${escapeHtml(trade.status_label || "-")}</strong><span>Trade #${escapeHtml(String(trade.sequence ?? index + 1))}</span></article>
        <article class="terminal-metric-card"><p>Entrata</p><strong>${escapeHtml(trade.entry_price_display || "-")}</strong><span>${escapeHtml(joinTradeTimestamp(trade.entry_date_display, trade.entry_time_display))}</span></article>
        <article class="terminal-metric-card"><p>Uscita</p><strong>${escapeHtml(trade.exit_price_display || "-")}</strong><span>${escapeHtml(joinTradeTimestamp(trade.exit_date_display, trade.exit_time_display))}</span></article>
        <article class="terminal-metric-card"><p>PnL</p><strong>${escapeHtml(trade.pnl_display || "-")}</strong><span>Movimento della posizione</span></article>
        <article class="terminal-metric-card"><p>Durata</p><strong>${escapeHtml(trade.duration_display || "-")}</strong><span>Tempo in posizione</span></article>
      `;
    }
    if (dom.tradeDetailEntry) dom.tradeDetailEntry.textContent = trade.entry_detail_text || "Dettaglio di entrata non disponibile per questa operazione.";
    if (dom.tradeDetailExit)  dom.tradeDetailExit.textContent  = trade.exit_detail_text  || "Dettaglio di uscita non disponibile per questa operazione.";
    dom.tradeDetailModal.hidden = false;
  }

  function closeTradeDetailModal() {
    if (!dom.tradeDetailModal) return;
    dom.tradeDetailModal.hidden = true;
  }

  function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  function joinTradeTimestamp(datePart, timePart) {
    const parts = [datePart, timePart].map((value) => String(value || "").trim()).filter(Boolean);
    return parts.join(" · ") || "-";
  }

  // ─── Preview API (richiamata da chart_strategy_lab.js) ───────────────────────
  function applyPreview(payload, previewLabel = "Preview live") {
    hideSignalPopup();
    resetViewportLock();
    state.previewRawPayload = normalizePayload(payload || {}, rawPayload.interval);
    syncPreviewAvailability();
    setStatus("preview", previewLabel);
    rerenderChart();
  }

  function setPreviewIndicatorFilter(indicatorKeys) {
    state.previewIndicatorFilter = Array.isArray(indicatorKeys) ? [...indicatorKeys] : null;
    if (!state.previewRawPayload) return;
    resetViewportLock();
    syncPreviewAvailability();
    rerenderChart();
  }

  function clearPreview() {
    hideSignalPopup();
    resetViewportLock();
    state.previewRawPayload      = null;
    state.previewIndicatorFilter = null;
    Object.keys(state.previewAvailable).forEach((key) => {
      state.previewAvailable[key] = false;
      state.visible[key]          = false;
    });
    setStatus("preview", baselinePreviewLabel);
    rerenderChart();
  }

  window.tradingBotChartTerminal = { applyPreview, clearPreview, setPreviewIndicatorFilter };

  // ─── Clamp ────────────────────────────────────────────────────────────────────
  function clamp(reset = false) {
    state.start    = Math.min(Math.max(state.start, 0), maxStart());
    if (reset) state.progress = state.mode === "replay" ? 0 : segLen() - 1;
    state.progress = Math.min(Math.max(state.progress, 0), segLen() - 1);
    if (state.mode === "all") state.progress = segLen() - 1;
    syncInputs();
  }
})();
