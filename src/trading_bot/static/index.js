const SYMBOL_CATALOG = [
  // Indici ETF
  { ticker: "QQQ",      name: "Nasdaq-100 ETF (CONSIGLIATO)",  category: "Indici ETF",      badge: "Consigliato" },
  { ticker: "SPY",      name: "S&P 500 ETF",                   category: "Indici ETF" },
  { ticker: "IWM",      name: "Russell 2000 ETF",              category: "Indici ETF" },
  { ticker: "DIA",      name: "Dow Jones Industrial ETF",      category: "Indici ETF" },
  { ticker: "VTI",      name: "US Total Market ETF",           category: "Indici ETF" },
  { ticker: "VOO",      name: "Vanguard S&P 500 ETF",          category: "Indici ETF" },
  // Azioni tech
  { ticker: "AAPL",     name: "Apple",                         category: "Azioni tech" },
  { ticker: "MSFT",     name: "Microsoft",                     category: "Azioni tech" },
  { ticker: "NVDA",     name: "NVIDIA",                        category: "Azioni tech" },
  { ticker: "GOOGL",    name: "Alphabet (Google)",             category: "Azioni tech" },
  { ticker: "AMZN",     name: "Amazon",                        category: "Azioni tech" },
  { ticker: "META",     name: "Meta Platforms",                category: "Azioni tech" },
  { ticker: "TSLA",     name: "Tesla",                         category: "Azioni tech" },
  // Azioni finanza / energia
  { ticker: "JPM",      name: "JPMorgan Chase",                category: "Azioni finanza" },
  { ticker: "GS",       name: "Goldman Sachs",                 category: "Azioni finanza" },
  { ticker: "XOM",      name: "ExxonMobil",                    category: "Azioni energia" },
  { ticker: "CVX",      name: "Chevron",                       category: "Azioni energia" },
  // Materie prime (futures yfinance)
  { ticker: "GC=F",     name: "Oro (futures)",                 category: "Materie prime" },
  { ticker: "CL=F",     name: "Petrolio WTI (futures)",        category: "Materie prime" },
  { ticker: "SI=F",     name: "Argento (futures)",             category: "Materie prime" },
  { ticker: "NG=F",     name: "Gas naturale (futures)",        category: "Materie prime" },
  // Crypto
  { ticker: "BTC-USD",  name: "Bitcoin",                       category: "Crypto" },
  { ticker: "ETH-USD",  name: "Ethereum",                      category: "Crypto" },
  { ticker: "SOL-USD",  name: "Solana",                        category: "Crypto" },
  // Forex
  { ticker: "EURUSD=X", name: "Euro / Dollaro USA",            category: "Forex" },
  { ticker: "GBPUSD=X", name: "Sterlina / Dollaro USA",        category: "Forex" },
  { ticker: "JPYUSD=X", name: "Yen giapponese / Dollaro USA",  category: "Forex" },
  // Obbligazioni ETF
  { ticker: "TLT",      name: "Treasury 20+ anni ETF",         category: "Obbligazioni" },
  { ticker: "AGG",      name: "US Aggregate Bond ETF",         category: "Obbligazioni" },
  { ticker: "IEF",      name: "Treasury 7-10 anni ETF",        category: "Obbligazioni" },
  // Internazionale
  { ticker: "EEM",      name: "Mercati emergenti ETF",         category: "Internazionale" },
  { ticker: "EFA",      name: "Mercati sviluppati ex-US ETF",  category: "Internazionale" },
];

