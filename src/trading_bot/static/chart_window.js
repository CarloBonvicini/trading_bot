(() => {
  const dataNode = document.getElementById("chart-window-data");
  const tradeTableDataNode = document.getElementById("chart-trade-table-data");
  const root = document.getElementById("interactive-chart-root");
  if (!dataNode || !root || typeof Plotly === "undefined") return;

  const intervalDefinitions = {
    "1m": { key: "1m", label: "1m", unit: "minute", minutes: 1 },
    "2m": { key: "2m", label: "2m", unit: "minute", minutes: 2 },
    "5m": { key: "5m", label: "5m", unit: "minute", minutes: 5 },
    "15m": { key: "15m", label: "15m", unit: "minute", minutes: 15 },
    "30m": { key: "30m", label: "30m", unit: "minute", minutes: 30 },
    "1h": { key: "1h", label: "1h", unit: "minute", minutes: 60 },
    "90m": { key: "90m", label: "90m", unit: "minute", minutes: 90 },
    "1d": { key: "1d", label: "1g", unit: "day", minutes: 24 * 60 },
    "1wk": { key: "1wk", label: "1w", unit: "week", minutes: 7 * 24 * 60 },
    "1mo": { key: "1mo", label: "1mo", unit: "month", minutes: 30 * 24 * 60 },
  };
  const rawPayload = normalizePayload(JSON.parse(dataNode.textContent || "{}"));
  const rawTradeRows = JSON.parse(tradeTableDataNode?.textContent || "[]");
  const tradeRows = Array.isArray(rawTradeRows) ? rawTradeRows : [];
  if (!rawPayload.dates.length) return;

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
    signalPopupBody: $("[data-signal-popup-body]"),
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
  const chartPanel = root.closest(".chart-terminal-main");
  const baselinePreviewLabel = document.querySelector('[data-chart-status="preview"]')?.textContent || "Setup iniziale del report";
  const tradePageSize = 50;

  const focusProfiles = {
    all: { price: 5.2, indicator: 1.55, equity: 2.05, drawdown: 1.25 },
    price: { price: 7.4, indicator: 1.6, equity: 0.95, drawdown: 0.65 },
    equity: { price: 4.4, indicator: 1.45, equity: 3.1, drawdown: 0.75 },
    drawdown: { price: 3.9, indicator: 1.35, equity: 2.35, drawdown: 1.9 },
  };
  const supportedCandleOptions = buildSupportedCandleOptions(rawPayload.interval);
  const datasetCatalog = new Map(
    supportedCandleOptions.map((option) => [
      option.key,
      option.key === rawPayload.interval ? rawPayload : aggregatePayload(rawPayload, option.key),
    ]),
  );
  const defaultCandle = datasetCatalog.has(rawPayload.interval)
    ? rawPayload.interval
    : supportedCandleOptions[0]?.key || rawPayload.interval;
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
  };
  const state = {
    focus: focusProfiles[rawPayload.focus] ? rawPayload.focus : "price",
    candle: defaultCandle,
    drag: "pan",
    timer: null,
    mode: "all",
    start: 0,
    seg: "all",
    win: "all",
    step: 1,
    speed: 6,
    progress: Math.max(initialTotal - 1, 0),
    visible: {
      price: true,
      volume: false,
      entry: hasValues(rawPayload.entry_markers?.x),
      exit: hasValues(rawPayload.exit_markers?.x),
      strategy: hasValues(rawPayload.equity?.strategy),
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
  };
  let signalPopupHideTimer = null;
  let signalPopupText = "";
  let tradePage = 0;

  renderCandleControls();
  syncInputs();
  renderTradeTape();

  Plotly.newPlot(root, buildTraces(), buildLayout(), buildConfig()).then(() => {
    bind();
    applyFocus();
    applyReplay();
  });

  function bind() {
    $$("[data-focus-view]").forEach((b) => b.addEventListener("click", () => {
      const nextFocus = b.dataset.focusView || "all";
      if (nextFocus === state.focus) {
        syncUi();
        return;
      }
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
    dom.signalPopup?.addEventListener("mouseenter", clearSignalPopupHideTimer);
    dom.signalPopup?.addEventListener("mouseleave", scheduleSignalPopupHide);
    chartPanel?.addEventListener("mouseleave", scheduleSignalPopupHide);
    dom.tradePrev?.addEventListener("click", () => moveTradePage(-1));
    dom.tradeNext?.addEventListener("click", () => moveTradePage(1));
    dom.tradeTable?.addEventListener("click", onTradeTableClick);
    dom.tradeTable?.addEventListener("keydown", onTradeTableKeydown);
    $$("[data-chart-trade-detail-close]").forEach((button) => button.addEventListener("click", closeTradeDetailModal));
    document.addEventListener("keydown", onKeydown);
    root.addEventListener("mousedown", onAxisDragStart, true);
    root.addEventListener("mousemove", onAxisHover);
    window.addEventListener("mousemove", onAxisDragMove);
    window.addEventListener("mouseup", onAxisDragEnd);
    root.addEventListener("mouseleave", () => {
      if (!state.axisDrag) root.classList.remove("is-axis-draggable");
    });
    window.addEventListener("resize", () => Plotly.Plots.resize(root));
    root.on?.("plotly_relayout", onPlotlyRelayout);
    root.on?.("plotly_hover", onPlotlyHover);
    root.on?.("plotly_unhover", onPlotlyUnhover);
  }

  function buildTraces() {
    const data = activePayload();
    const previewData = activePreviewPayload();
    const chartStructure = buildChartStructure(previewData);
    const candles = data.market?.has_candles && hasValues(data.market?.open) && hasValues(data.market?.high) && hasValues(data.market?.low);
    return [
      candles
        ? { type: "candlestick", name: "Prezzo", x: data.dates, open: data.market.open, high: data.market.high, low: data.market.low, close: data.market.close, increasing: { line: { color: "#26d0a8", width: 1.2 }, fillcolor: "#26d0a8" }, decreasing: { line: { color: "#ff5f73", width: 1.2 }, fillcolor: "#ff5f73" }, whiskerwidth: 0.35, hovertemplate: "O %{open:.4f}<br>H %{high:.4f}<br>L %{low:.4f}<br>C %{close:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" }
        : { type: "scatter", mode: "lines", name: "Prezzo", x: data.dates, y: data.market?.close || [], line: { color: "#7dd3fc", width: 2.3 }, hovertemplate: "Close %{y:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" },
      { type: "bar", name: "Volume", x: data.dates, y: data.market?.volume || [], marker: { color: volumeColors(data) }, opacity: 0.45, visible: state.visible.volume, hovertemplate: "Volume %{y:,.0f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y4" },
      { type: "scatter", mode: "markers+text", name: "Entry", x: data.entry_markers?.x || [], y: data.entry_markers?.y || [], text: (data.entry_markers?.x || []).map(() => "ENTRY"), hovertext: data.entry_markers?.text || [], visible: state.visible.entry, hovertemplate: "Entry<br>%{x}<br>Dettaglio nel popup accanto<extra></extra>", textposition: "top center", textfont: { color: "#bdf9de", size: 10, family: "Aptos, Segoe UI Variable, sans-serif" }, cliponaxis: false, marker: { color: "#21c98b", size: 14, symbol: "triangle-up", line: { width: 2, color: "#f8fffc" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers+text", name: "Exit", x: data.exit_markers?.x || [], y: data.exit_markers?.y || [], text: (data.exit_markers?.x || []).map(() => "EXIT"), hovertext: data.exit_markers?.text || [], visible: state.visible.exit, hovertemplate: "Exit<br>%{x}<br>Dettaglio nel popup accanto<extra></extra>", textposition: "bottom center", textfont: { color: "#ffd2d9", size: 10, family: "Aptos, Segoe UI Variable, sans-serif" }, cliponaxis: false, marker: { color: "#ff5f73", size: 14, symbol: "triangle-down", line: { width: 2, color: "#fff6f7" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Strategia", x: data.dates, y: data.equity?.strategy || [], visible: state.visible.strategy, line: { color: "#4ade80", width: 2.5 }, hovertemplate: "Strategia %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Buy & hold", x: data.dates, y: data.equity?.benchmark || [], visible: state.visible.benchmark, line: { color: "#60a5fa", width: 2.1 }, hovertemplate: "Buy & hold %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Senza fee", x: data.dates, y: data.equity?.gross || [], visible: state.visible.gross, line: { color: "#fbbf24", width: 1.6, dash: "dot" }, hovertemplate: "Senza fee %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Drawdown", x: data.dates, y: data.drawdown_pct || [], visible: state.visible.drawdown, line: { color: "#ff6b7b", width: 2.2 }, fill: "tozeroy", fillcolor: "rgba(255,95,115,0.18)", hovertemplate: "Drawdown %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
      { type: "scatter", mode: "markers+text", name: "Entry preview", x: previewData?.entry_markers?.x || [], y: previewData?.entry_markers?.y || [], text: (previewData?.entry_markers?.x || []).map(() => "P-ENTRY"), hovertext: previewData?.entry_markers?.text || [], visible: state.visible.preview_entry, hovertemplate: "Entry preview<br>%{x}<br>Dettaglio nel popup accanto<extra></extra>", textposition: "top center", textfont: { color: "#ffe1ad", size: 9, family: "Aptos, Segoe UI Variable, sans-serif" }, cliponaxis: false, marker: { color: "#f59e0b", size: 12, symbol: "diamond", line: { width: 2, color: "#fff8ef" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers+text", name: "Exit preview", x: previewData?.exit_markers?.x || [], y: previewData?.exit_markers?.y || [], text: (previewData?.exit_markers?.x || []).map(() => "P-EXIT"), hovertext: previewData?.exit_markers?.text || [], visible: state.visible.preview_exit, hovertemplate: "Exit preview<br>%{x}<br>Dettaglio nel popup accanto<extra></extra>", textposition: "bottom center", textfont: { color: "#ffd7df", size: 9, family: "Aptos, Segoe UI Variable, sans-serif" }, cliponaxis: false, marker: { color: "#fb7185", size: 12, symbol: "diamond-open", line: { width: 2, color: "#fff5f7" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Preview live", x: previewData?.dates || data.dates, y: previewData?.equity?.strategy || [], visible: state.visible.preview_strategy, line: { color: "#f59e0b", width: 2.6 }, hovertemplate: "Preview %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Preview DD", x: previewData?.dates || data.dates, y: previewData?.drawdown_pct || [], visible: state.visible.preview_drawdown, line: { color: "#f97316", width: 2.2, dash: "dot" }, hovertemplate: "Preview DD %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
      ...buildIndicatorOverlayTraces(previewData),
      ...buildIndicatorPanelTraces(previewData, chartStructure),
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

  function buildChartStructure(previewData = activePreviewPayload()) {
    const panelIndicators = Array.isArray(previewData?.indicators)
      ? previewData.indicators.filter((indicator) => (
        indicator?.placement === "panel"
        && Array.isArray(indicator.series)
        && indicator.series.some((series) => hasValues(series?.values))
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
    sections.push({ key: "equity", yRef: "y2", weight: profile.equity });
    sections.push({ key: "drawdown", yRef: "y3", weight: profile.drawdown });

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
    const layout = {
      paper_bgcolor: "#05070b", plot_bgcolor: "#05070b", font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5" },
      hoverlabel: { bgcolor: "#0f1520", bordercolor: "#212a3f", font: { color: "#eef3ff" } }, hovermode: "closest", dragmode: state.drag,
      margin: { l: 60, r: 72, t: 18, b: 48 }, showlegend: false, uirevision: "chart-terminal-static", spikedistance: -1,
      height: chartStructure.height,
      xaxis: axis("x", rangebreaks, { anchor: "y", showticklabels: false }),
      xaxis2: axis("x2", rangebreaks, { anchor: "y2", showticklabels: false }),
      xaxis3: axis("x3", rangebreaks, { anchor: "y3", showticklabels: true }),
      yaxis: { domain: chartStructure.domains.y, side: "right", tickformat: ",.3f", gridcolor: "rgba(171,184,214,0.05)", zeroline: false },
      yaxis4: { domain: chartStructure.domains.y4, overlaying: "y", side: "left", showgrid: false, zeroline: false, showticklabels: false },
      yaxis2: { domain: chartStructure.domains.y2, side: "right", tickformat: ",.0f", gridcolor: "rgba(171,184,214,0.05)", zeroline: false },
      yaxis3: { domain: chartStructure.domains.y3, side: "right", ticksuffix: "%", gridcolor: "rgba(171,184,214,0.05)", zeroline: true, zerolinecolor: "rgba(171,184,214,0.1)" },
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
    return { responsive: true, scrollZoom: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "zoom2d", "pan2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"], toImageButtonOptions: { format: "png", filename: "trading-bot-chart", height: 1080, width: 1920, scale: 1 } };
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
    state.candle = nextKey;
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
    const end = state.mode === "all" ? state.start + segLen() - 1 : state.start + state.progress;
    const current = Math.min(Math.max(end, state.start), totalPoints() - 1);
    const first = winLen() >= segLen() ? state.start : Math.max(state.start, current - winLen() + 1);
    const left = Math.max(first - 1, 0), right = Math.min(current + 1, totalPoints() - 1);
    const guideLine = priceLine(current, data);
    const relayoutUpdate = {
      shapes: [...buildPersistentShapes(chartStructure), guideLine.shape],
      annotations: [...buildPersistentAnnotations(chartStructure), guideLine.annotation],
    };
    if (!preserveViewport) {
      relayoutUpdate["xaxis.range"] = [data.dates[left], data.dates[right]];
      relayoutUpdate["xaxis2.range"] = [data.dates[left], data.dates[right]];
      relayoutUpdate["xaxis3.range"] = [data.dates[left], data.dates[right]];
      chartStructure.panelAxes.forEach((panelAxis) => {
        relayoutUpdate[`${panelAxis.xLayout}.range`] = [data.dates[left], data.dates[right]];
      });
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

  function volumeColors(data = activePayload()) {
    const c = data.market?.close || [], o = data.market?.open || [];
    return (data.market?.volume || []).map((_, i) => ((c[i] ?? 0) >= ((o[i] ?? c[i - 1]) ?? 0) ? "rgba(38,208,168,0.45)" : "rgba(255,95,115,0.45)"));
  }

  function buildAxisRangeBreaks() {
    const data = activePayload();
    const intervalMinutes = intervalToMinutes(data.interval);
    if (!intervalMinutes) return [];

    const parsedDates = data.parsedDates.filter((value) => value instanceof Date && !Number.isNaN(value.getTime()));
    if (parsedDates.length < 3) return [];

    const sessionsByDay = new Map();
    parsedDates.forEach((dateValue) => {
      const dayKey = dateValue.toISOString().slice(0, 10);
      const minuteOfDay = (dateValue.getUTCHours() * 60) + dateValue.getUTCMinutes();
      const existing = sessionsByDay.get(dayKey);
      if (!existing) {
        sessionsByDay.set(dayKey, { start: minuteOfDay, end: minuteOfDay, count: 1 });
        return;
      }
      existing.start = Math.min(existing.start, minuteOfDay);
      existing.end = Math.max(existing.end, minuteOfDay);
      existing.count += 1;
    });

    const daySessions = Array.from(sessionsByDay.values()).filter((session) => session.count > 1);
    if (!daySessions.length) return [];

    const medianStart = median(daySessions.map((session) => session.start).sort((a, b) => a - b));
    const medianEnd = median(daySessions.map((session) => session.end).sort((a, b) => a - b)) + intervalMinutes;
    const sessionStartMinutes = Math.max(0, Math.min(medianStart, (24 * 60) - intervalMinutes));
    const sessionEndMinutes = Math.max(sessionStartMinutes + intervalMinutes, Math.min(medianEnd, 24 * 60));
    const rangebreaks = [];

    if ((sessionEndMinutes - sessionStartMinutes) < ((24 * 60) - Math.max(intervalMinutes / 2, 1))) {
      rangebreaks.push({
        pattern: "hour",
        bounds: [roundHour(sessionEndMinutes / 60), roundHour(sessionStartMinutes / 60)],
      });
    }

    if (!parsedDates.some((dateValue) => {
      const day = dateValue.getUTCDay();
      return day === 0 || day === 6;
    })) {
      rangebreaks.push({ bounds: ["sat", "mon"] });
    }

    const missingDays = buildMissingDayBreaks(parsedDates, sessionsByDay);
    if (missingDays.length) {
      rangebreaks.push({ values: missingDays });
    }

    return rangebreaks;
  }

  function segLen() { return state.seg === "all" ? Math.max(totalPoints() - state.start, 1) : Math.max(Math.min(Number(state.seg) || 1, totalPoints() - state.start), 1); }
  function winLen() { return state.win === "all" ? segLen() : Math.max(Math.min(Number(state.win) || 1, segLen()), 1); }
  function maxStart() { return state.seg === "all" ? Math.max(totalPoints() - 1, 0) : Math.max(totalPoints() - (Number(state.seg) || 1), 0); }
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
  function median(values) { if (!values.length) return 0; const mid = Math.floor(values.length / 2); return values.length % 2 ? values[mid] : ((values[mid - 1] + values[mid]) / 2); }
  function roundHour(value) { return Math.round(value * 100) / 100; }

  function canonicalIntervalKey(interval) {
    const raw = String(interval || "").trim().toLowerCase();
    if (raw === "60m") return "1h";
    if (raw === "1w") return "1wk";
    return intervalDefinitions[raw]?.key || "1d";
  }

  function buildSupportedCandleOptions(baseInterval) {
    const baseKey = canonicalIntervalKey(baseInterval);
    const baseDefinition = intervalDefinitions[baseKey] || intervalDefinitions["1d"];
    return Object.values(intervalDefinitions).filter((candidate) => canUseCandleSize(baseDefinition, candidate));
  }

  function canUseCandleSize(baseDefinition, candidate) {
    if (!baseDefinition || !candidate) return false;
    if (candidate.minutes < baseDefinition.minutes) return false;
    if (baseDefinition.unit === "minute" && candidate.unit === "minute") {
      return candidate.minutes % baseDefinition.minutes === 0;
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
    dom.candleControls.innerHTML = supportedCandleOptions.map((option) => `
      <button type="button" class="terminal-chip${option.key === state.candle ? " is-active" : ""}" data-candle-view="${option.key}">
        ${option.label}
      </button>
    `).join("");
    $$("[data-candle-view]").forEach((button) => {
      button.addEventListener("click", () => setCandleSize(button.dataset.candleView || rawPayload.interval));
    });
  }

  function parseChartDateLabel(label) {
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
    const aggregated = [];
    const bucketByKey = new Map();
    (Array.isArray(dates) ? dates : []).forEach((label, index) => {
      const parsedDate = parseChartDateLabel(label);
      if (!parsedDate) return;
      const bucketDate = floorToBucket(parsedDate, targetInterval);
      const bucketKey = bucketDate.toISOString();
      bucketByKey.set(bucketKey, val(values, index));
    });
    bucketByKey.forEach((bucketValue) => {
      aggregated.push(bucketValue);
    });
    return aggregated;
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
    }
  }

  function onPlotlyRelayout(eventData) {
    if (state.isProgrammaticRelayout || !eventData) return;
    const hasManualViewportChange = Object.keys(eventData).some((key) => (
      key.startsWith("xaxis.range")
      || key.startsWith("yaxis.range")
      || key.startsWith("yaxis2.range")
      || key.startsWith("yaxis3.range")
      || key === "xaxis.autorange"
      || key === "yaxis.autorange"
      || key === "yaxis2.autorange"
      || key === "yaxis3.autorange"
    ));
    if (!hasManualViewportChange) return;
    captureViewport();
  }

  function onPlotlyHover(eventData) {
    const point = Array.isArray(eventData?.points) ? eventData.points[0] : null;
    if (!isSignalMarkerPoint(point)) return;
    showSignalPopup(point);
  }

  function onPlotlyUnhover() {
    scheduleSignalPopupHide();
  }

  function isSignalMarkerPoint(point) {
    const traceName = String(point?.data?.name || "");
    return ["Entry", "Exit", "Entry preview", "Exit preview"].includes(traceName);
  }

  function showSignalPopup(point) {
    if (!dom.signalPopup || !dom.signalPopupBody) return;
    clearSignalPopupHideTimer();
    signalPopupText = extractSignalPopupText(point);
    if (!signalPopupText) return;
    dom.signalPopup.hidden = false;
    if (dom.signalPopupTitle) {
      dom.signalPopupTitle.textContent = String(point?.data?.name || "Segnale");
    }
    dom.signalPopupBody.textContent = signalPopupText;
    if (dom.signalPopupStatus) {
      dom.signalPopupStatus.textContent = "Testo selezionabile. Usa Copia per portarlo fuori al volo.";
    }
    positionSignalPopup(point);
  }

  function hideSignalPopup() {
    clearSignalPopupHideTimer();
    signalPopupText = "";
    if (dom.signalPopup) {
      dom.signalPopup.hidden = true;
    }
  }

  function scheduleSignalPopupHide() {
    if (!dom.signalPopup || dom.signalPopup.hidden) return;
    clearSignalPopupHideTimer();
    signalPopupHideTimer = window.setTimeout(() => {
      if (dom.signalPopup?.matches(":hover")) return;
      hideSignalPopup();
    }, 180);
  }

  function clearSignalPopupHideTimer() {
    if (!signalPopupHideTimer) return;
    window.clearTimeout(signalPopupHideTimer);
    signalPopupHideTimer = null;
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
    state.previewRawPayload = normalizePayload(payload || {}, rawPayload.interval);
    syncPreviewAvailability();
    setStatus("preview", previewLabel);
    rerenderChart();
  }

  function setPreviewIndicatorFilter(indicatorKeys) {
    state.previewIndicatorFilter = Array.isArray(indicatorKeys) ? [...indicatorKeys] : null;
    if (!state.previewRawPayload) return;
    syncPreviewAvailability();
    rerenderChart();
  }

  function clearPreview() {
    hideSignalPopup();
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

  function captureViewport() {
    const fullLayout = root._fullLayout;
    if (!fullLayout) return;
    state.viewport.locked = true;
    state.viewport.xRange = copyRange(fullLayout.xaxis?.range);
    state.viewport.yRange = copyRange(fullLayout.yaxis?.range);
    state.viewport.y2Range = copyRange(fullLayout.yaxis2?.range);
    state.viewport.y3Range = copyRange(fullLayout.yaxis3?.range);
  }

  function restoreViewport() {
    if (!state.viewport.locked) return Promise.resolve();
    const chartStructure = buildChartStructure();
    const update = {};
    if (state.viewport.xRange) {
      update["xaxis.range"] = [...state.viewport.xRange];
      update["xaxis2.range"] = [...state.viewport.xRange];
      update["xaxis3.range"] = [...state.viewport.xRange];
      chartStructure.panelAxes.forEach((panelAxis) => {
        update[`${panelAxis.xLayout}.range`] = [...state.viewport.xRange];
      });
    }
    if (state.viewport.yRange) {
      update["yaxis.range"] = [...state.viewport.yRange];
      update["yaxis.autorange"] = false;
    }
    if (state.viewport.y2Range) {
      update["yaxis2.range"] = [...state.viewport.y2Range];
      update["yaxis2.autorange"] = false;
    }
    if (state.viewport.y3Range) {
      update["yaxis3.range"] = [...state.viewport.y3Range];
      update["yaxis3.autorange"] = false;
    }
    if (!Object.keys(update).length) return Promise.resolve();
    return runRelayout(update);
  }

  function copyRange(range) {
    if (!Array.isArray(range) || range.length !== 2) return null;
    return [range[0], range[1]];
  }
})();
