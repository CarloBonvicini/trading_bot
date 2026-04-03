(() => {
  const dataNode = document.getElementById("chart-window-data");
  const root = document.getElementById("interactive-chart-root");
  if (!dataNode || !root || typeof Plotly === "undefined") return;

  const p = JSON.parse(dataNode.textContent || "{}");
  const total = Array.isArray(p.dates) ? p.dates.length : 0;
  if (!total) return;

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
  };
  const baselinePreviewLabel = document.querySelector('[data-chart-status="preview"]')?.textContent || "Sistema salvato";

  const focusDomains = {
    all: { price: [0.5, 1], equity: [0.2, 0.43], drawdown: [0, 0.13] },
    price: { price: [0.24, 1], equity: [0.11, 0.2], drawdown: [0, 0.07] },
    equity: { price: [0.62, 1], equity: [0.16, 0.58], drawdown: [0, 0.11] },
    drawdown: { price: [0.72, 1], equity: [0.36, 0.68], drawdown: [0, 0.27] },
  };
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
    focus: focusDomains[p.focus] ? p.focus : "all",
    range: "series",
    drag: "pan",
    timer: null,
    mode: "all",
    start: Math.max(total - Math.min(total, 100), 0),
    seg: total >= 100 ? 100 : "all",
    win: total >= 100 ? 100 : "all",
    step: 1,
    speed: 6,
    progress: Math.max(Math.min(total, 100) - 1, 0),
    visible: {
      price: true,
      volume: hasValues(p.market?.volume),
      entry: hasValues(p.entry_markers?.x),
      exit: hasValues(p.exit_markers?.x),
      strategy: hasValues(p.equity?.strategy),
      benchmark: hasValues(p.equity?.benchmark),
      gross: hasValues(p.equity?.gross),
      drawdown: hasValues(p.drawdown_pct),
      preview_entry: false,
      preview_exit: false,
      preview_strategy: false,
      preview_drawdown: false,
    },
    previewAvailable: {
      preview_entry: false,
      preview_exit: false,
      preview_strategy: false,
      preview_drawdown: false,
    },
  };

  syncInputs();

  Plotly.newPlot(root, buildTraces(), buildLayout(), buildConfig()).then(() => {
    bind();
    applyFocus();
    applyReplay();
  });

  function bind() {
    $$("[data-focus-view]").forEach((b) => b.addEventListener("click", () => { state.focus = b.dataset.focusView || "all"; applyFocus(); }));
    $$("[data-range-view]").forEach((b) => b.addEventListener("click", () => { state.range = b.dataset.rangeView || "all"; applyCalendarRange(); }));
    $$("[data-chart-action]").forEach((b) => b.addEventListener("click", () => chartAction(b.dataset.chartAction || "")));
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
    window.addEventListener("resize", () => Plotly.Plots.resize(root));
  }

  function buildTraces() {
    const candles = p.market?.has_candles && hasValues(p.market?.open) && hasValues(p.market?.high) && hasValues(p.market?.low);
    return [
      candles
        ? { type: "candlestick", name: "Prezzo", x: p.dates, open: p.market.open, high: p.market.high, low: p.market.low, close: p.market.close, increasing: { line: { color: "#26d0a8", width: 1.2 }, fillcolor: "#26d0a8" }, decreasing: { line: { color: "#ff5f73", width: 1.2 }, fillcolor: "#ff5f73" }, whiskerwidth: 0.35, hovertemplate: "O %{open:.4f}<br>H %{high:.4f}<br>L %{low:.4f}<br>C %{close:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" }
        : { type: "scatter", mode: "lines", name: "Prezzo", x: p.dates, y: p.market?.close || [], line: { color: "#7dd3fc", width: 2.3 }, hovertemplate: "Close %{y:.4f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y" },
      { type: "bar", name: "Volume", x: p.dates, y: p.market?.volume || [], marker: { color: volumeColors() }, opacity: 0.45, visible: state.visible.volume, hovertemplate: "Volume %{y:,.0f}<br>%{x}<extra></extra>", xaxis: "x", yaxis: "y4" },
      { type: "scatter", mode: "markers", name: "Entry", x: p.entry_markers?.x || [], y: p.entry_markers?.y || [], text: p.entry_markers?.text || [], visible: state.visible.entry, hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>", marker: { color: "#21c98b", size: 9, symbol: "triangle-up", line: { width: 1, color: "#08110d" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers", name: "Exit", x: p.exit_markers?.x || [], y: p.exit_markers?.y || [], text: p.exit_markers?.text || [], visible: state.visible.exit, hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>", marker: { color: "#ff5f73", size: 9, symbol: "triangle-down", line: { width: 1, color: "#16080d" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Strategia", x: p.dates, y: p.equity?.strategy || [], visible: state.visible.strategy, line: { color: "#4ade80", width: 2.5 }, hovertemplate: "Strategia %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Buy & hold", x: p.dates, y: p.equity?.benchmark || [], visible: state.visible.benchmark, line: { color: "#60a5fa", width: 2.1 }, hovertemplate: "Buy & hold %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Senza fee", x: p.dates, y: p.equity?.gross || [], visible: state.visible.gross, line: { color: "#fbbf24", width: 1.6, dash: "dot" }, hovertemplate: "Senza fee %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Drawdown", x: p.dates, y: p.drawdown_pct || [], visible: state.visible.drawdown, line: { color: "#ff6b7b", width: 2.2 }, fill: "tozeroy", fillcolor: "rgba(255,95,115,0.18)", hovertemplate: "Drawdown %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
      { type: "scatter", mode: "markers", name: "Preview entry", x: [], y: [], text: [], visible: false, hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>", marker: { color: "#f59e0b", size: 10, symbol: "diamond", line: { width: 1, color: "#2b1800" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "markers", name: "Preview exit", x: [], y: [], text: [], visible: false, hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>", marker: { color: "#fb7185", size: 10, symbol: "diamond-open", line: { width: 1, color: "#2f0a12" } }, xaxis: "x", yaxis: "y" },
      { type: "scatter", mode: "lines", name: "Preview live", x: p.dates, y: [], visible: false, line: { color: "#f59e0b", width: 2.6 }, hovertemplate: "Preview %{y:,.2f}<br>%{x}<extra></extra>", xaxis: "x2", yaxis: "y2" },
      { type: "scatter", mode: "lines", name: "Preview DD", x: p.dates, y: [], visible: false, line: { color: "#f97316", width: 2.2, dash: "dot" }, hovertemplate: "Preview DD %{y:.2f}%<br>%{x}<extra></extra>", xaxis: "x3", yaxis: "y3" },
    ];
  }

  function buildLayout() {
    return {
      paper_bgcolor: "#05070b", plot_bgcolor: "#05070b", font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5" },
      hoverlabel: { bgcolor: "#0f1520", bordercolor: "#212a3f", font: { color: "#eef3ff" } }, hovermode: "x unified", dragmode: state.drag,
      margin: { l: 60, r: 72, t: 18, b: 48 }, showlegend: false, uirevision: "chart-terminal", spikedistance: 1000,
      xaxis: axis("x"), xaxis2: axis("x2"), xaxis3: axis("x3"),
      yaxis: { domain: focusDomains[state.focus].price, side: "right", tickformat: ",.3f", gridcolor: "rgba(171,184,214,0.08)", zeroline: false },
      yaxis4: { domain: focusDomains[state.focus].price, overlaying: "y", side: "left", showgrid: false, zeroline: false, showticklabels: false },
      yaxis2: { domain: focusDomains[state.focus].equity, side: "right", tickformat: ",.0f", gridcolor: "rgba(171,184,214,0.08)", zeroline: false },
      yaxis3: { domain: focusDomains[state.focus].drawdown, side: "right", ticksuffix: "%", gridcolor: "rgba(171,184,214,0.08)", zeroline: true, zerolinecolor: "rgba(171,184,214,0.14)" },
      bargap: 0.06,
    };
  }

  function buildConfig() {
    return { responsive: true, scrollZoom: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "zoom2d", "pan2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"], toImageButtonOptions: { format: "png", filename: "trading-bot-chart", height: 1080, width: 1920, scale: 1 } };
  }

  function axis(name) {
    return { domain: [0, 1], anchor: name === "x" ? "y" : name === "x2" ? "y2" : "y3", matches: name === "x" ? undefined : "x", showgrid: true, gridcolor: "rgba(171,184,214,0.07)", zeroline: false, showspikes: true, spikemode: "across", spikecolor: "rgba(96,165,250,0.42)", spikethickness: 1, tickfont: { color: "#8d98b2", size: 11 } };
  }

  function applyFocus() {
    const d = focusDomains[state.focus] || focusDomains.all;
    Plotly.relayout(root, { "yaxis.domain": d.price, "yaxis4.domain": d.price, "yaxis2.domain": d.equity, "yaxis3.domain": d.drawdown });
    syncUi();
  }

  function applyCalendarRange() {
    stopTimer();
    const bounds = calendarBounds(state.range);
    if (!bounds) return applyReplay();
    Plotly.relayout(root, { "xaxis.range": bounds, "xaxis2.range": bounds, "xaxis3.range": bounds });
    syncUi();
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

  function applyReplay() {
    clamp();
    const end = state.mode === "all" ? state.start + segLen() - 1 : state.start + state.progress;
    const current = Math.min(Math.max(end, state.start), total - 1);
    const first = winLen() >= segLen() ? state.start : Math.max(state.start, current - winLen() + 1);
    const left = Math.max(first - 1, 0), right = Math.min(current + 1, total - 1);
    Plotly.relayout(root, { "xaxis.range": [p.dates[left], p.dates[right]], "xaxis2.range": [p.dates[left], p.dates[right]], "xaxis3.range": [p.dates[left], p.dates[right]], shapes: [priceLine(current).shape], annotations: [priceLine(current).annotation] }).then(syncUi);
    updateMarket(current);
    updateReplayInfo(current);
  }

  function resetChart() {
    stopTimer();
    state.range = "series";
    Plotly.relayout(root, { dragmode: state.drag, "yaxis.autorange": true, "yaxis2.autorange": true, "yaxis3.autorange": true, "yaxis4.autorange": true }).then(() => { applyFocus(); applyReplay(); });
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
    $$("[data-range-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.rangeView === state.range));
    $$("[data-chart-action]").forEach((b) => b.classList.toggle("is-active", b.dataset.chartAction === state.drag));
    $$("[data-trace-toggle]").forEach((b) => { const k = b.dataset.traceToggle || ""; b.classList.toggle("is-on", !!state.visible[k]); });
    $$("[data-playback-mode]").forEach((b) => b.classList.toggle("is-active", b.dataset.playbackMode === state.mode));
    if (dom.toggleLabel) dom.toggleLabel.textContent = state.timer ? "Pausa" : "Play";
    if (dom.speedBadge) dom.speedBadge.textContent = `${state.speed}x/sec`;
    setStatus("mode", state.drag === "zoom" ? "Zoom" : "Pan");
    setStatus("focus", ({ all: "Multi panel", price: "Prezzo", equity: "Equity", drawdown: "Drawdown" }[state.focus]) || state.focus);
    setStatus("range", state.range === "series" ? "Serie scelta" : state.range);
    setStatus("playback", state.mode === "replay" ? "Replay" : "Tutto subito");
    setStatus("speed", `${state.speed}x/sec`);
    updatePreviewLayerButtons();
  }

  function updateReplayInfo(current) {
    if (dom.startLabel) dom.startLabel.textContent = `Da candle ${state.start + 1}`;
    if (dom.startDate) dom.startDate.textContent = p.dates[state.start] || "-";
    if (dom.progressLabel) dom.progressLabel.textContent = `Candle ${current + 1} / ${total}`;
    if (dom.progressDate) dom.progressDate.textContent = p.dates[current] || "-";
  }

  function updateMarket(i) {
    const close = val(p.market?.close, i), open = val(p.market?.open, i), high = val(p.market?.high, i), low = val(p.market?.low, i), prev = i > 0 ? val(p.market?.close, i - 1) : open, volume = val(p.market?.volume, i);
    text(dom.open, fmt(open)); text(dom.high, fmt(high)); text(dom.low, fmt(low)); text(dom.close, fmt(close)); text(dom.closePanel, fmt(close)); text(dom.timestamp, p.dates[i] || "-"); if (volume !== null) text(dom.volume, compact(volume));
    if (close === null || prev === null || prev === 0) return setChange("neutral", "n/a", "n/a");
    const delta = close - prev, pct = (delta / prev) * 100, cls = delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral";
    setChange(cls, signed(delta), signedPct(pct));
  }

  function setChange(cls, a, b) {
    [dom.change, dom.changePct].forEach((n) => { if (!n) return; n.classList.remove("terminal-change-positive", "terminal-change-negative", "terminal-change-neutral"); n.classList.add(`terminal-change-${cls}`); });
    text(dom.change, a); text(dom.changePct, b);
  }

  function priceLine(i) {
    const close = val(p.market?.close, i) ?? 0, prev = i > 0 ? val(p.market?.close, i - 1) : close, up = close >= prev, color = up ? "#26d0a8" : "#ff5f73";
    return { shape: { type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: close, y1: close, line: { color: "rgba(255,255,255,0.1)", width: 1, dash: "dot" } }, annotation: { xref: "paper", x: 1.01, xanchor: "left", yref: "y", y: close, text: Number(close).toFixed(3), showarrow: false, font: { color: "#041011", size: 11, family: "Aptos, sans-serif" }, bgcolor: color, bordercolor: color, borderpad: 4 } };
  }

  function volumeColors() {
    const c = p.market?.close || [], o = p.market?.open || [];
    return (p.market?.volume || []).map((_, i) => ((c[i] ?? 0) >= ((o[i] ?? c[i - 1]) ?? 0) ? "rgba(38,208,168,0.45)" : "rgba(255,95,115,0.45)"));
  }

  function calendarBounds(kind) {
    if (kind === "series" || kind === "all") return null;
    const end = new Date(p.dates[total - 1]); if (Number.isNaN(end.getTime())) return null; const start = new Date(end);
    if (kind === "1d") start.setDate(start.getDate() - 1); else if (kind === "1w") start.setDate(start.getDate() - 7); else if (kind === "1m") start.setMonth(start.getMonth() - 1); else if (kind === "3m") start.setMonth(start.getMonth() - 3); else if (kind === "ytd") { start.setMonth(0, 1); start.setHours(0, 0, 0, 0); } else return null;
    return [start.toISOString(), end.toISOString()];
  }

  function segLen() { return state.seg === "all" ? Math.max(total - state.start, 1) : Math.max(Math.min(Number(state.seg) || 1, total - state.start), 1); }
  function winLen() { return state.win === "all" ? segLen() : Math.max(Math.min(Number(state.win) || 1, segLen()), 1); }
  function maxStart() { return state.seg === "all" ? Math.max(total - 1, 0) : Math.max(total - (Number(state.seg) || 1), 0); }
  function parseLen(v) { return v === "all" ? "all" : Math.max(Number(v) || 1, 1); }
  function val(arr, i) { return Array.isArray(arr) && arr[i] != null ? Number(arr[i]) : null; }
  function text(node, value) { if (node) node.textContent = value; }
  function fmt(v) { return v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(3).replace(/\.?0+$/, ""); }
  function signed(v) { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${Number(v).toFixed(3).replace(/\.?0+$/, "")}`; }
  function signedPct(v) { return v == null || Number.isNaN(v) ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`; }
  function compact(v) { const a = Math.abs(v); if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`; if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`; if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`; return `${Math.round(v)}`; }
  function setStatus(k, v) { const n = document.querySelector(`[data-chart-status="${k}"]`); if (n) n.textContent = v; }
  function hasValues(arr) { return Array.isArray(arr) && arr.some((v) => v !== null && v !== undefined); }

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

  function applyPreview(payload, previewLabel = "Preview live") {
    const previewData = payload || {};
    state.previewAvailable.preview_entry = hasValues(previewData.entry_markers?.x);
    state.previewAvailable.preview_exit = hasValues(previewData.exit_markers?.x);
    state.previewAvailable.preview_strategy = hasValues(previewData.equity?.strategy);
    state.previewAvailable.preview_drawdown = hasValues(previewData.drawdown_pct);

    Object.keys(state.previewAvailable).forEach((key) => {
      state.visible[key] = state.previewAvailable[key];
    });

    Plotly.restyle(
      root,
      {
        x: [previewData.entry_markers?.x || []],
        y: [previewData.entry_markers?.y || []],
        text: [previewData.entry_markers?.text || []],
        visible: state.visible.preview_entry ? true : false,
        name: ["Preview entry"],
      },
      [traceIndexes.preview_entry],
    );
    Plotly.restyle(
      root,
      {
        x: [previewData.exit_markers?.x || []],
        y: [previewData.exit_markers?.y || []],
        text: [previewData.exit_markers?.text || []],
        visible: state.visible.preview_exit ? true : false,
        name: ["Preview exit"],
      },
      [traceIndexes.preview_exit],
    );
    Plotly.restyle(
      root,
      {
        x: [previewData.dates || p.dates],
        y: [previewData.equity?.strategy || []],
        visible: state.visible.preview_strategy ? true : false,
        name: [previewLabel],
      },
      [traceIndexes.preview_strategy],
    );
    Plotly.restyle(
      root,
      {
        x: [previewData.dates || p.dates],
        y: [previewData.drawdown_pct || []],
        visible: state.visible.preview_drawdown ? true : false,
        name: [`${previewLabel} DD`],
      },
      [traceIndexes.preview_drawdown],
    );
    setStatus("preview", previewLabel);
    syncUi();
  }

  function clearPreview() {
    Object.keys(state.previewAvailable).forEach((key) => {
      state.previewAvailable[key] = false;
      state.visible[key] = false;
    });

    Plotly.restyle(root, { x: [[]], y: [[]], text: [[]], visible: false }, [traceIndexes.preview_entry]);
    Plotly.restyle(root, { x: [[]], y: [[]], text: [[]], visible: false }, [traceIndexes.preview_exit]);
    Plotly.restyle(root, { x: [p.dates], y: [[]], visible: false, name: ["Preview live"] }, [traceIndexes.preview_strategy]);
    Plotly.restyle(root, { x: [p.dates], y: [[]], visible: false, name: ["Preview DD"] }, [traceIndexes.preview_drawdown]);
    setStatus("preview", baselinePreviewLabel);
    syncUi();
  }

  window.tradingBotChartTerminal = {
    applyPreview,
    clearPreview,
  };
})();