function bindSymbolAutocomplete(inputEl, suggestionsEl) {
  if (!inputEl || !suggestionsEl) {
    return;
  }

  let activeIndex = -1;
  let currentItems = [];

  function matchesQuery(item, query) {
    const q = query.toLowerCase();
    return (
      item.ticker.toLowerCase().startsWith(q)
      || item.name.toLowerCase().includes(q)
      || item.ticker.toLowerCase().includes(q)
    );
  }

  function filterCatalog(query) {
    if (!query) {
      return SYMBOL_CATALOG.slice(0, 12);
    }
    const results = SYMBOL_CATALOG.filter((item) => matchesQuery(item, query));
    return results.slice(0, 16);
  }

  function buildSuggestionsHtml(items) {
    if (items.length === 0) {
      return '<div class="symbol-suggestion-item"><span class="symbol-suggestion-name">Nessun simbolo trovato</span></div>';
    }

    let html = "";
    let lastCategory = "";

    items.forEach((item) => {
      if (item.category !== lastCategory) {
        html += `<div class="symbol-suggestion-category">${item.category}</div>`;
        lastCategory = item.category;
      }
      const badge = item.badge ? `<span class="symbol-suggestion-badge">${item.badge}</span>` : "";
      html += `<div class="symbol-suggestion-item" data-ticker="${item.ticker}" tabindex="-1">
        <span class="symbol-suggestion-ticker">${item.ticker}</span>
        <span class="symbol-suggestion-name">${item.name}</span>
        ${badge}
      </div>`;
    });

    return html;
  }

  function renderSuggestions(query) {
    const items = filterCatalog(query);
    currentItems = items;
    activeIndex = -1;
    suggestionsEl.innerHTML = buildSuggestionsHtml(items);
    suggestionsEl.hidden = false;
  }

  function hideSuggestions() {
    suggestionsEl.hidden = true;
    activeIndex = -1;
    currentItems = [];
  }

  function selectTicker(ticker) {
    inputEl.value = ticker;
    inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    inputEl.dispatchEvent(new Event("change", { bubbles: true }));
    hideSuggestions();
    inputEl.focus();
  }

  function highlightActive() {
    const itemEls = Array.from(suggestionsEl.querySelectorAll(".symbol-suggestion-item[data-ticker]"));
    itemEls.forEach((el, idx) => {
      el.classList.toggle("is-active", idx === activeIndex);
    });
    if (activeIndex >= 0 && itemEls[activeIndex]) {
      itemEls[activeIndex].scrollIntoView({ block: "nearest" });
    }
  }

  inputEl.addEventListener("focus", () => {
    renderSuggestions(inputEl.value.trim());
  });

  inputEl.addEventListener("input", () => {
    renderSuggestions(inputEl.value.trim());
  });

  inputEl.addEventListener("keydown", (event) => {
    if (suggestionsEl.hidden) {
      return;
    }

    const itemEls = Array.from(suggestionsEl.querySelectorAll(".symbol-suggestion-item[data-ticker]"));

    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, itemEls.length - 1);
      highlightActive();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, -1);
      highlightActive();
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const ticker = itemEls[activeIndex]?.dataset.ticker;
      if (ticker) {
        selectTicker(ticker);
      }
    } else if (event.key === "Escape") {
      hideSuggestions();
    }
  });

  suggestionsEl.addEventListener("mousedown", (event) => {
    const item = event.target.closest(".symbol-suggestion-item[data-ticker]");
    if (item) {
      event.preventDefault();
      selectTicker(item.dataset.ticker);
    }
  });

  document.addEventListener("click", (event) => {
    if (!inputEl.contains(event.target) && !suggestionsEl.contains(event.target)) {
      hideSuggestions();
    }
  });
}

// ── Stato globale ──────────────────────────────────────────────────────────────
const homeUiState = {
  keydownBound: false,
  popstateBound: false,
  selectedSessionName: "",
};

// ── Utility navigazione ────────────────────────────────────────────────────────
function parseIndexConfig() {
  const configNode = document.getElementById("index-page-config");
  if (!configNode) {
    return null;
  }
  try {
    return JSON.parse(configNode.textContent);
  } catch {
    return null;
  }
}

function getHomeShell() {
  return document.querySelector("[data-home-tab-shell]");
}

function currentRelativeUrl() {
  return `${window.location.pathname}${window.location.search}`;
}

function normalizeRelativeUrl(rawUrl) {
  if (!rawUrl) {
    return "";
  }
  try {
    const resolved = new URL(rawUrl, window.location.origin);
    if (resolved.origin !== window.location.origin) {
      return "";
    }
    return `${resolved.pathname}${resolved.search}`;
  } catch {
    return "";
  }
}

