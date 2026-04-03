(() => {
  const payloadNode = document.getElementById("chart-window-data");
  const root = document.getElementById("interactive-chart-root");
  if (!payloadNode || !root || typeof Plotly === "undefined") {
    return;
  }

  const payload = JSON.parse(payloadNode.textContent || "{}");
  const traceIndexes = {
    price: 0,
    volume: 1,
    entry: 2,
    exit: 3,
    strategy: 4,
    benchmark: 5,
    gross: 6,
    drawdown: 7,
  };

  const focusDomains = {
    all: { price: [0.5, 1], equity: [0.2, 0.43], drawdown: [0, 0.13] },
    price: { price: [0.24, 1], equity: [0.11, 0.2], drawdown: [0, 0.07] },
    equity: { price: [0.62, 1], equity: [0.16, 0.58], drawdown: [0, 0.11] },
    drawdown: { price: [0.72, 1], equity: [0.36, 0.68], drawdown: [0, 0.27] },
  };

  const state = {
    focus: focusDomains[payload.focus] ? payload.focus : "all",
    range: "all",
    dragmode: "pan",
    visible: {
      price: true,
      volume: hasValues(payload?.market?.volume),
      entry: Array.isArray(payload?.entry_markers?.x) && payload.entry_markers.x.length > 0,
      exit: Array.isArray(payload?.exit_markers?.x) && payload.exit_markers.x.length > 0,
      strategy: hasValues(payload?.equity?.strategy),
      benchmark: hasValues(payload?.equity?.benchmark),
      gross: hasValues(payload?.equity?.gross),
      drawdown: hasValues(payload?.drawdown_pct),
    },
  };

  const volumeColors = buildVolumeColors(payload);
  const latestPriceInfo = buildLatestPriceInfo(payload);

  const traces = [
    buildPriceTrace(payload),
    {
      type: "bar",
      name: "Volume",
      x: payload.dates,
      y: payload.market?.volume || [],
      marker: { color: volumeColors },
      opacity: 0.45,
      visible: state.visible.volume,
      hovertemplate: "Volume %{y:,.0f}<br>%{x}<extra></extra>",
      xaxis: "x",
      yaxis: "y4",
    },
    {
      type: "scatter",
      mode: "markers",
      name: "Entry",
      x: payload.entry_markers?.x || [],
      y: payload.entry_markers?.y || [],
      text: payload.entry_markers?.text || [],
      visible: state.visible.entry,
      hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>",
      marker: {
        color: "#21c98b",
        size: 9,
        symbol: "triangle-up",
        line: { width: 1, color: "#08110d" },
      },
      xaxis: "x",
      yaxis: "y",
    },
    {
      type: "scatter",
      mode: "markers",
      name: "Exit",
      x: payload.exit_markers?.x || [],
      y: payload.exit_markers?.y || [],
      text: payload.exit_markers?.text || [],
      visible: state.visible.exit,
      hovertemplate: "%{text}<br>%{x}<br>%{y:.4f}<extra></extra>",
      marker: {
        color: "#ff5f73",
        size: 9,
        symbol: "triangle-down",
        line: { width: 1, color: "#16080d" },
      },
      xaxis: "x",
      yaxis: "y",
    },
    {
      type: "scatter",
      mode: "lines",
      name: "Strategia",
      x: payload.dates,
      y: payload.equity?.strategy || [],
      visible: state.visible.strategy,
      line: { color: "#4ade80", width: 2.5 },
      hovertemplate: "Strategia %{y:,.2f}<br>%{x}<extra></extra>",
      xaxis: "x2",
      yaxis: "y2",
    },
    {
      type: "scatter",
      mode: "lines",
      name: "Buy & hold",
      x: payload.dates,
      y: payload.equity?.benchmark || [],
      visible: state.visible.benchmark,
      line: { color: "#60a5fa", width: 2.1 },
      hovertemplate: "Buy & hold %{y:,.2f}<br>%{x}<extra></extra>",
      xaxis: "x2",
      yaxis: "y2",
    },
    {
      type: "scatter",
      mode: "lines",
      name: "Equity senza fee",
      x: payload.dates,
      y: payload.equity?.gross || [],
      visible: state.visible.gross,
      line: { color: "#fbbf24", width: 1.6, dash: "dot" },
      hovertemplate: "Senza fee %{y:,.2f}<br>%{x}<extra></extra>",
      xaxis: "x2",
      yaxis: "y2",
    },
    {
      type: "scatter",
      mode: "lines",
      name: "Drawdown",
      x: payload.dates,
      y: payload.drawdown_pct || [],
      visible: state.visible.drawdown,
      line: { color: "#ff6b7b", width: 2.2 },
      fill: "tozeroy",
      fillcolor: "rgba(255, 95, 115, 0.18)",
      hovertemplate: "Drawdown %{y:.2f}%<br>%{x}<extra></extra>",
      xaxis: "x3",
      yaxis: "y3",
    },
  ];

  const layout = {
    paper_bgcolor: "#05070b",
    plot_bgcolor: "#05070b",
    font: { family: "Aptos, Segoe UI Variable, sans-serif", color: "#d6ddf5" },
    hoverlabel: {
      bgcolor: "#0f1520",
      bordercolor: "#212a3f",
      font: { color: "#eef3ff" },
    },
    hovermode: "x unified",
    dragmode: state.dragmode,
    margin: { l: 60, r: 72, t: 18, b: 48 },
    showlegend: false,
    uirevision: "chart-terminal",
    spikedistance: 1000,
    shapes: latestPriceInfo.shape ? [latestPriceInfo.shape] : [],
    annotations: latestPriceInfo.annotation ? [latestPriceInfo.annotation] : [],
    xaxis: baseXAxis(),
    xaxis2: baseXAxis("x2"),
    xaxis3: baseXAxis("x3"),
    yaxis: {
      domain: focusDomains[state.focus].price,
      title: "",
      side: "right",
      tickformat: ",.3f",
      gridcolor: "rgba(171, 184, 214, 0.08)",
      zeroline: false,
      fixedrange: false,
    },
    yaxis4: {
      domain: focusDomains[state.focus].price,
      overlaying: "y",
      side: "left",
      showgrid: false,
      zeroline: false,
      showticklabels: false,
      fixedrange: false,
    },
    yaxis2: {
      domain: focusDomains[state.focus].equity,
      title: "",
      side: "right",
      tickformat: ",.0f",
      gridcolor: "rgba(171, 184, 214, 0.08)",
      zeroline: false,
      fixedrange: false,
    },
    yaxis3: {
      domain: focusDomains[state.focus].drawdown,
      title: "",
      side: "right",
      ticksuffix: "%",
      gridcolor: "rgba(171, 184, 214, 0.08)",
      zeroline: true,
      zerolinecolor: "rgba(171, 184, 214, 0.14)",
      fixedrange: false,
    },
    bargap: 0.06,
  };

  const config = {
    responsive: true,
    scrollZoom: true,
    displaylogo: false,
    modeBarButtonsToRemove: [
      "lasso2d",
      "select2d",
      "autoScale2d",
      "zoom2d",
      "pan2d",
      "hoverClosestCartesian",
      "hoverCompareCartesian",
      "toggleSpikelines",
    ],
    toImageButtonOptions: {
      format: "png",
      filename: "trading-bot-chart",
      height: 1080,
      width: 1920,
      scale: 1,
    },
  };

  Plotly.newPlot(root, traces, layout, config).then(() => {
    bindUi();
    applyFocus(state.focus);
    syncControls();
  });

  function bindUi() {
    document.querySelectorAll("[data-focus-view]").forEach((button) => {
      button.addEventListener("click", () => {
        state.focus = button.dataset.focusView || "all";
        applyFocus(state.focus);
      });
    });

    document.querySelectorAll("[data-range-view]").forEach((button) => {
      button.addEventListener("click", () => {
        state.range = button.dataset.rangeView || "all";
        applyRange(state.range);
      });
    });

    document.querySelectorAll("[data-chart-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.chartAction;
        if (action === "pan" || action === "zoom") {
          state.dragmode = action;
          Plotly.relayout(root, { dragmode: state.dragmode });
          syncControls();
          return;
        }
        if (action === "reset") {
          resetChart();
          return;
        }
        if (action === "export") {
          Plotly.downloadImage(root, config.toImageButtonOptions);
          return;
        }
        if (action === "fullscreen" && document.documentElement.requestFullscreen) {
          if (document.fullscreenElement) {
            document.exitFullscreen?.();
          } else {
            document.documentElement.requestFullscreen().catch(() => {});
          }
        }
      });
    });

    document.querySelectorAll("[data-trace-toggle]").forEach((button) => {
      if (button.dataset.locked === "true") {
        return;
      }
      button.addEventListener("click", () => {
        const traceKey = button.dataset.traceToggle;
        if (!traceKey) {
          return;
        }
        state.visible[traceKey] = !state.visible[traceKey];
        applyTraceVisibility(traceKey);
      });
    });

    window.addEventListener("resize", () => Plotly.Plots.resize(root));
  }

  function applyFocus(focus) {
    const domains = focusDomains[focus] || focusDomains.all;
    Plotly.relayout(root, {
      "yaxis.domain": domains.price,
      "yaxis4.domain": domains.price,
      "yaxis2.domain": domains.equity,
      "yaxis3.domain": domains.drawdown,
    });
    syncControls();
  }

  function applyRange(rangeKey) {
    const bounds = resolveRange(rangeKey);
    if (!bounds) {
      Plotly.relayout(root, {
        "xaxis.autorange": true,
        "xaxis2.autorange": true,
        "xaxis3.autorange": true,
      });
      syncControls();
      return;
    }

    Plotly.relayout(root, {
      "xaxis.range": bounds,
      "xaxis2.range": bounds,
      "xaxis3.range": bounds,
    });
    syncControls();
  }

  function applyTraceVisibility(traceKey) {
    const traceIndex = traceIndexes[traceKey];
    if (traceIndex === undefined) {
      return;
    }
    Plotly.restyle(root, { visible: state.visible[traceKey] ? true : "legendonly" }, [traceIndex]);
    syncControls();
  }

  function resetChart() {
    state.range = "all";
    Plotly.relayout(root, {
      dragmode: state.dragmode,
      "xaxis.autorange": true,
      "xaxis2.autorange": true,
      "xaxis3.autorange": true,
      "yaxis.autorange": true,
      "yaxis2.autorange": true,
      "yaxis3.autorange": true,
      "yaxis4.autorange": true,
    }).then(() => applyFocus(state.focus));
  }

  function syncControls() {
    document.querySelectorAll("[data-focus-view]").forEach((button) => {
      const active = button.dataset.focusView === state.focus;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });

    document.querySelectorAll("[data-range-view]").forEach((button) => {
      const active = button.dataset.rangeView === state.range;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });

    document.querySelectorAll("[data-chart-action]").forEach((button) => {
      const action = button.dataset.chartAction;
      const active = action === state.dragmode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });

    document.querySelectorAll("[data-trace-toggle]").forEach((button) => {
      const traceKey = button.dataset.traceToggle;
      const enabled = state.visible[traceKey];
      button.classList.toggle("is-on", !!enabled);
      button.setAttribute("aria-pressed", String(!!enabled));
    });

    setStatus("mode", state.dragmode === "zoom" ? "Zoom" : "Pan");
    setStatus("focus", labelForState(state.focus, { all: "Multi panel", price: "Prezzo", equity: "Equity", drawdown: "Drawdown" }));
    setStatus("range", labelForState(state.range, { all: "All", "1d": "1 giorno", "1w": "1 settimana", "1m": "1 mese", "3m": "3 mesi", ytd: "YTD" }));
  }

  function setStatus(key, value) {
    const node = document.querySelector(`[data-chart-status="${key}"]`);
    if (node) {
      node.textContent = value;
    }
  }

  function resolveRange(rangeKey) {
    if (!Array.isArray(payload.dates) || payload.dates.length === 0 || rangeKey === "all") {
      return null;
    }

    const end = new Date(payload.dates[payload.dates.length - 1]);
    if (Number.isNaN(end.getTime())) {
      return null;
    }

    const start = new Date(end);
    if (rangeKey === "1d") {
      start.setDate(start.getDate() - 1);
    } else if (rangeKey === "1w") {
      start.setDate(start.getDate() - 7);
    } else if (rangeKey === "1m") {
      start.setMonth(start.getMonth() - 1);
    } else if (rangeKey === "3m") {
      start.setMonth(start.getMonth() - 3);
    } else if (rangeKey === "ytd") {
      start.setMonth(0, 1);
      start.setHours(0, 0, 0, 0);
    } else {
      return null;
    }

    return [start.toISOString(), end.toISOString()];
  }

  function buildPriceTrace(source) {
    const hasCandles =
      source.market?.has_candles &&
      hasValues(source.market?.open) &&
      hasValues(source.market?.high) &&
      hasValues(source.market?.low);

    if (hasCandles) {
      return {
        type: "candlestick",
        name: "Prezzo",
        x: source.dates,
        open: source.market.open,
        high: source.market.high,
        low: source.market.low,
        close: source.market.close,
        increasing: { line: { color: "#26d0a8", width: 1.2 }, fillcolor: "#26d0a8" },
        decreasing: { line: { color: "#ff5f73", width: 1.2 }, fillcolor: "#ff5f73" },
        whiskerwidth: 0.35,
        hoverlabel: { namelength: -1 },
        hovertemplate:
          "O %{open:.4f}<br>H %{high:.4f}<br>L %{low:.4f}<br>C %{close:.4f}<br>%{x}<extra></extra>",
        xaxis: "x",
        yaxis: "y",
      };
    }

    return {
      type: "scatter",
      mode: "lines",
      name: "Prezzo",
      x: source.dates,
      y: source.market?.close || [],
      line: { color: "#7dd3fc", width: 2.3 },
      hovertemplate: "Close %{y:.4f}<br>%{x}<extra></extra>",
      xaxis: "x",
      yaxis: "y",
    };
  }

  function baseXAxis(axisName = "x") {
    return {
      domain: [0, 1],
      anchor: axisName === "x" ? "y" : axisName === "x2" ? "y2" : "y3",
      matches: axisName === "x" ? undefined : "x",
      showgrid: true,
      gridcolor: "rgba(171, 184, 214, 0.07)",
      zeroline: false,
      showspikes: true,
      spikemode: "across",
      spikecolor: "rgba(96, 165, 250, 0.42)",
      spikethickness: 1,
      tickfont: { color: "#8d98b2", size: 11 },
      fixedrange: false,
    };
  }

  function buildVolumeColors(source) {
    const close = source.market?.close || [];
    const open = source.market?.open || [];
    return (source.market?.volume || []).map((_, index) => {
      const currentClose = close[index];
      const currentOpen = open[index];
      const previousClose = index > 0 ? close[index - 1] : currentOpen;
      const reference = currentOpen ?? previousClose;
      return currentClose >= reference ? "rgba(38, 208, 168, 0.45)" : "rgba(255, 95, 115, 0.45)";
    });
  }

  function buildLatestPriceInfo(source) {
    const closes = source.market?.close || [];
    const dates = source.dates || [];
    if (!hasValues(closes) || dates.length === 0) {
      return { shape: null, annotation: null };
    }

    const latestIndex = closes.length - 1;
    const latestValue = closes[latestIndex];
    const previousValue = latestIndex > 0 ? closes[latestIndex - 1] : latestValue;
    const isUp = latestValue >= previousValue;
    const accent = isUp ? "#26d0a8" : "#ff5f73";

    return {
      shape: {
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y",
        y0: latestValue,
        y1: latestValue,
        line: { color: "rgba(255,255,255,0.1)", width: 1, dash: "dot" },
      },
      annotation: {
        xref: "paper",
        x: 1.01,
        xanchor: "left",
        yref: "y",
        y: latestValue,
        text: `${latestValue.toFixed(3)}`,
        showarrow: false,
        font: { color: "#041011", size: 11, family: "Aptos, sans-serif" },
        bgcolor: accent,
        bordercolor: accent,
        borderpad: 4,
      },
    };
  }

  function hasValues(values) {
    return Array.isArray(values) && values.some((value) => value !== null && value !== undefined);
  }

  function labelForState(value, labels) {
    return labels[value] || value;
  }
})();
