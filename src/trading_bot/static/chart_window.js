(() => {
  const dataNode = document.getElementById("chart-window-data");
  const tradeTableDataNode = document.getElementById("chart-trade-table-data");
  const root = document.getElementById("interactive-chart-root");
  if (!dataNode || !root || typeof Plotly === "undefined") {
    const diagnostics = {
      dataNode: Boolean(dataNode),
      root: Boolean(root),
      plotlyLoaded: typeof Plotly !== "undefined",
      plotlyVersion: typeof Plotly !== "undefined" ? Plotly.version : null,
    };
    console.error("Chart initialization failed", diagnostics);
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

  const intervalDefinitions = {
    "1m": { key: "1m", label: "1m", unit: "minute", minutes: 1 },
    "2m": { key: "2m", label: "2m", unit: "minute", minutes: 2 },
    "5m": { key: "5m", label: "5m", unit: "minute", minutes: 5 },
    "15m": { key: "15m", label: "15m", unit: "minute", minutes: 15 },
    "30m": { key: "30m", label: "30m", unit: "minute", minutes: 30 },
    "1h": { key: "1h", label: "1h", unit: "minute", minutes: 60 },
    "4h": { key: "4h", label: "4h", unit: "minute", minutes: 240 },
    "90m": { key: "90m", label: "90m", unit: "minute", minutes: 90 },
    "1d": { key: "1d", label: "1g", unit: "day", minutes: 24 * 60 },
    "1wk": { key: "1wk", label: "1w", unit: "week", minutes: 7 * 24 * 60 },
    "1mo": { key: "1mo", label: "1mo", unit: "month", minutes: 30 * 24 * 60 },
  };
  const candleControlOrder = ["1m", "2m", "5m", "30m", "1h", "4h", "1d", "1wk"];
  const rawPayload = normalizePayload(JSON.parse(dataNode.textContent || "{}"));
  const rawTradeRows = JSON.parse(tradeTableDataNode?.textContent || "[]");
  const tradeRows = Array.isArray(rawTradeRows) ? rawTradeRows : [];
  const tradeIndexByEntryRaw = new Map();
  const tradeIndexByExitRaw = new Map();
  tradeRows.forEach((trade, index) => {
    const entryKey = normalizeSignalTimestamp(trade?.entry_raw);
    const exitKey = normalizeSignalTimestamp(trade?.exit_raw);
    if (entryKey) tradeIndexByEntryRaw.set(entryKey, index);
    if (exitKey) tradeIndexByExitRaw.set(exitKey, index);
  });
  if (!rawPayload.dates.length) {
    console.warn("Chart payload has no dates", rawPayload);
    return;
  }
  console.debug("Chart payload summary", {
    interval: rawPayload.interval,
    dates: rawPayload.dates.length,
    hasCandles: rawPayload.market?.has_candles,
    markers: {
      entries: rawPayload.entry_markers?.x?.length,
      exits: rawPayload.exit_markers?.x?.length,
    },
  });

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

  const focusProfiles = {
    all: { price: 5.2, indicator: 1.55, equity: 2.05, drawdown: 1.25 },
    price: { price: 7.4, indicator: 1.6, equity: 0.95, drawdown: 0.65 },
    equity: { price: 4.4, indicator: 1.45, equity: 3.1, drawdown: 0.75 },
    drawdown: { price: 3.9, indicator: 1.35, equity: 2.35, drawdown: 1.9 },
  };
  const candleControlOptions = buildSupportedCandleOptions(rawPayload.interval);
  const supportedCandleOptions = candleControlOptions.filter((option) => option.enabled);
  const fallbackCandleOption = intervalDefinitions[canonicalIntervalKey(rawPayload.interval)] || intervalDefinitions["1d"];
  const datasetOptions = supportedCandleOptions.length ? supportedCandleOptions : [{ ...fallbackCandleOption, enabled: true }];
  const datasetCatalog = new Map(
    datasetOptions.map((option) => [
      option.key,
      option.key === rawPayload.interval ? rawPayload : aggregatePayload(rawPayload, option.key),
    ]),
  );
  const defaultCandle = datasetCatalog.has(rawPayload.interval)
    ? rawPayload.interval
    : datasetOptions[0]?.key || rawPayload.interval;
  const initialDataset = datasetCatalog.get(defaultCandle) || rawPayload;
  const initialTotal = initialDataset.dates.length;
  const traceIndexes = {
    price: 0,
    volume: 1,
    entry: 2,
    exit: 3,
    strategy: 4,
    benchmark: 5,
    gross: 6,
    drawdown: 7,
    preview_entry: 8,
    preview_exit: 9,
    preview_strategy: 10,
    preview_drawdown: 11,
    selected_entry: 12,
    selected_exit: 13,
  };
  const state = {
    focus: focusProfiles[rawPayload.focus] ? rawPayload.focus : "price",
    candle: defaultCandle,
    drag: "pan",
    timer: null,
    mode: "all",
    start: 0,
    seg: "all",
    win: hasWindowControl ? coerceVisibleWindowForInterval(defaultCandle, parseLen(dom.win.value)) : "all",
    step: 1,
    speed: 6,
    progress: Math.max(initialTotal - 1, 0),
    visible: {
      price: true,
      volume: false,
      entry: hasValues(rawPayload.entry_markers?.x),
      exit: hasValues(rawPayload.exit_markers?.x),
      strategy: false,
      benchmark: false,
      gross: false,
      drawdown: false,
      preview_entry: false,
      preview_exit: false,
      preview_strategy: false,
      preview_drawdown: false,
    },
    previewRawPayload: null,
    previewIndicatorFilter: null,
    previewAvailable: {
      preview_entry: false,
      preview_exit: false,
      preview_strategy: false,
      preview_drawdown: false,
    },
    axisDrag: null,
    isProgrammaticRelayout: false,
    viewport: {
      locked: false,
      xRange: null,
      yRange: null,
      y2Range: null,
      y3Range: null,
    },
    selectedTradeIndex: -1,
  };
  let signalPopupText = "";
  let signalPopupTab = "entry";
  let signalPopupPanels = { entry: "", exit: "" };
  let tradePage = 0;

  renderCandleControls();
  syncInputs();
  renderTradeTape();

  function initializeChart() {
    const rootRect = root.getBoundingClientRect();
    console.info("Chart window starting", {
      plotly: { version: Plotly?.version },
      payload: {
        interval: rawPayload.interval,
        dates: rawPayload.dates.length,
        hasCandles: rawPayload.market?.has_candles,
        markers: {
          entries: rawPayload.entry_markers?.x?.length || 0,
          exits: rawPayload.exit_markers?.x?.length || 0,
        },
      },
      rootRect,
    });

    if (rootRect.width === 0 || rootRect.height === 0) {
      window.setTimeout(initializeChart, 50);
      return;
    }

    Plotly.newPlot(root, buildTraces(), buildLayout(), buildConfig())
      .then(() => {
        console.info("Plotly rendered chart", {
          xaxis: rootRect.width,
          yaxis: rootRect.height,
        });
        bind();
        applyFocus();
        applyReplay();
        syncUi();
        window.requestAnimationFrame(() => Plotly.Plots.resize(root));
        window.setTimeout(() => {
          if (root && root._fullLayout) {
            Plotly.Plots.resize(root);
          }
        }, 120);
      })
      .catch((error) => {
        console.error("Plotly failed to render chart", error);
        if (root) {
          root.innerHTML = `
            <div class="chart-error">
              <strong>Errore durante il rendering del grafico</strong>
              <p>Controlla la console per i dettagli.</p>
              <pre>${String(error)}</pre>
            </div>
          `;
        }
      });
  }

  if (root.getBoundingClientRect().width > 0 && root.getBoundingClientRect().height > 0) {
    initializeChart();
  } else {
    window.requestAnimationFrame(initializeChart);
  }

  function bind() {
    $$("[data-focus-view]").forEach((b) => b.addEventListener("click", () => {
      const nextFocus = b.dataset.focusView || "all";
      if (nextFocus === state.focus) {
        syncUi();
        return;
      }
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
        const requiresLayoutRefresh = ["strategy", "benchmark", "gross", "drawdown", "preview_strategy", "preview_drawdown"].includes(key);
        if (requiresLayoutRefresh) {
          resetViewportLock();
          rerenderChart();
          return;
        }
        Plotly.restyle(root, { visible: state.visible[key] ? true : "legendonly" }, [traceIndexes[key]]);
        syncUi();
      });
    });
    $$("[data-playback-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.playbackMode || "all")));
    $$("[data-playback-action]").forEach((b) => b.addEventListener("click", () => playbackAction(b.dataset.playbackAction || "")));
    dom.start?.addEventListener("input", () => { state.start = Math.max(Number(dom.start.value) - 1, 0); clamp(true); applyReplay(); });
    dom.seg?.addEventListener("change", () => { state.seg = parseLen(dom.seg.value); clamp(true); applyReplay(); });
    dom.win?.addEventListener("change", () => { state.win = parseLen(dom.win.value); clamp(); applyReplay(); });
    dom.step?.addEventListener("change", () => { state.step = Math.max(Number(dom.step.value) || 1, 1); syncUi(); });
    dom.speed?.addEventListener("input", () => { state.speed = Math.max(Number(dom.speed.value) || 1, 1); if (state.timer) restartTimer(); syncUi(); });
    dom.progress?.addEventListener("input", () => { stopTimer(); setMode("replay"); state.progress = Math.max(Number(dom.progress.value) - 1, 0); clamp(); applyReplay(); });
    dom.indicatorSearch?.addEventListener("input", filterIndicatorCatalog);
    dom.signalPopupCopy?.addEventListener("click", copySignalPopupText);
    dom.signalPopupTabs.forEach((button) => {
      button.addEventListener("click", () => {
        setSignalPopupTab(button.dataset.signalPopupTab || "entry");
      });
    });
    dom.tradePrev?.addEventListener("click", () => moveTradePage(-1));
    dom.tradeNext?.addEventListener("click", () => moveTradePage(1));
    dom.tradeTable?.addEventListener("click", onTradeTableClick);
    dom.tradeTable?.addEventListener("keydown", onTradeTableKeydown);
    $$("[data-chart-trade-detail-close]").forEach((button) => button.addEventListener("click", closeTradeDetailModal));
    document.addEventListener("keydown", onKeydown);
    window.addEventListener("resize", () => Plotly.Plots.resize(root));
    root.on?.("plotly_relayout", onPlotlyRelayout);
    root.on?.("plotly_click", onPlotlyClick);
  }

  function buildTraces() {
    const data = activePayload();
    const previewData = activePreviewPayload();
    const bounds = resolveVisibleBounds(data);
    const viewData = slicePayloadWindow(data, bounds.left, bounds.right);
    const viewPreview = previewData ? slicePayloadWindow(previewData, bounds.left, bounds.right) : null;
    const viewStartLabel = viewData.dates[0];
    const viewEndLabel = viewData.dates[viewData.dates.length - 1];
    const entryMarkers = sliceMarkersByWindow(data.entry_markers, viewStartLabel, viewEndLabel);
    const exitMarkers = sliceMarkersByWindow(data.exit_markers, viewStartLabel, viewEndLabel);
    const previewEntryMarkers = sliceMarkersByWindow(viewPreview?.entry_markers, viewStartLabel, viewEndLabel);
    const previewExitMarkers = sliceMarkersByWindow(viewPreview?.exit_markers, viewStartLabel, viewEndLabel);
    const chartStructure = buildChartStructure(previewData);
    const selectedOverlay = buildSelectedTradeOverlay(data);
    const showPreviewIndicatorsOnChart = false;
    const minuteInterval = intervalToMinutes(viewData.interval);
    const denseIntraday = Number.isFinite(minuteInterval) && minuteInterval <= 5;
    const candleLineWidth = denseIntraday ? 3.2 : 1.2;
    const candleWhiskerWidth = denseIntraday ? 0.95 : 0.35;
    const candles = viewData.market?.has_candles && hasValues(viewData.market?.open) && hasValues(viewData.market?.high) && hasValues(viewData.market?.low);
    const denseGuideTrace = denseIntraday
      ? {
        type: "scatter",
        mode: "lines",
        name: "Prezzo guida",
        x: viewData.dates,
        y: viewData.market?.close || [],
        hoverinfo: "skip",
        line: { color: "rgba(125,211,252,0.58)", width: 1.35 },
        xaxis: "x",
        yaxis: "y",
      }
      : null;
    return [
      candles
        ? { type: "candlestick", name: "Prezzo", visible: true, x: viewData.dates, open: viewData.market.open, high: viewData.market.high, low: viewData.market.low, close: viewData.market.close, increasing: { line: { color: "#26d0a8", width: candleLineWidth }, fillcolor: "rgba(38,208,168,0.55)" }, decreasing: { line: { color: "#ff5f73", width: candleLineWidth }, fillcolor: "rgba(255,95,115,0.55)" }, whiskerwidth: candleWhiskerWidth, hovertemplate: "O %{open:.4f}<br>H %{high:.4f}<br>L %{low:.4f}<br>C %{close:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" }
        : { type: "scatter", mode: "lines", name: "Prezzo", visible: true, x: viewData.dates, y: viewData.market?.close || [], line: { color: "#7dd3fc", width: 2.3 }, hovertemplate: "Close %{y:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" },
      { type: "bar", name: "Volume", x: viewData.dates, y: viewData.market?.volume || [], marker: { color: volumeColors(viewData) }, opacity: 0.45, visible: state.visible.volume, hovertemplate: "Volume %{y:,.0f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y4" },
      { type: "scatter", mode: "markers", name: "Entry", x: entryMarkers.x, y: entryMarkers.y, hovertext: entryMarkers.text, visible: state.visible.entry, hovertemplate: "Entry<br>%{x}<br>Clicca per aprire i dettagli trade<extra></extra>", cliponaxis: false, marker: { color: "#21c98b", size: 14, symbol: "triangle-up", line: { width: 2, color: "#f8fffc" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers", name: "Exit", x: exitMarkers.x, y: exitMarkers.y, hovertext: exitMarkers.text, visible: state.visible.exit, hovertemplate: "Exit<br>%{x}<br>Clicca per aprire i dettagli trade<extra></extra>", cliponaxis: false, marker: { color: "#ff5f73", size: 14, symbol: "triangle-down", line: { width: 2, color: "#fff6f7" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Strategia", x: viewData.dates, y: viewData.equity?.strategy || [], visible: state.visible.strategy, line: { color: "#4ade80", width: 2.5 }, hovertemplate: "Strategia %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Buy & hold", x: viewData.dates, y: viewData.equity?.benchmark || [], visible: state.visible.benchmark, line: { color: "#60a5fa", width: 2.1 }, hovertemplate: "Buy & hold %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Senza fee", x: viewData.dates, y: viewData.equity?.gross || [], visible: state.visible.gross, line: { color: "#fbbf24", width: 1.6, dash: "dot" }, hovertemplate: "Senza fee %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Drawdown", x: viewData.dates, y: viewData.drawdown_pct || [], visible: state.visible.drawdown, line: { color: "#ff6b7b", width: 2.2 }, fill: "tozeroy", fillcolor: "rgba(255,95,115,0.18)", hovertemplate: "Drawdown %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
      { type: "scatter", mode: "markers", name: "Entry preview", x: previewEntryMarkers.x, y: previewEntryMarkers.y, hovertext: previewEntryMarkers.text, visible: state.visible.preview_entry, hovertemplate: "Entry preview<br>%{x}<br>Clicca per aprire i dettagli<extra></extra>", cliponaxis: false, marker: { color: "#f59e0b", size: 12, symbol: "diamond", line: { width: 2, color: "#fff8ef" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers", name: "Exit preview", x: previewExitMarkers.x, y: previewExitMarkers.y, hovertext: previewExitMarkers.text, visible: state.visible.preview_exit, hovertemplate: "Exit preview<br>%{x}<br>Clicca per aprire i dettagli<extra></extra>", cliponaxis: false, marker: { color: "#fb7185", size: 12, symbol: "diamond-open", line: { width: 2, color: "#fff5f7" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Preview live", x: viewPreview?.dates || viewData.dates, y: viewPreview?.equity?.strategy || [], visible: state.visible.preview_strategy, line: { color: "#f59e0b", width: 2.6 }, hovertemplate: "Preview %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Preview DD", x: viewPreview?.dates || viewData.dates, y: viewPreview?.drawdown_pct || [], visible: state.visible.preview_drawdown, line: { color: "#f97316", width: 2.2, dash: "dot" }, hovertemplate: "Preview DD %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
      { type: "scatter", mode: "markers", name: "Entry selected", x: selectedOverlay.entry.x, y: selectedOverlay.entry.y, visible: selectedOverlay.entry.visible, hoverinfo: "skip", cliponaxis: false, marker: { size: 24, symbol: "circle-open", color: "rgba(0,0,0,0)", line: { width: 3, color: "#34e6b8" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers", name: "Exit selected", x: selectedOverlay.exit.x, y: selectedOverlay.exit.y, visible: selectedOverlay.exit.visible, hoverinfo: "skip", cliponaxis: false, marker: { size: 24, symbol: "circle-open", color: "rgba(0,0,0,0)", line: { width: 3, color: "#ff8fa0" } }, xaxis: "x", yaxis: "y" },
      ...(showPreviewIndicatorsOnChart ? buildIndicatorOverlayTraces(previewData) : []),
      ...(showPreviewIndicatorsOnChart ? buildIndicatorPanelTraces(previewData, chartStructure) : []),
      ...(denseGuideTrace ? [denseGuideTrace] : []),
    ];
  }

  function buildIndicatorOverlayTraces(payload) {
    if (!payload || !Array.isArray(payload.indicators)) return [];
    const traces = [];
    payload.indicators
      .filter((indicator) => indicator.placement === "overlay")
      .forEach((indicator) => {
        (Array.isArray(indicator.series) ? indicator.series : []).forEach((series) => {
          traces.push({
            type: "scatter",
            mode: "lines",
            name: series.label || indicator.label || "Indicatore",
            x: payload.dates,
            y: Array.isArray(series.values) ? series.values : [],
            line: {
              color: series.color || "#94a3b8",
              width: 1.9,
              dash: series.dash || "solid",
            },
            hovertemplate: `${series.label || indicator.label || "Indicatore"} %{y:.4f}<br>%{x}<extra></extra>`,
            xaxis: "x",
            yaxis: "y",
          });
        });
      });
    return traces;
  }

  function buildIndicatorPanelTraces(payload, chartStructure = buildChartStructure(payload)) {
    if (!payload || !chartStructure.panelAxes.length) return [];
    const traces = [];
    chartStructure.panelAxes.forEach((panelAxis) => {
      (Array.isArray(panelAxis.indicator?.series) ? panelAxis.indicator.series : []).forEach((series) => {
        traces.push({
          type: "scatter",
          mode: "lines",
          name: series.label || panelAxis.indicator.label || "Indicatore",
          x: payload.dates || [],
          y: Array.isArray(series.values) ? series.values : [],
          line: {
            color: series.color || "#94a3b8",
            width: 1.9,
            dash: series.dash || "solid",
          },
          hovertemplate: `${series.label || panelAxis.indicator.label || "Indicatore"} %{y:.4f}<br>%{x}<extra></extra>`,
          xaxis: panelAxis.xRef,
          yaxis: panelAxis.yRef,
        });
      });
    });
    return traces;
  }

  function buildSelectedTradeOverlay(data = activePayload()) {
    const empty = {
      entry: { x: [], y: [], visible: false },
      exit: { x: [], y: [], visible: false },
    };
    if (!Number.isInteger(state.selectedTradeIndex) || state.selectedTradeIndex < 0) {
      return empty;
    }
    const trade = tradeRows[state.selectedTradeIndex];
    if (!trade) {
      return empty;
    }

    const entryPoint = resolveTradeMarkerPoint({
      markers: data.entry_markers,
      rawTimestamp: trade.entry_raw,
      expectedPrice: trade.entry_price_display,
      intervalKey: data.interval,
    });
    const exitPoint = resolveTradeMarkerPoint({
      markers: data.exit_markers,
      rawTimestamp: trade.exit_raw,
      expectedPrice: trade.exit_price_display,
      intervalKey: data.interval,
    });

    if (entryPoint) {
      empty.entry = { x: [entryPoint.x], y: [entryPoint.y], visible: true };
    }
    if (exitPoint) {
      empty.exit = { x: [exitPoint.x], y: [exitPoint.y], visible: true };
    }
    return empty;
  }

  function resolveTradeMarkerPoint({ markers, rawTimestamp, expectedPrice, intervalKey }) {
    if (!markers || !rawTimestamp) {
      return null;
    }

    const markerLabels = Array.isArray(markers.x) ? markers.x : [];
    const markerPrices = Array.isArray(markers.y) ? markers.y : [];
    const targetLabel = signalBucketLabel(rawTimestamp, intervalKey);
    if (!targetLabel) {
      return null;
    }

    const candidateIndexes = [];
    markerLabels.forEach((label, index) => {
      if (normalizeSignalTimestamp(label) === normalizeSignalTimestamp(targetLabel)) {
        candidateIndexes.push(index);
      }
    });
    if (!candidateIndexes.length) {
      return null;
    }

    const expected = parseSignalPrice(expectedPrice);
    let chosenIndex = candidateIndexes[0];
    if (Number.isFinite(expected)) {
      chosenIndex = candidateIndexes.reduce((best, current) => {
        const bestDistance = Math.abs(Number(markerPrices[best] ?? Number.POSITIVE_INFINITY) - expected);
        const currentDistance = Math.abs(Number(markerPrices[current] ?? Number.POSITIVE_INFINITY) - expected);
        return currentDistance < bestDistance ? current : best;
      }, chosenIndex);
    }

    const xValue = markerLabels[chosenIndex];
    const yValue = Number(markerPrices[chosenIndex]);
    if (!xValue || !Number.isFinite(yValue)) {
      return null;
    }
    return { x: String(xValue), y: yValue };
  }

  function signalBucketLabel(rawTimestamp, intervalKey) {
    const parsed = parseChartDateLabel(rawTimestamp);
    if (!parsed) {
      return normalizeSignalTimestamp(rawTimestamp);
    }
    const bucketDate = floorToBucket(parsed, intervalKey);
    return formatBucketLabel(bucketDate, intervalKey);
  }

  function parseSignalPrice(rawValue) {
    const parsed = Number(String(rawValue || "").replace(/[^0-9.+-]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function buildChartStructure(previewData = activePreviewPayload()) {
    const showEquityPanel = Boolean(
      state.visible.strategy
      || state.visible.benchmark
      || state.visible.gross
      || state.visible.preview_strategy,
    );
    const showDrawdownPanel = Boolean(
      state.visible.drawdown
      || state.visible.preview_drawdown,
    );
    const showIndicatorPanels = false;
    const panelIndicators = Array.isArray(previewData?.indicators)
      ? previewData.indicators.filter((indicator) => (
        showIndicatorPanels
        && (
        indicator?.placement === "panel"
        && Array.isArray(indicator.series)
        && indicator.series.some((series) => hasValues(series?.values))
        )
      ))
      : [];
    const profile = focusProfiles[state.focus] || focusProfiles.all;
    const sections = [{ key: "price", yRef: "y", weight: profile.price }];
    panelIndicators.forEach((indicator, index) => {
      const axisKeys = panelAxisKeys(index);
      sections.push({
        key: `panel-${index}`,
        yRef: axisKeys.yRef,
        weight: profile.indicator,
        indicator,
        ...axisKeys,
      });
    });
    if (showEquityPanel) {
      sections.push({ key: "equity", yRef: "y2", weight: profile.equity });
    }
    if (showDrawdownPanel) {
      sections.push({ key: "drawdown", yRef: "y3", weight: profile.drawdown });
    }

    const gap = sections.length > 1 ? 0.018 : 0;
    const usableHeight = Math.max(1 - (gap * (sections.length - 1)), 0.2);
    const totalWeight = sections.reduce((sum, section) => sum + section.weight, 0);
    let top = 1;
    const domains = {};
    const panelAxes = [];

    sections.forEach((section) => {
      const sectionHeight = usableHeight * (section.weight / totalWeight);
      const nextBottom = Math.max(top - sectionHeight, 0);
      const domain = [nextBottom, top];
      domains[section.yRef] = domain;
      if (section.yRef === "y") {
        domains.y4 = domain;
      }
      if (section.indicator) {
        panelAxes.push({
          indicator: section.indicator,
          domain,
          xLayout: section.xLayout,
          yLayout: section.yLayout,
          xRef: section.xRef,
          yRef: section.yRef,
        });
      }
      top = Math.max(nextBottom - gap, 0);
    });

    return {
      domains,
      panelAxes,
      showEquityPanel,
      showDrawdownPanel,
      height: Math.max(760, 700 + (panelAxes.length * 140)),
    };
  }

  function panelAxisKeys(index) {
    const xIndex = 4 + index;
    const yIndex = 5 + index;
    return {
      xLayout: `xaxis${xIndex}`,
      yLayout: `yaxis${yIndex}`,
      xRef: `x${xIndex}`,
      yRef: `y${yIndex}`,
    };
  }

  function buildPersistentShapes(chartStructure = buildChartStructure()) {
    const shapes = [];
    chartStructure.panelAxes.forEach((panelAxis) => {
      (Array.isArray(panelAxis.indicator?.thresholds) ? panelAxis.indicator.thresholds : []).forEach((threshold) => {
        shapes.push({
          type: "line",
          xref: `${panelAxis.xRef} domain`,
          x0: 0,
          x1: 1,
          yref: panelAxis.yRef,
          y0: Number(threshold.value),
          y1: Number(threshold.value),
          line: {
            color: threshold.color || "#94a3b8",
            width: 1,
            dash: threshold.dash || "dot",
          },
        });
      });
    });
    return shapes;
  }

  function buildPersistentAnnotations(chartStructure = buildChartStructure()) {
    return chartStructure.panelAxes.map((panelAxis) => ({
      xref: "paper",
      x: 0.008,
      xanchor: "left",
      yref: "paper",
      y: Math.max(panelAxis.domain[1] - 0.012, panelAxis.domain[0] + 0.02),
      yanchor: "top",
      text: String(panelAxis.indicator?.label || "Indicatore"),
      showarrow: false,
      font: { color: "#aeb8cf", size: 11, family: "Aptos, Segoe UI Variable, sans-serif" },
      bgcolor: "rgba(9, 13, 21, 0.82)",
      bordercolor: "rgba(171, 184, 214, 0.14)",
      borderpad: 3,
    }));
  }

  function buildLayout() {
    const rangebreaks = buildAxisRangeBreaks();
    const chartStructure = buildChartStructure();
    root.style.minHeight = `${chartStructure.height}px`;
    root.style.height = `${chartStructure.height}px`;
    const equityDomain = chartStructure.domains.y2 || chartStructure.domains.y || [0, 1];
    const drawdownDomain = chartStructure.domains.y3 || chartStructure.domains.y || [0, 1];
    const showBottomLabels = !chartStructure.showDrawdownPanel;
    const layout = {
      paper_bgcolor: "#05070b", plot_bgcolor: "#05070b", font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5" },
      hoverlabel: { bgcolor: "#0f1520", bordercolor: "#212a3f", font: { color: "#eef3ff" } }, hovermode: "closest", dragmode: state.drag,
      margin: { l: 60, r: 72, t: 24, b: 48 }, showlegend: true, legend: { orientation: "h", y: 1.02, x: 0.5, xanchor: "center", font: { size: 10 }, bgcolor: "rgba(0,0,0,0)" }, spikedistance: -1,
      height: chartStructure.height,
      xaxis: axis("x", rangebreaks, { anchor: "y", showticklabels: showBottomLabels }),
      xaxis2: axis("x2", rangebreaks, { anchor: "y2", showticklabels: false }),
      xaxis3: axis("x3", rangebreaks, { anchor: "y3", showticklabels: Boolean(chartStructure.showDrawdownPanel) }),
      yaxis: { domain: chartStructure.domains.y, side: "right", tickformat: ",.3f", gridcolor: "rgba(171,184,214,0.05)", zeroline: false, title: { text: "Prezzo", standoff: 10 } },
      yaxis4: { domain: chartStructure.domains.y4, overlaying: "y", side: "left", showgrid: false, zeroline: false, showticklabels: false },
      yaxis2: { domain: equityDomain, side: "right", tickformat: ",.0f", gridcolor: "rgba(171,184,214,0.05)", zeroline: false, showticklabels: Boolean(chartStructure.showEquityPanel), title: { text: "Equity", standoff: 10 } },
      yaxis3: { domain: drawdownDomain, side: "right", ticksuffix: "%", gridcolor: "rgba(171,184,214,0.05)", zeroline: true, zerolinecolor: "rgba(171,184,214,0.1)", showticklabels: Boolean(chartStructure.showDrawdownPanel), title: { text: "Drawdown", standoff: 10 } },
      annotations: buildPersistentAnnotations(chartStructure),
      shapes: buildPersistentShapes(chartStructure),
      bargap: 0.06,
    };
    chartStructure.panelAxes.forEach((panelAxis) => {
      layout[panelAxis.xLayout] = axis(panelAxis.xRef, rangebreaks, {
        anchor: panelAxis.yRef,
        showticklabels: false,
      });
      layout[panelAxis.yLayout] = {
        domain: panelAxis.domain,
        side: "right",
        gridcolor: "rgba(171,184,214,0.05)",
        zeroline: false,
        tickfont: { color: "#8d98b2", size: 10 },
        automargin: true,
      };
    });
    return layout;
  }

  function buildConfig() {
    return { responsive: true, scrollZoom: true, displayModeBar: false, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "zoom2d", "pan2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"], toImageButtonOptions: { format: "png", filename: "trading-bot-chart", height: 1080, width: 1920, scale: 1 } };
  }

  function axis(name, rangebreaks = [], options = {}) {
    const defaultAnchors = { x: "y", x2: "y2", x3: "y3" };
    const showticklabels = options.showticklabels ?? name === "x3";
    return {
      type: "date",
      domain: [0, 1],
      anchor: options.anchor || defaultAnchors[name] || "y",
      matches: name === "x" ? undefined : "x",
      showgrid: true,
      gridcolor: "rgba(171,184,214,0.04)",
      zeroline: false,
      showspikes: false,
      tickfont: { color: "#8d98b2", size: 11 },
      showticklabels,
      ticks: showticklabels ? undefined : "",
      rangebreaks,
      rangeslider: name === "x" ? { visible: false } : undefined,
    };
  }

  function applyFocus() {
    syncUi();
  }

  function rerenderChart() {
    hideSignalPopup();
    return Plotly.react(root, buildTraces(), buildLayout(), buildConfig()).then(() => {
      applyFocus();
      if (state.viewport.locked) {
        restoreViewport().then(() => applyReplay({ preserveViewport: true }));
        return;
      }
      applyReplay();
    });
  }

  function setCandleSize(intervalKey) {
    const nextKey = canonicalIntervalKey(intervalKey);
    if (!datasetCatalog.has(nextKey) || nextKey === state.candle) return;
    stopTimer();
    // A viewport zoomed on one candle size can become invalid on another size.
    // Reset the manual lock when switching timeframe to avoid broken layouts.
    resetViewportLock();
    state.candle = nextKey;
    state.win = hasWindowControl ? coerceVisibleWindowForInterval(nextKey, state.win) : "all";
    syncPreviewAvailability();
    rerenderChart();
  }

  function chartAction(action) {
    if (action === "pan" || action === "zoom") { state.drag = action; Plotly.relayout(root, { dragmode: state.drag }); return syncUi(); }
    if (action === "reset") return resetChart();
    if (action === "export") return Plotly.downloadImage(root, buildConfig().toImageButtonOptions);
    if (action === "fullscreen" && document.documentElement.requestFullscreen) {
      return document.fullscreenElement ? document.exitFullscreen?.() : document.documentElement.requestFullscreen().catch(() => {});
    }
  }

  function playbackAction(action) {
    if (action === "restart") { stopTimer(); setMode("replay"); state.progress = 0; return applyReplay(); }
    if (action === "step-back") { stopTimer(); setMode("replay"); return move(-state.step); }
    if (action === "step-forward") { stopTimer(); setMode("replay"); return move(state.step); }
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

  function applyReplay(options = {}) {
    const preserveViewport = Boolean(options.preserveViewport || state.viewport.locked);
    const data = activePayload();
    const chartStructure = buildChartStructure();
    clamp();
    const bounds = resolveVisibleBounds(data);
    const current = bounds.current;
    const guideLine = priceLine(current, data);
    const relayoutUpdate = {
      shapes: [...buildPersistentShapes(chartStructure), guideLine.shape],
      annotations: [...buildPersistentAnnotations(chartStructure), guideLine.annotation],
    };
    if (!preserveViewport) {
      relayoutUpdate["xaxis.autorange"] = true;
      relayoutUpdate["yaxis.autorange"] = true;
    }
    runRelayout(relayoutUpdate).then(syncUi);
    updateMarket(current);
    updateReplayInfo(current);
  }

  function resetChart() {
    stopTimer();
    hideSignalPopup();
    state.viewport.locked = false;
    state.viewport.xRange = null;
    state.viewport.yRange = null;
    state.viewport.y2Range = null;
    state.viewport.y3Range = null;
    runRelayout({ dragmode: state.drag, "yaxis.autorange": true, "yaxis2.autorange": true, "yaxis3.autorange": true, "yaxis4.autorange": true }).then(() => { applyFocus(); applyReplay({ preserveViewport: false }); });
  }

  function clamp(reset = false) {
    state.start = Math.min(Math.max(state.start, 0), maxStart());
    if (reset) state.progress = state.mode === "replay" ? 0 : segLen() - 1;
    state.progress = Math.min(Math.max(state.progress, 0), segLen() - 1);
    if (state.mode === "all") state.progress = segLen() - 1;
    syncInputs();
  }

  function syncInputs() {
    if (dom.start) { dom.start.min = "1"; dom.start.max = String(maxStart() + 1); dom.start.value = String(state.start + 1); }
    if (dom.seg) dom.seg.value = String(state.seg);
    if (dom.win) dom.win.value = String(state.win);
    if (dom.step) dom.step.value = String(state.step);
    if (dom.speed) dom.speed.value = String(state.speed);
    if (dom.progress) { dom.progress.min = "1"; dom.progress.max = String(segLen()); dom.progress.value = String(state.progress + 1); dom.progress.disabled = state.mode === "all"; }
  }

  function syncUi() {
    $$("[data-focus-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.focusView === state.focus));
    $$("[data-candle-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.candleView === state.candle));
    $$("[data-chart-action]").forEach((b) => b.classList.toggle("is-active", b.dataset.chartAction === state.drag));
    $$("[data-trace-toggle]").forEach((b) => { const k = b.dataset.traceToggle || ""; b.classList.toggle("is-on", !!state.visible[k]); });
    $$("[data-playback-mode]").forEach((b) => b.classList.toggle("is-active", b.dataset.playbackMode === state.mode));
    if (dom.toggleLabel) dom.toggleLabel.textContent = state.timer ? "Pausa" : "Play";
    if (dom.speedBadge) dom.speedBadge.textContent = `${state.speed}x/sec`;
    setStatus("mode", state.drag === "zoom" ? "Zoom" : "Pan");
    setStatus("focus", ({ all: "Multi panel", price: "Prezzo", equity: "Equity", drawdown: "Drawdown" }[state.focus]) || state.focus);
    setStatus("candle", candleLabel(state.candle));
    setStatus("playback", state.mode === "replay" ? "Replay" : "Tutto subito");
    setStatus("speed", `${state.speed}x/sec`);
    updatePreviewLayerButtons();
    updateIndicatorSummary();
    filterIndicatorCatalog();
  }

  function updateReplayInfo(current) {
    const data = activePayload();
    if (dom.startLabel) dom.startLabel.textContent = `Da candle ${state.start + 1}`;
    if (dom.startDate) dom.startDate.textContent = data.dates[state.start] || "-";
    if (dom.progressLabel) dom.progressLabel.textContent = `Candle ${current + 1} / ${totalPoints()}`;
    if (dom.progressDate) dom.progressDate.textContent = data.dates[current] || "-";
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

  function priceLine(i, data = activePayload()) {
    const close = val(data.market?.close, i) ?? 0, prev = i > 0 ? val(data.market?.close, i - 1) : close, up = close >= prev, color = up ? "#26d0a8" : "#ff5f73";
    return { shape: { type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: close, y1: close, line: { color: "rgba(255,255,255,0.08)", width: 1, dash: "dot" } }, annotation: { xref: "paper", x: 1.01, xanchor: "left", yref: "y", y: close, text: Number(close).toFixed(3), showarrow: false, font: { color: "#041011", size: 11, family: "Aptos, sans-serif" }, bgcolor: color, bordercolor: color, borderpad: 4 } };
  }

  function computeVisiblePriceRange(data, leftIndex, rightIndex) {
    const start = Math.max(Number(leftIndex) || 0, 0);
    const end = Math.min(Number(rightIndex) || 0, totalPoints() - 1);
    if (end < start) return null;

    let minValue = Number.POSITIVE_INFINITY;
    let maxValue = Number.NEGATIVE_INFINITY;
    for (let index = start; index <= end; index += 1) {
      const high = val(data.market?.high, index);
      const low = val(data.market?.low, index);
      const close = val(data.market?.close, index);

      if (Number.isFinite(high)) maxValue = Math.max(maxValue, high);
      if (Number.isFinite(low)) minValue = Math.min(minValue, low);
      if (Number.isFinite(close)) {
        maxValue = Math.max(maxValue, close);
        minValue = Math.min(minValue, close);
      }
    }

    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) return null;
    const span = maxValue - minValue;
    const pad = span > 0 ? Math.max(span * 0.12, 0.01) : Math.max(Math.abs(maxValue) * 0.002, 0.02);
    return [minValue - pad, maxValue + pad];
  }

  function buildPlotlyXRange(data, leftIndex, rightIndex) {
    const leftDate = parsePlotlyDateValue(data.dates?.[leftIndex]);
    const rightDate = parsePlotlyDateValue(data.dates?.[rightIndex]);
    if (!(leftDate instanceof Date) || Number.isNaN(leftDate.getTime()) || !(rightDate instanceof Date) || Number.isNaN(rightDate.getTime())) {
      return [data.dates?.[leftIndex], data.dates?.[rightIndex]];
    }
    return [leftDate.getTime(), rightDate.getTime()];
  }

  function volumeColors(data = activePayload()) {
    const c = data.market?.close || [], o = data.market?.open || [];
    return (data.market?.volume || []).map((_, i) => ((c[i] ?? 0) >= ((o[i] ?? c[i - 1]) ?? 0) ? "rgba(38,208,168,0.45)" : "rgba(255,95,115,0.45)"));
  }

  function buildAxisRangeBreaks() {
    // Temporary safety fallback: avoid dynamic intraday rangebreaks,
    // they can hide all candles on some minute datasets/browser combos.
    return [];
  }

  function segLen() { return state.seg === "all" ? Math.max(totalPoints() - state.start, 1) : Math.max(Math.min(Number(state.seg) || 1, totalPoints() - state.start), 1); }
  function winLen() { return state.win === "all" ? segLen() : Math.max(Math.min(Number(state.win) || 1, segLen()), 1); }
  function maxStart() { return state.seg === "all" ? Math.max(totalPoints() - 1, 0) : Math.max(totalPoints() - (Number(state.seg) || 1), 0); }
  function resolveVisibleBounds(data = activePayload()) {
    const total = Array.isArray(data?.dates) ? data.dates.length : totalPoints();
    const segLength = state.seg === "all"
      ? Math.max(total - state.start, 1)
      : Math.max(Math.min(Number(state.seg) || 1, total - state.start), 1);
    const end = state.mode === "all" ? state.start + segLength - 1 : state.start + state.progress;
    const current = Math.min(Math.max(end, state.start), Math.max(total - 1, 0));
    const windowLength = state.win === "all" ? segLength : Math.max(Math.min(Number(state.win) || 1, segLength), 1);
    const first = windowLength >= segLength ? state.start : Math.max(state.start, current - windowLength + 1);
    const left = Math.max(first - 1, 0);
    const right = Math.min(current + 1, Math.max(total - 1, 0));
    return { left, right, current };
  }
  function slicePayloadWindow(payload, left, right) {
    const start = Math.max(Number(left) || 0, 0);
    const end = Math.max(Number(right) || start, start);
    const slice = (values) => (Array.isArray(values) ? values.slice(start, end + 1) : []);
    return {
      ...payload,
      dates: slice(payload?.dates),
      parsedDates: slice(payload?.parsedDates),
      market: {
        has_candles: Boolean(payload?.market?.has_candles),
        open: slice(payload?.market?.open),
        high: slice(payload?.market?.high),
        low: slice(payload?.market?.low),
        close: slice(payload?.market?.close),
        volume: slice(payload?.market?.volume),
      },
      equity: {
        strategy: slice(payload?.equity?.strategy),
        gross: slice(payload?.equity?.gross),
        benchmark: slice(payload?.equity?.benchmark),
      },
      drawdown_pct: slice(payload?.drawdown_pct),
      indicators: payload?.indicators,
      entry_markers: payload?.entry_markers,
      exit_markers: payload?.exit_markers,
    };
  }
  function sliceMarkersByWindow(markers, leftLabel, rightLabel) {
    const result = { x: [], y: [], text: [] };
    if (!markers || !Array.isArray(markers.x) || !Array.isArray(markers.y)) return result;
    const left = String(leftLabel || "");
    const right = String(rightLabel || "");
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
    if (minutes <= 1) return 180;
    if (minutes <= 2) return 150;
    if (minutes <= 5) return 120;
    if (minutes <= 30) return 100;
    if (minutes <= 60) return 84;
    if (minutes <= 240) return 72;
    return "all";
  }
  function coerceVisibleWindowForInterval(intervalKey, currentWindow) {
    const preferred = defaultVisibleWindow(intervalKey);
    if (preferred === "all") return currentWindow;
    if (currentWindow === "all") return preferred;
    const preferredNumber = Number(preferred);
    const currentNumber = Number(currentWindow);
    if (!Number.isFinite(preferredNumber) || !Number.isFinite(currentNumber)) return preferred;
    // Keep dense intraday frames readable by avoiding extremely wide windows.
    return currentNumber > (preferredNumber * 2) ? preferred : currentNumber;
  }
  function parseLen(v) { return v === "all" ? "all" : Math.max(Number(v) || 1, 1); }
  function val(arr, i) { return Array.isArray(arr) && arr[i] != null ? Number(arr[i]) : null; }
  function text(node, value) { if (node) node.textContent = value; }
  function fmt(v) { return v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(3).replace(/\.?0+$/, ""); }
  function signed(v) { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${Number(v).toFixed(3).replace(/\.?0+$/, "")}`; }
  function signedPct(v) { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`; }
  function compact(v) { const a = Math.abs(v); if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`; if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`; if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`; return `${Math.round(v)}`; }
  function setStatus(k, v) { const n = document.querySelector(`[data-chart-status="${k}"]`); if (n) n.textContent = v; }
  function hasValues(arr) { return Array.isArray(arr) && arr.some((v) => v !== null && v !== undefined); }
  function totalPoints() { return activePayload().dates.length; }
  function activePayload() { return datasetCatalog.get(state.candle) || rawPayload; }
  function activePreviewPayload() {
    if (!state.previewRawPayload) return null;
    const filteredPayload = filterPreviewPayload(state.previewRawPayload, state.previewIndicatorFilter);
    return aggregatePayload(filteredPayload, state.candle);
  }
  function intervalToMinutes(interval) { return intervalDefinitions[canonicalIntervalKey(interval)]?.unit === "minute" ? intervalDefinitions[canonicalIntervalKey(interval)].minutes : null; }
  function candleLabel(interval) { return intervalDefinitions[canonicalIntervalKey(interval)]?.label || String(interval || "").trim() || "n/d"; }
  function roundHour(value) { return Math.round(value * 100) / 100; }

  function canonicalIntervalKey(interval) {
    const raw = String(interval || "").trim().toLowerCase();
    if (raw === "60m") return "1h";
    if (raw === "240m") return "4h";
    if (raw === "1g") return "1d";
    if (raw === "1w") return "1wk";
    return intervalDefinitions[raw]?.key || "1d";
  }

  function buildSupportedCandleOptions(baseInterval) {
    const baseKey = canonicalIntervalKey(baseInterval);
    const baseDefinition = intervalDefinitions[baseKey] || intervalDefinitions["1d"];
    const preferred = candleControlOrder
      .map((key) => intervalDefinitions[key])
      .filter((candidate) => Boolean(candidate))
      .map((candidate) => ({
        ...candidate,
        enabled: canUseCandleSize(baseDefinition, candidate),
      }));
    if (!preferred.some((candidate) => candidate.key === baseDefinition.key)) {
      return [{ ...baseDefinition, enabled: true }, ...preferred];
    }
    if (preferred.length) {
      return preferred;
    }
    // Fallback for uncommon source intervals (es. monthly reports).
    return [{ ...baseDefinition, enabled: true }];
  }

  function canUseCandleSize(baseDefinition, candidate) {
    if (!baseDefinition || !candidate) return false;
    if (candidate.minutes < baseDefinition.minutes) return false;
    if (baseDefinition.unit === "minute" && candidate.unit === "minute") {
      return candidate.minutes >= baseDefinition.minutes;
    }
    if (baseDefinition.unit === "day") {
      return candidate.unit === "day" || candidate.unit === "week" || candidate.unit === "month";
    }
    if (baseDefinition.unit === "week") {
      return candidate.unit === "week" || candidate.unit === "month";
    }
    if (baseDefinition.unit === "month") {
      return candidate.unit === "month";
    }
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
    const parsed = new Date(Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hours),
      Number(minutes),
      Number(seconds),
    ));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function buildMissingDayBreaks(parsedDates, sessionsByDay) {
    if (!parsedDates.length) return [];
    const missingDays = [];
    const first = parsedDates[0];
    const last = parsedDates[parsedDates.length - 1];
    const cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()));
    const end = Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), last.getUTCDate());

    while (cursor.getTime() <= end) {
      const day = cursor.getUTCDay();
      const dayKey = cursor.toISOString().slice(0, 10);
      if (day !== 0 && day !== 6 && !sessionsByDay.has(dayKey)) {
        missingDays.push(dayKey);
      }
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    return missingDays;
  }

  function normalizePayload(payload, fallbackInterval = "1d") {
    const dates = Array.isArray(payload?.dates) ? payload.dates.map((value) => String(value || "")) : [];
    return {
      focus: payload?.focus || "price",
      interval: canonicalIntervalKey(payload?.interval || fallbackInterval || "1d"),
      dates,
      parsedDates: dates.map(parseChartDateLabel).filter((value) => value),
      market: {
        has_candles: Boolean(payload?.market?.has_candles),
        open: normalizeSeries(payload?.market?.open),
        high: normalizeSeries(payload?.market?.high),
        low: normalizeSeries(payload?.market?.low),
        close: normalizeSeries(payload?.market?.close),
        volume: normalizeSeries(payload?.market?.volume),
      },
      equity: {
        strategy: normalizeSeries(payload?.equity?.strategy),
        gross: normalizeSeries(payload?.equity?.gross),
        benchmark: normalizeSeries(payload?.equity?.benchmark),
      },
      drawdown_pct: normalizeSeries(payload?.drawdown_pct),
      entry_markers: normalizeMarkers(payload?.entry_markers),
      exit_markers: normalizeMarkers(payload?.exit_markers),
      indicators: normalizeIndicators(payload?.indicators),
    };
  }

  function normalizeSeries(values) {
    return Array.isArray(values) ? values.map((value) => (value == null || Number.isNaN(Number(value)) ? null : Number(value))) : [];
  }

  function normalizeMarkers(markers) {
    return {
      x: Array.isArray(markers?.x) ? markers.x.map((value) => String(value || "")) : [],
      y: Array.isArray(markers?.y) ? markers.y.map((value) => (value == null || Number.isNaN(Number(value)) ? null : Number(value))) : [],
      text: Array.isArray(markers?.text) ? markers.text.map((value) => String(value || "")) : [],
    };
  }

  function normalizeIndicators(indicators) {
    return Array.isArray(indicators)
      ? indicators.map((indicator) => ({
        key: String(indicator?.key || ""),
        label: String(indicator?.label || ""),
        description: String(indicator?.description || ""),
        placement: String(indicator?.placement || "panel"),
        series: Array.isArray(indicator?.series)
          ? indicator.series.map((series) => ({
            key: String(series?.key || ""),
            label: String(series?.label || ""),
            color: String(series?.color || "#60a5fa"),
            dash: String(series?.dash || "solid"),
            values: normalizeSeries(series?.values),
          }))
          : [],
        thresholds: Array.isArray(indicator?.thresholds)
          ? indicator.thresholds
            .map((threshold) => ({
              label: String(threshold?.label || ""),
              value: threshold?.value == null || Number.isNaN(Number(threshold.value)) ? null : Number(threshold.value),
              color: String(threshold?.color || "#94a3b8"),
              dash: String(threshold?.dash || "dot"),
            }))
            .filter((threshold) => threshold.value !== null)
          : [],
      }))
      : [];
  }

  function filterPreviewPayload(payload, indicatorFilter) {
    if (!payload || !Array.isArray(payload.indicators)) return payload;
    if (!Array.isArray(indicatorFilter) || indicatorFilter.length === 0) return payload;
    const allowed = new Set(indicatorFilter.map((value) => String(value || "").trim()).filter(Boolean));
    return {
      ...payload,
      indicators: payload.indicators.filter((indicator) => allowed.has(String(indicator.key || "").trim())),
    };
  }

  function aggregatePayload(payload, targetInterval) {
    const targetKey = canonicalIntervalKey(targetInterval);
    if (!payload?.dates?.length || payload.interval === targetKey) return payload;

    const buckets = [];
    const bucketByKey = new Map();
    payload.dates.forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      if (!parsedDate) return;
      const bucketDate = floorToBucket(parsedDate, targetKey);
      const bucketKey = bucketDate.toISOString();
      let bucket = bucketByKey.get(bucketKey);
      if (!bucket) {
        bucket = {
          date: bucketDate,
          label: formatBucketLabel(bucketDate, targetKey),
          market: { open: null, high: null, low: null, close: null, volume: 0 },
          equity: { strategy: null, gross: null, benchmark: null },
          drawdown: null,
        };
        bucketByKey.set(bucketKey, bucket);
        buckets.push(bucket);
      }
      updateBucket(bucket, payload, index);
    });
    buckets.sort((a, b) => a.date.getTime() - b.date.getTime());

    return {
      focus: payload.focus,
      interval: targetKey,
      dates: buckets.map((bucket) => bucket.label),
      parsedDates: buckets.map((bucket) => bucket.date),
      market: {
        has_candles: payload.market?.has_candles,
        open: buckets.map((bucket) => bucket.market.open),
        high: buckets.map((bucket) => bucket.market.high),
        low: buckets.map((bucket) => bucket.market.low),
        close: buckets.map((bucket) => bucket.market.close),
        volume: buckets.map((bucket) => bucket.market.volume || null),
      },
      equity: {
        strategy: buckets.map((bucket) => bucket.equity.strategy),
        gross: buckets.map((bucket) => bucket.equity.gross),
        benchmark: buckets.map((bucket) => bucket.equity.benchmark),
      },
      drawdown_pct: buckets.map((bucket) => bucket.drawdown),
      entry_markers: aggregateMarkers(payload.entry_markers, targetKey),
      exit_markers: aggregateMarkers(payload.exit_markers, targetKey),
      indicators: aggregateIndicators(payload.indicators, payload.dates, targetKey),
    };
  }

  function updateBucket(bucket, payload, index) {
    const open = val(payload.market?.open, index);
    const high = val(payload.market?.high, index);
    const low = val(payload.market?.low, index);
    const close = val(payload.market?.close, index);
    const volume = val(payload.market?.volume, index);
    const strategy = val(payload.equity?.strategy, index);
    const gross = val(payload.equity?.gross, index);
    const benchmark = val(payload.equity?.benchmark, index);
    const drawdown = val(payload.drawdown_pct, index);

    if (bucket.market.open === null) bucket.market.open = open ?? close;
    if (high !== null) bucket.market.high = bucket.market.high === null ? high : Math.max(bucket.market.high, high);
    if (low !== null) bucket.market.low = bucket.market.low === null ? low : Math.min(bucket.market.low, low);
    if (close !== null) bucket.market.close = close;
    if (volume !== null) bucket.market.volume += volume;
    if (strategy !== null) bucket.equity.strategy = strategy;
    if (gross !== null) bucket.equity.gross = gross;
    if (benchmark !== null) bucket.equity.benchmark = benchmark;
    if (drawdown !== null) bucket.drawdown = bucket.drawdown === null ? drawdown : Math.min(bucket.drawdown, drawdown);
  }

  function aggregateMarkers(markers, targetInterval) {
    const aggregated = { x: [], y: [], text: [] };
    const targetKey = canonicalIntervalKey(targetInterval);
    markers?.x?.forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      const price = markers?.y?.[index];
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
        ? indicator.series.map((series) => ({
          ...series,
          values: aggregateIndicatorSeries(series.values, dates, targetInterval),
        }))
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
      const bucketKey = bucketDate.toISOString();
      bucketByKey.set(bucketKey, val(values, index));
    });
    return Array.from(bucketByKey.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([, bucketValue]) => bucketValue);
  }

  function floorToBucket(dateValue, intervalKey) {
    const definition = intervalDefinitions[canonicalIntervalKey(intervalKey)] || intervalDefinitions["1d"];
    if (definition.unit === "minute") {
      const totalMinutes = (dateValue.getUTCHours() * 60) + dateValue.getUTCMinutes();
      const bucketMinutes = Math.floor(totalMinutes / definition.minutes) * definition.minutes;
      return new Date(Date.UTC(
        dateValue.getUTCFullYear(),
        dateValue.getUTCMonth(),
        dateValue.getUTCDate(),
        Math.floor(bucketMinutes / 60),
        bucketMinutes % 60,
        0,
      ));
    }
    if (definition.unit === "day") {
      return new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), dateValue.getUTCDate()));
    }
    if (definition.unit === "week") {
      const monday = new Date(Date.UTC(dateValue.getUTCFullYear(), dateValue.getUTCMonth(), dateValue.getUTCDate()));
      const delta = (monday.getUTCDay() + 6) % 7;
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

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function updatePreviewLayerButtons() {
    document.querySelectorAll("[data-preview-layer]").forEach((button) => {
      const key = button.dataset.traceToggle || "";
      const available = Boolean(state.previewAvailable[key]);
      button.hidden = !available;
      if (available) {
        button.classList.toggle("is-on", Boolean(state.visible[key]));
      }
    });
  }

  function syncPreviewAvailability() {
    const previewData = activePreviewPayload();
    state.previewAvailable.preview_entry = hasValues(previewData?.entry_markers?.x);
    state.previewAvailable.preview_exit = hasValues(previewData?.exit_markers?.x);
    state.previewAvailable.preview_strategy = hasValues(previewData?.equity?.strategy);
    state.previewAvailable.preview_drawdown = hasValues(previewData?.drawdown_pct);
    Object.keys(state.previewAvailable).forEach((key) => {
      if (key === "preview_strategy" || key === "preview_drawdown") {
        state.visible[key] = false;
        return;
      }
      state.visible[key] = state.previewAvailable[key];
    });
  }

  function updateIndicatorSummary() {
    const activeCount = Object.entries(state.visible).filter(([, enabled]) => enabled).length;
    const liveIndicatorCount = Array.isArray(activePreviewPayload()?.indicators) ? activePreviewPayload().indicators.length : 0;
    const totalCount = activeCount + liveIndicatorCount;
    if (dom.indicatorCount) dom.indicatorCount.textContent = String(totalCount);
    $$("[data-chart-indicator-open]").forEach((button) => {
      button.classList.toggle("is-on", totalCount > 0);
    });
  }

  function openIndicatorModal() {
    if (!dom.indicatorModal) return;
    dom.indicatorModal.hidden = false;
    document.body.classList.add("chart-indicator-modal-open");
    filterIndicatorCatalog();
    window.requestAnimationFrame(() => {
      dom.indicatorSearch?.focus();
    });
  }

  function closeIndicatorModal() {
    if (!dom.indicatorModal) return;
    dom.indicatorModal.hidden = true;
    document.body.classList.remove("chart-indicator-modal-open");
    if (dom.indicatorSearch) {
      dom.indicatorSearch.value = "";
    }
    filterIndicatorCatalog();
  }

  function filterIndicatorCatalog() {
    const query = String(dom.indicatorSearch?.value || "").trim().toLowerCase();
    let visibleItems = 0;
    $$("[data-chart-indicator-item]").forEach((item) => {
      const available = !item.hidden;
      const haystack = String(item.dataset.chartIndicatorSearch || item.textContent || "").toLowerCase();
      const matches = !query || haystack.includes(query);
      const isHiddenBySearch = available && !matches;
      item.classList.toggle("is-search-hidden", isHiddenBySearch);
      if (available && matches) visibleItems += 1;
    });
    if (dom.indicatorEmpty) {
      dom.indicatorEmpty.hidden = visibleItems !== 0;
    }
  }

  function onKeydown(event) {
    if (event.key !== "Escape") return;
    if (dom.tradeDetailModal?.hidden === false) {
      closeTradeDetailModal();
      return;
    }
    if (dom.indicatorModal?.hidden === false) {
      closeIndicatorModal();
      return;
    }
    if (dom.signalPopup?.hidden === false) {
      hideSignalPopup();
    }
  }

  function onPlotlyRelayout(eventData) {
    if (state.isProgrammaticRelayout || !eventData) return;
    const hasManualViewportChange = Object.keys(eventData).some((key) => (
      key.startsWith("xaxis.range")
      || key === "xaxis.autorange"
    ));
    if (!hasManualViewportChange) return;
    captureViewport();
  }

  function onPlotlyClick(eventData) {
    const point = Array.isArray(eventData?.points) ? eventData.points[0] : null;
    if (!isSignalMarkerPoint(point)) {
      hideSignalPopup();
      return;
    }
    showSignalPopup(point);
  }

  function isSignalMarkerPoint(point) {
    const traceName = String(point?.data?.name || "");
    return ["Entry", "Exit", "Entry preview", "Exit preview"].includes(traceName);
  }

  function showSignalPopup(point) {
    if (!dom.signalPopup || !dom.signalPopupEntry || !dom.signalPopupExit) return;
    const payload = buildSignalPopupPayload(point);
    const hasEntry = Boolean(String(payload.entryText || "").trim());
    const hasExit = Boolean(String(payload.exitText || "").trim());
    if (!hasEntry && !hasExit) return;

    state.selectedTradeIndex = Number.isInteger(payload.tradeIndex) ? payload.tradeIndex : -1;
    signalPopupPanels = {
      entry: String(payload.entryText || ""),
      exit: String(payload.exitText || ""),
    };

    dom.signalPopup.hidden = false;
    if (dom.signalPopupTitle) {
      dom.signalPopupTitle.textContent = payload.title;
    }
    dom.signalPopupEntry.textContent = signalPopupPanels.entry || "Dettaglio entry non disponibile.";
    dom.signalPopupExit.textContent = signalPopupPanels.exit || "Dettaglio exit non disponibile.";
    setSignalPopupTab(payload.activeTab || "entry", { force: true });
    if (dom.signalPopupStatus) {
      dom.signalPopupStatus.textContent = payload.status;
    }
    positionSignalPopup(point);
    applySignalHighlight();
  }

  function hideSignalPopup() {
    state.selectedTradeIndex = -1;
    signalPopupPanels = { entry: "", exit: "" };
    signalPopupText = "";
    if (dom.signalPopup) {
      dom.signalPopup.hidden = true;
    }
    setSignalPopupTab("entry", { force: true });
    applySignalHighlight();
  }

  function buildSignalPopupPayload(point) {
    const traceName = String(point?.data?.name || "Segnale");
    const fallbackText = extractSignalPopupText(point);
    const signalSide = traceName.toLowerCase().includes("exit") ? "exit" : "entry";
    const signalTime = extractSignalTimestamp(point, fallbackText);
    const tradeIndex = resolveTradeIndex(signalSide, signalTime);

    if (tradeIndex < 0 || !tradeRows[tradeIndex]) {
      const isPreview = traceName.toLowerCase().includes("preview");
      return {
        title: traceName,
        entryText: signalSide === "entry" ? (fallbackText || "Dettaglio entry non disponibile.") : "Entry collegata non disponibile.",
        exitText: signalSide === "exit" ? (fallbackText || "Dettaglio exit non disponibile.") : "Exit collegata non disponibile.",
        activeTab: signalSide,
        tradeIndex: -1,
        status: isPreview
          ? "Segnale preview: pairing entry/exit disponibile solo quando il trade esiste nel report base."
          : "Clicca un marker Entry/Exit del report per vedere la coppia completa.",
      };
    }

    const trade = tradeRows[tradeIndex];
    const sequence = Number.isFinite(Number(trade.sequence)) ? Number(trade.sequence) : tradeIndex + 1;
    const tradeHeader = `Trade #${sequence} (${String(trade.status_label || "-")})`;
    const entryBlock = String(trade.entry_detail_text || "").trim() || "ENTRY | Dettaglio non disponibile.";
    const exitBlock = String(trade.exit_detail_text || "").trim() || "EXIT | Dettaglio non disponibile.";
    const isOpenTrade = !String(trade.exit_raw || "").trim();
    return {
      title: isOpenTrade ? "Entry (trade aperto)" : "Entry + Exit",
      entryText: `${tradeHeader}\n\n${entryBlock}`,
      exitText: `${tradeHeader}\n\n${exitBlock}`,
      activeTab: signalSide,
      tradeIndex,
      status: isOpenTrade
        ? "Trade ancora aperto: la sezione EXIT viene aggiornata quando arriva la chiusura."
        : "Coppia completa mostrata: stessa operazione (entry + exit).",
    };
  }

  function setSignalPopupTab(nextTab, options = {}) {
    const tab = nextTab === "exit" ? "exit" : "entry";
    const force = Boolean(options.force);
    if (!force && signalPopupTab === tab) {
      return;
    }
    signalPopupTab = tab;

    dom.signalPopupTabs.forEach((button) => {
      const isActive = (button.dataset.signalPopupTab || "entry") === tab;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    if (dom.signalPopupEntry) {
      dom.signalPopupEntry.hidden = tab !== "entry";
    }
    if (dom.signalPopupExit) {
      dom.signalPopupExit.hidden = tab !== "exit";
    }
    signalPopupText = tab === "exit"
      ? (signalPopupPanels.exit || signalPopupPanels.entry || "")
      : (signalPopupPanels.entry || signalPopupPanels.exit || "");
  }

  function extractSignalPopupText(point) {
    const hoverText = point?.hovertext;
    if (typeof hoverText === "string" && hoverText.trim()) return hoverText.trim();
    const traceHoverText = point?.data?.hovertext;
    if (Array.isArray(traceHoverText) && traceHoverText[point.pointNumber]) {
      return String(traceHoverText[point.pointNumber] || "").trim();
    }
    return "";
  }

  function extractSignalTimestamp(point, fallbackText = "") {
    const lines = String(fallbackText || "").split("\n");
    const firstLine = String(lines[0] || "").trim();
    const match = firstLine.match(/^(?:ENTRY|EXIT)\s*\|\s*(.+)$/i);
    if (match && match[1]) {
      return normalizeSignalTimestamp(match[1]);
    }
    return normalizeSignalTimestamp(point?.x);
  }

  function resolveTradeIndex(signalSide, signalTime) {
    if (!signalTime) return -1;
    if (signalSide === "exit") {
      return tradeIndexByExitRaw.has(signalTime) ? Number(tradeIndexByExitRaw.get(signalTime)) : -1;
    }
    return tradeIndexByEntryRaw.has(signalTime) ? Number(tradeIndexByEntryRaw.get(signalTime)) : -1;
  }

  function normalizeSignalTimestamp(rawValue) {
    const raw = String(rawValue || "").trim();
    if (!raw) return "";
    const match = raw.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2})?)?$/);
    if (!match) return raw;
    const [, datePart, hours = "", minutes = ""] = match;
    return hours ? `${datePart} ${hours}:${minutes}` : datePart;
  }

  function applySignalHighlight() {
    if (!Array.isArray(root?.data) || root.data.length <= traceIndexes.selected_exit) {
      return;
    }
    const overlay = buildSelectedTradeOverlay(activePayload());
    Plotly.restyle(root, {
      x: [overlay.entry.x],
      y: [overlay.entry.y],
      visible: [overlay.entry.visible],
    }, [traceIndexes.selected_entry]);
    Plotly.restyle(root, {
      x: [overlay.exit.x],
      y: [overlay.exit.y],
      visible: [overlay.exit.visible],
    }, [traceIndexes.selected_exit]);
  }

  function positionSignalPopup(point) {
    if (!dom.signalPopupHost || !dom.signalPopup) return;
    const hostRect = dom.signalPopupHost.getBoundingClientRect();
    const popupRect = dom.signalPopup.getBoundingClientRect();
    const event = point?.event;
    const anchorX = Number(event?.clientX || (hostRect.left + hostRect.width - 24));
    const anchorY = Number(event?.clientY || (hostRect.top + 24));
    const padding = 14;
    const preferredOffset = 18;
    const maxLeft = Math.max(hostRect.width - popupRect.width - padding, padding);
    const maxTop = Math.max(hostRect.height - popupRect.height - padding, padding);

    let left = anchorX - hostRect.left + preferredOffset;
    let top = anchorY - hostRect.top - Math.min(popupRect.height * 0.3, 54);

    if ((left + popupRect.width + padding) > hostRect.width) {
      left = anchorX - hostRect.left - popupRect.width - preferredOffset;
    }
    if (left < padding) {
      left = padding;
    }
    if (top < padding) {
      top = padding;
    }
    if (top > maxTop) {
      top = maxTop;
    }

    dom.signalPopup.style.left = `${Math.min(left, maxLeft)}px`;
    dom.signalPopup.style.top = `${Math.min(top, maxTop)}px`;
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
        helper.style.left = "-9999px";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      if (dom.signalPopupStatus) {
        dom.signalPopupStatus.textContent = "Copiato negli appunti.";
      }
    } catch {
      if (dom.signalPopupStatus) {
        dom.signalPopupStatus.textContent = "Copia non riuscita. Puoi comunque selezionare il testo.";
      }
    }
  }

  function moveTradePage(delta) {
    const nextPage = Math.min(Math.max(tradePage + delta, 0), tradePageCount() - 1);
    if (nextPage === tradePage) return;
    tradePage = nextPage;
    renderTradeTape();
  }

  function tradePageCount() {
    return Math.max(Math.ceil(tradeRows.length / tradePageSize), 1);
  }

  function renderTradeTape() {
    if (!dom.tradeTable) return;

    if (!Array.isArray(tradeRows) || tradeRows.length === 0) {
      if (dom.tradeControls) dom.tradeControls.hidden = true;
      dom.tradeTable.innerHTML = `
        <div class="empty-state">
          <p>Nessun trade disponibile per questo chart.</p>
        </div>
      `;
      return;
    }

    const totalPages = tradePageCount();
    tradePage = Math.min(Math.max(tradePage, 0), totalPages - 1);
    const start = tradePage * tradePageSize;
    const end = Math.min(start + tradePageSize, tradeRows.length);
    const visibleRows = tradeRows.slice(start, end);

    if (dom.tradeControls) dom.tradeControls.hidden = false;
    if (dom.tradeSummary) {
      dom.tradeSummary.textContent = `Finestra ${start + 1}-${end} di ${tradeRows.length} operazioni.`;
    }
    if (dom.tradePageLabel) {
      dom.tradePageLabel.textContent = `Pagina ${tradePage + 1} / ${totalPages}`;
    }
    if (dom.tradePrev) {
      dom.tradePrev.disabled = tradePage === 0;
    }
    if (dom.tradeNext) {
      dom.tradeNext.disabled = tradePage >= totalPages - 1;
    }

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
    if (dom.tradeDetailTitle) {
      dom.tradeDetailTitle.textContent = trade.detail_title || `Operazione #${trade.sequence || index + 1}`;
    }
    if (dom.tradeDetailSummary) {
      dom.tradeDetailSummary.innerHTML = `
        <article class="terminal-metric-card">
          <p>Esito</p>
          <strong>${escapeHtml(trade.status_label || "-")}</strong>
          <span>Trade #${escapeHtml(String(trade.sequence ?? index + 1))}</span>
        </article>
        <article class="terminal-metric-card">
          <p>Entrata</p>
          <strong>${escapeHtml(trade.entry_price_display || "-")}</strong>
          <span>${escapeHtml(joinTradeTimestamp(trade.entry_date_display, trade.entry_time_display))}</span>
        </article>
        <article class="terminal-metric-card">
          <p>Uscita</p>
          <strong>${escapeHtml(trade.exit_price_display || "-")}</strong>
          <span>${escapeHtml(joinTradeTimestamp(trade.exit_date_display, trade.exit_time_display))}</span>
        </article>
        <article class="terminal-metric-card">
          <p>PnL</p>
          <strong>${escapeHtml(trade.pnl_display || "-")}</strong>
          <span>Movimento della posizione</span>
        </article>
        <article class="terminal-metric-card">
          <p>Durata</p>
          <strong>${escapeHtml(trade.duration_display || "-")}</strong>
          <span>Tempo in posizione</span>
        </article>
      `;
    }
    if (dom.tradeDetailEntry) {
      dom.tradeDetailEntry.textContent = trade.entry_detail_text || "Dettaglio di entrata non disponibile per questa operazione.";
    }
    if (dom.tradeDetailExit) {
      dom.tradeDetailExit.textContent = trade.exit_detail_text || "Dettaglio di uscita non disponibile per questa operazione.";
    }
    dom.tradeDetailModal.hidden = false;
  }

  function closeTradeDetailModal() {
    if (!dom.tradeDetailModal) return;
    dom.tradeDetailModal.hidden = true;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function joinTradeTimestamp(datePart, timePart) {
    const parts = [datePart, timePart].map((value) => String(value || "").trim()).filter(Boolean);
    return parts.join(" · ") || "-";
  }

  function onAxisHover(event) {
    if (state.axisDrag) {
      root.classList.add("is-axis-draggable");
      return;
    }
    root.classList.toggle("is-axis-draggable", isWithinPriceAxisZone(event));
  }

  function onAxisDragStart(event) {
    if (event.button !== 0 || !isWithinPriceAxisZone(event)) return;
    const fullLayout = root._fullLayout;
    const currentRange = fullLayout?.yaxis?.range;
    if (!Array.isArray(currentRange) || currentRange.length !== 2) return;
    const min = Number(currentRange[0]);
    const max = Number(currentRange[1]);
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return;

    event.preventDefault();
    event.stopPropagation();
    stopTimer();
    state.axisDrag = {
      startY: event.clientY,
      min,
      max,
      center: (min + max) / 2,
      halfRange: Math.abs(max - min) / 2,
    };
    root.classList.add("is-axis-draggable");
  }

  function onAxisDragMove(event) {
    if (!state.axisDrag) return;
    event.preventDefault();
    const dragDistance = event.clientY - state.axisDrag.startY;
    const zoomFactor = Math.exp(dragDistance * 0.01);
    const nextHalfRange = Math.max(state.axisDrag.halfRange * zoomFactor, 0.000001);
    runRelayout({
      "yaxis.autorange": false,
      "yaxis.range": [
        state.axisDrag.center - nextHalfRange,
        state.axisDrag.center + nextHalfRange,
      ],
    });
  }

  function onAxisDragEnd() {
    if (!state.axisDrag) return;
    state.axisDrag = null;
    captureViewport();
    root.classList.remove("is-axis-draggable");
  }

  function isWithinPriceAxisZone(event) {
    const fullLayout = root._fullLayout;
    if (!fullLayout) return false;
    const rect = root.getBoundingClientRect();
    const axisBox = getPriceAxisZone(fullLayout);
    if (!axisBox) return false;
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;
    return localX >= axisBox.left && localX <= axisBox.right && localY >= axisBox.top && localY <= axisBox.bottom;
  }

  function getPriceAxisZone(fullLayout) {
    const margin = fullLayout.margin || { l: 60, r: 72, t: 18, b: 48 };
    const width = fullLayout.width || root.clientWidth;
    const height = fullLayout.height || root.clientHeight;
    const plotWidth = Math.max(width - margin.l - margin.r, 1);
    const plotHeight = Math.max(height - margin.t - margin.b, 1);
    const domain = buildChartStructure().domains.y || [0.16, 1];
    const top = margin.t + (1 - domain[1]) * plotHeight;
    const bottom = margin.t + (1 - domain[0]) * plotHeight;
    return {
      left: margin.l + plotWidth + 6,
      right: width,
      top,
      bottom,
    };
  }

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
    state.previewRawPayload = null;
    state.previewIndicatorFilter = null;
    Object.keys(state.previewAvailable).forEach((key) => {
      state.previewAvailable[key] = false;
      state.visible[key] = false;
    });
    setStatus("preview", baselinePreviewLabel);
    rerenderChart();
  }

  window.tradingBotChartTerminal = {
    applyPreview,
    clearPreview,
    setPreviewIndicatorFilter,
  };

  function runRelayout(update) {
    state.isProgrammaticRelayout = true;
    return Plotly.relayout(root, update).finally(() => {
      state.isProgrammaticRelayout = false;
    });
  }

  function resetViewportLock() {
    state.viewport.locked = false;
    state.viewport.xRange = null;
    state.viewport.yRange = null;
    state.viewport.y2Range = null;
    state.viewport.y3Range = null;
  }

  function captureViewport() {
    const fullLayout = root._fullLayout;
    if (!fullLayout) return;
    state.viewport.locked = true;
    state.viewport.xRange = clampViewportXRange(copyRange(fullLayout.xaxis?.range), activePayload().dates);
    state.viewport.yRange = null;
    state.viewport.y2Range = null;
    state.viewport.y3Range = null;
  }

  function restoreViewport() {
    if (!state.viewport.locked) return Promise.resolve();
    const update = {};
    if (state.viewport.xRange) {
      update["xaxis.range"] = [...state.viewport.xRange];
    }
    if (!Object.keys(update).length) return Promise.resolve();
    return runRelayout(update);
  }

  function copyRange(range) {
    if (!Array.isArray(range) || range.length !== 2) return null;
    return [range[0], range[1]];
  }

  function clampViewportXRange(range, dates) {
    if (!Array.isArray(range) || range.length !== 2) return null;
    const parsedStart = parsePlotlyDateValue(range[0]);
    const parsedEnd = parsePlotlyDateValue(range[1]);
    if (!parsedStart || !parsedEnd) return copyRange(range);
    const firstDate = parsePlotlyDateValue(dates?.[0]);
    const lastDate = parsePlotlyDateValue(dates?.[(dates?.length || 1) - 1]);
    if (!firstDate || !lastDate) return copyRange(range);

    let start = parsedStart;
    let end = parsedEnd;
    if (start.getTime() > end.getTime()) {
      [start, end] = [end, start];
    }

    if (start.getTime() < firstDate.getTime()) start = firstDate;
    if (end.getTime() > lastDate.getTime()) end = lastDate;
    if (end.getTime() <= start.getTime()) {
      const fallbackStartIndex = Math.max((dates?.length || 1) - Math.max(winLen(), 2), 0);
      const fallbackStart = parsePlotlyDateValue(dates?.[fallbackStartIndex]) || firstDate;
      return [fallbackStart.getTime(), lastDate.getTime()];
    }
    return [start.getTime(), end.getTime()];
  }

  function parsePlotlyDateValue(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      const fromEpoch = new Date(value);
      return Number.isNaN(fromEpoch.getTime()) ? null : fromEpoch;
    }
    const raw = String(value || "").trim();
    if (!raw) return null;
    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
    if (match) {
      const [, year, month, day, hours = "00", minutes = "00", seconds = "00"] = match;
      const parsedLocal = new Date(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hours),
        Number(minutes),
        Number(seconds),
      );
      return Number.isNaN(parsedLocal.getTime()) ? null : parsedLocal;
    }
    const fallback = new Date(raw);
    return Number.isNaN(fallback.getTime()) ? null : fallback;
  }
})();