function currentHomeTabFromView(viewName) {
  if (viewName === "results") {
    return "results";
  }
  if (viewName === "setup" || viewName === "strategies") {
    return "backtest";
  }
  return "dashboard";
}

function currentHomeTabFromLocation() {
  const pathname = window.location.pathname;
  if (pathname.startsWith("/history")) {
    return "results";
  }
  if (pathname.startsWith("/backtests/new") || pathname.startsWith("/strategies")) {
    return "backtest";
  }
  return "dashboard";
}

function routeForHomeTab(tabName, pageConfig) {
  const homeRoutes = pageConfig?.homeRoutes || {};
  if (tabName === "results") {
    return homeRoutes.results || "/history";
  }
  if (tabName === "backtest") {
    return homeRoutes.setup || "/backtests/new";
  }
  return homeRoutes.dashboard || "/";
}

// ── Sessioni workspace (tab Sessioni) ─────────────────────────────────────────
function renderSessionPreview(previewChart) {
  const chartNode = document.getElementById("session-preview-chart");
  const legendNode = document.getElementById("session-preview-legend");
  if (!chartNode || !previewChart) {
    return;
  }

  chartNode.setAttribute("viewBox", `0 0 ${previewChart.width} ${previewChart.height}`);
  chartNode.replaceChildren();
  legendNode?.replaceChildren();

  (previewChart.series || []).forEach((series) => {
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", series.points || "");
    polyline.setAttribute("stroke", series.color || "#3b82f6");
    polyline.setAttribute("fill", "none");
    polyline.setAttribute("stroke-width", "3");
    polyline.setAttribute("stroke-linecap", "round");
    polyline.setAttribute("stroke-linejoin", "round");
    chartNode.appendChild(polyline);

    if (legendNode) {
      const item = document.createElement("span");
      item.className = "mini-chart-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "mini-chart-legend-swatch";
      swatch.style.setProperty("--legend-color", series.color || "#3b82f6");
      item.append(swatch, series.label || "Serie");
      legendNode.appendChild(item);
    }
  });
}

function updateSessionWorkspace(pageConfig, sessionName, options = {}) {
  const { updateHistory = false } = options;
  const sessionItems = pageConfig?.sessionItems || [];
  const sessionItem = sessionItems.find((item) => item.name === sessionName) || sessionItems[0];
  if (!sessionItem) {
    return;
  }

  homeUiState.selectedSessionName = sessionItem.name;

  document.querySelectorAll("[data-session-selector]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.sessionSelector === sessionItem.name);
  });

  const summaryCard = document.getElementById("session-summary-card");
  summaryCard?.setAttribute("data-tone", sessionItem.tone || "neutral");

  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => {
    const node = byId(id);
    if (node) {
      node.textContent = value || "";
    }
  };

  setText("session-artifact-label", sessionItem.artifact_label);
  setText("session-title", sessionItem.title);
  setText("session-subtitle", sessionItem.subtitle);
  setText("session-stage-artifact", sessionItem.artifact_label);
  setText("session-stage-created", sessionItem.created_at_display);
  setText("session-metric-label", sessionItem.list_metric_label);
  setText("session-metric-value", sessionItem.list_metric);
  setText("session-period-label", sessionItem.period_label);
  setText("session-interval-label", `timeframe ${sessionItem.interval}`);
  setText("session-created-at", sessionItem.created_at_display);
  setText("session-description-interval", `timeframe ${sessionItem.interval}`);
  setText("session-description", sessionItem.description);
  setText("session-description-period", sessionItem.period_label);
  setText("session-description-created", sessionItem.created_at_display);
  setText("session-analytics-count", `${(sessionItem.metrics || []).length} metriche`);

  const openLink = byId("session-open-link");
  if (openLink) {
    openLink.textContent = sessionItem.open_label;
    openLink.setAttribute("href", sessionItem.open_url);
  }

  const resumeLink = byId("session-resume-link");
  if (resumeLink) {
    const hasResume = Boolean(sessionItem.resume_url);
    resumeLink.classList.toggle("is-hidden", !hasResume);
    resumeLink.setAttribute("href", hasResume ? sessionItem.resume_url : "#");
  }

  const metricsGrid = byId("session-metrics-grid");
  if (metricsGrid) {
    metricsGrid.replaceChildren();
    (sessionItem.metrics || []).forEach((metric) => {
      const article = document.createElement("article");
      article.className = "home-session-metric";
      const label = document.createElement("span");
      label.textContent = metric.label || "";
      const value = document.createElement("strong");
      value.textContent = metric.value || "";
      article.append(label, value);
      metricsGrid.appendChild(article);
    });
  }

  renderSessionPreview(sessionItem.preview_chart);

  if (updateHistory) {
    const nextUrl = `/history?session=${encodeURIComponent(sessionItem.name)}`;
    history.replaceState({ homeTab: "results" }, "", nextUrl);
  }
}

