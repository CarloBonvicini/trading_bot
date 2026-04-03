document.addEventListener("DOMContentLoaded", () => {
  const expandablePanels = Array.from(document.querySelectorAll("[data-expandable-panel]"));
  const backdrop = document.getElementById("panel-backdrop");
  let activePanel = null;
  const EXPANDED_PANEL_GAP = 16;
  const EXPANDED_PANEL_GAP_COMPACT = 8;

  function isInteractiveTarget(target) {
    return Boolean(
      target.closest(
        "a, button, input, label, select, textarea, summary, [data-no-expand], [data-strategy-toggle-card], [data-chart-strategy-card]",
      ),
    );
  }

  function applyExpandedLayout(panel) {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const safeGap = viewportWidth <= 980 || viewportHeight <= 760
      ? EXPANDED_PANEL_GAP_COMPACT
      : EXPANDED_PANEL_GAP;

    panel.style.inset = `${safeGap}px`;
    panel.style.width = "auto";
    panel.style.height = "auto";
    panel.style.maxWidth = "none";
    panel.style.maxHeight = "none";
    panel.style.left = "";
    panel.style.top = "";
    panel.style.right = "";
    panel.style.bottom = "";
    panel.style.transform = "none";
  }

  function clearExpandedLayout(panel) {
    panel.style.inset = "";
    panel.style.width = "";
    panel.style.height = "";
    panel.style.maxWidth = "";
    panel.style.maxHeight = "";
    panel.style.left = "";
    panel.style.top = "";
    panel.style.right = "";
    panel.style.bottom = "";
    panel.style.transform = "";
  }

  function closeActivePanel() {
    if (!activePanel) {
      return;
    }

    clearExpandedLayout(activePanel);
    activePanel.classList.remove("is-expanded");
    activePanel.setAttribute("aria-expanded", "false");
    document.body.classList.remove("panel-expanded");
    backdrop.hidden = true;
    backdrop.classList.remove("is-visible");
    activePanel = null;
  }

  function openDetachedInTab(detachedUrl) {
    const link = document.createElement("a");
    link.href = detachedUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.dataset.noExpand = "true";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function openPanel(panel) {
    if (activePanel === panel) {
      return;
    }

    closeActivePanel();
    activePanel = panel;
    panel.classList.add("is-expanded");
    panel.setAttribute("aria-expanded", "true");
    applyExpandedLayout(panel);
    panel.scrollTop = 0;
    document.body.classList.add("panel-expanded");
    backdrop.hidden = false;
    requestAnimationFrame(() => backdrop.classList.add("is-visible"));
  }

  expandablePanels.forEach((panel) => {
    panel.setAttribute("aria-expanded", "false");
    const detachedUrl = panel.dataset.detachedUrl;
    panel.setAttribute("title", detachedUrl ? "Clicca per aprire il chart avanzato" : "Clicca per espandere");

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "panel-expand-close";
    closeButton.dataset.noExpand = "true";
    closeButton.setAttribute("aria-label", "Chiudi pannello espanso");
    closeButton.textContent = "Chiudi";
    closeButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeActivePanel();
    });
    panel.appendChild(closeButton);

    panel.addEventListener("click", (event) => {
      if (isInteractiveTarget(event.target)) {
        return;
      }

      if (detachedUrl) {
        openDetachedInTab(detachedUrl);
        return;
      }

      if (panel.classList.contains("is-expanded")) {
        closeActivePanel();
        return;
      }

      openPanel(panel);
    });
  });

  backdrop.addEventListener("click", closeActivePanel);
  window.addEventListener("resize", () => {
    if (activePanel) {
      applyExpandedLayout(activePanel);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeActivePanel();
    }
  });
});