// ── Navigazione tab ────────────────────────────────────────────────────────────
function activateHomeTab(tabName, pageConfig, options = {}) {
  const { updateHistory = false, explicitRoute = "" } = options;
  const nextTab = ["dashboard", "backtest", "results"].includes(tabName) ? tabName : "dashboard";
  const route = normalizeRelativeUrl(explicitRoute || routeForHomeTab(nextTab, pageConfig));

  document.querySelectorAll("[data-home-tab-button]").forEach((button) => {
    const isActive = button.dataset.homeTabButton === nextTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  document.querySelectorAll("[data-home-panel]").forEach((panel) => {
    const isActive = panel.dataset.homePanel === nextTab;
    panel.hidden = !isActive;
    panel.classList.toggle("is-active", isActive);
  });

  if (updateHistory && route && route !== currentRelativeUrl()) {
    history.pushState({ homeTab: nextTab }, "", route);
  }
}

function bindGlobalHomeListeners(pageConfig) {
  if (!homeUiState.popstateBound) {
    window.addEventListener("popstate", () => {
      if (!getHomeShell()) {
        return;
      }
      activateHomeTab(currentHomeTabFromLocation(), pageConfig, { updateHistory: false });
      const selectedSessionFromUrl = new URLSearchParams(window.location.search).get("session") || homeUiState.selectedSessionName;
      updateSessionWorkspace(pageConfig, selectedSessionFromUrl, { updateHistory: false });
    });
    homeUiState.popstateBound = true;
  }

  if (!history.state || !history.state.homeTab) {
    history.replaceState({ homeTab: currentHomeTabFromView(pageConfig?.currentHomeView) }, "", currentRelativeUrl());
  }
}

function bindHomeShellNavigation(pageConfig) {
  const shell = getHomeShell();
  if (!shell) {
    return;
  }

  const shellControls = Array.from(shell.querySelectorAll("[data-home-tab-button], [data-home-tab-trigger]"));

  shellControls.forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      const requestedTab = control.dataset.homeTabButton || control.dataset.homeTabTrigger || "dashboard";
      const normalizedTab = (requestedTab === "setup" || requestedTab === "strategies")
        ? "backtest"
        : (["dashboard", "backtest", "results"].includes(requestedTab) ? requestedTab : "dashboard");
      const explicitRoute = control.dataset.homeTabRoute || routeForHomeTab(normalizedTab, pageConfig);
      activateHomeTab(normalizedTab, pageConfig, { updateHistory: true, explicitRoute });
    });
  });
}

function bindSessionWorkspace(pageConfig) {
  const selectors = Array.from(document.querySelectorAll("[data-session-selector]"));
  if (selectors.length === 0) {
    return;
  }
  selectors.forEach((button) => {
    button.addEventListener("click", () => {
      const openUrl = button.dataset.sessionOpenUrl || "";
      if (openUrl) {
        window.location.assign(openUrl);
        return;
      }
      updateSessionWorkspace(pageConfig, button.dataset.sessionSelector || "", { updateHistory: true });
    });
  });
}

// ── Form backtest semplificato ─────────────────────────────────────────────────
// Il form raccoglie solo: simbolo, date, timeframe, strategia iniziale,
// capitale, fee e preset. Tutta la configurazione avanzata avviene nel
// Strategy Lab della finestra grafico (chart_window.html).
function setupStrategyWorkspace(pageConfig) {
  const presetData = pageConfig?.strategyPresets || [];
  const intervalHints = pageConfig?.intervalHints || {};
  const intervalLookbackDays = pageConfig?.intervalLookbackDays || {};
  const presetsById = Object.fromEntries(presetData.map((preset) => [preset.id, preset]));

  const backtestForm = document.getElementById("backtest-form");
  const symbolInput = document.getElementById("symbol-input");
  const startInput = backtestForm?.querySelector('[name="start"]');
  const endInput = backtestForm?.querySelector('[name="end"]');
  const intervalSelect = document.getElementById("setup-interval-select");
  const initialCapitalInput = backtestForm?.querySelector('[name="initial_capital"]');
  const feeBpsInput = backtestForm?.querySelector('[name="fee_bps"]');
  const presetSelect = document.getElementById("setup-preset-select");
  const intervalHint = document.getElementById("interval-hint");
  const intervalAutoAdjustNote = document.getElementById("interval-auto-adjust-note");

  // ── Utility ──────────────────────────────────────────────────────────────────
  function namedFields(fieldName) {
    return Array.from(document.getElementsByName(fieldName));
  }

  function setNamedFieldValue(fieldName, value) {
    namedFields(fieldName).forEach((field) => {
      if (field.type === "checkbox" || field.type === "radio") {
        return;
      }
      field.value = value;
    });
  }

  // ── Hint intervallo ───────────────────────────────────────────────────────────
  function syncIntervalHint() {
    if (!intervalHint || !intervalSelect) {
      return;
    }
    intervalHint.textContent = intervalHints[intervalSelect.value] || "";
  }

  // ── Finestra date per intervalli intraday ─────────────────────────────────────
  function parseDateInputValue(value) {
    const rawValue = String(value || "").trim();
    if (!rawValue) {
      return null;
    }
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(rawValue);
    if (!match) {
      return null;
    }
    const parsed = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    parsed.setHours(0, 0, 0, 0);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatDateInputValue(dateValue) {
    const year = dateValue.getFullYear();
    const month = String(dateValue.getMonth() + 1).padStart(2, "0");
    const day = String(dateValue.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function resolveAllowedDateWindow(intervalValue) {
    const lookbackDays = Number(intervalLookbackDays[intervalValue]);
    if (!Number.isFinite(lookbackDays) || lookbackDays <= 0) {
      return null;
    }
    const referenceNow = new Date();
    const latestEnd = new Date(referenceNow.getFullYear(), referenceNow.getMonth(), referenceNow.getDate());
    const oldestAllowed = new Date(referenceNow.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
    const earliestStart = new Date(oldestAllowed.getFullYear(), oldestAllowed.getMonth(), oldestAllowed.getDate());
    if (
      oldestAllowed.getHours() !== 0
      || oldestAllowed.getMinutes() !== 0
      || oldestAllowed.getSeconds() !== 0
      || oldestAllowed.getMilliseconds() !== 0
    ) {
      earliestStart.setDate(earliestStart.getDate() + 1);
    }
    if (earliestStart >= latestEnd) {
      earliestStart.setDate(latestEnd.getDate() - 1);
    }
    return {
      lookbackDays,
      startDate: earliestStart,
      endDate: latestEnd,
      startValue: formatDateInputValue(earliestStart),
      endValue: formatDateInputValue(latestEnd),
    };
  }

  function setIntervalAutoAdjustMessage(message = "") {
    if (!intervalAutoAdjustNote) {
      return;
    }
    intervalAutoAdjustNote.textContent = message;
    intervalAutoAdjustNote.classList.toggle("is-hidden", !message);
  }

  function syncIntervalDateWindow(options = {}) {
    const { announce = false } = options;
    if (!intervalSelect || !startInput || !endInput) {
      return false;
    }
    const allowedWindow = resolveAllowedDateWindow(intervalSelect.value);
    if (!allowedWindow) {
      startInput.removeAttribute("min");
      startInput.removeAttribute("max");
      endInput.removeAttribute("min");
      endInput.removeAttribute("max");
      setIntervalAutoAdjustMessage("");
      return false;
    }
    startInput.min = allowedWindow.startValue;
    startInput.max = allowedWindow.endValue;
    endInput.min = allowedWindow.startValue;
    endInput.max = allowedWindow.endValue;

    const currentStart = parseDateInputValue(startInput.value);
    const currentEnd = parseDateInputValue(endInput.value);
    const needsAdjustment = !currentStart
      || !currentEnd
      || currentStart < allowedWindow.startDate
      || currentEnd > allowedWindow.endDate
      || currentEnd <= currentStart;

    if (!needsAdjustment) {
      setIntervalAutoAdjustMessage("");
      return false;
    }
    startInput.value = allowedWindow.startValue;
    endInput.value = allowedWindow.endValue;
    if (announce) {
      setIntervalAutoAdjustMessage(
        `Date aggiornate automaticamente su ${allowedWindow.startValue} → ${allowedWindow.endValue} per il timeframe ${intervalSelect.value}.`,
      );
    }
    return true;
  }

  // ── Applica preset ────────────────────────────────────────────────────────────
  function applyPreset(presetId) {
    const preset = presetsById[presetId];
    if (!preset) {
      return;
    }

    if (intervalSelect) {
      intervalSelect.value = preset.interval || intervalSelect.value;
    }

    const presetStrategyIds = preset.active_strategy_ids
      || (preset.active_rules || []).map((rule) => rule.strategy)
      || [preset.strategy].filter(Boolean);

    const strategySelect = backtestForm?.querySelector('[name="active_strategies"]');
    if (strategySelect && presetStrategyIds[0]) {
      strategySelect.value = presetStrategyIds[0];
    }

    setNamedFieldValue("preset_name", preset.name);
    if (initialCapitalInput) {
      initialCapitalInput.value = preset.initial_capital;
    }
    if (feeBpsInput) {
      feeBpsInput.value = preset.fee_bps;
    }

    const parameterGroups = preset.parameters_by_strategy || { [preset.strategy]: preset.parameters || {} };
    Object.entries(parameterGroups).forEach(([strategyId, parameters]) => {
      Object.entries(parameters || {}).forEach(([parameterName, parameterValue]) => {
        setNamedFieldValue(`${strategyId}__${parameterName}`, parameterValue);
      });
    });

    Object.entries(preset.sweep_settings || {}).forEach(([fieldName, fieldValue]) => {
      setNamedFieldValue(fieldName, fieldValue);
    });

    syncIntervalDateWindow({ announce: true });
    syncIntervalHint();
  }

  // ── Binding eventi ────────────────────────────────────────────────────────────
  presetSelect?.addEventListener("change", (event) => applyPreset(event.target.value));

  intervalSelect?.addEventListener("change", () => {
    syncIntervalDateWindow({ announce: true });
    syncIntervalHint();
  });

  backtestForm?.addEventListener("submit", () => {
    syncIntervalDateWindow({ announce: false });
  });

  // ── Inizializzazione ──────────────────────────────────────────────────────────
  syncIntervalDateWindow({ announce: false });
  syncIntervalHint();
  bindSymbolAutocomplete(
    document.getElementById("symbol-input"),
    document.getElementById("symbol-suggestions"),
  );
}

// ── Entry point ────────────────────────────────────────────────────────────────
function mountHomePage() {
  const pageConfig = parseIndexConfig();
  if (!pageConfig) {
    return;
  }

  homeUiState.selectedSessionName = pageConfig.selectedSessionName || "";
  activateHomeTab(currentHomeTabFromView(pageConfig.currentHomeView), pageConfig, { updateHistory: false });

  bindGlobalHomeListeners(pageConfig);
  bindHomeShellNavigation(pageConfig);
  bindSessionWorkspace(pageConfig);
  updateSessionWorkspace(pageConfig, homeUiState.selectedSessionName, { updateHistory: false });
  setupStrategyWorkspace(pageConfig);
}

document.addEventListener("DOMContentLoaded", mountHomePage);
