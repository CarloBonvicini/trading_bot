document.addEventListener("DOMContentLoaded", () => {
  const expandablePanels = Array.from(document.querySelectorAll("[data-expandable-panel]"));
  const backdrop = document.getElementById("panel-backdrop");
  let activePanel = null;

  function isInteractiveTarget(target) {
    return Boolean(target.closest("a, button, input, select, textarea, summary, [data-no-expand]"));
  }

  function closeActivePanel() {
    if (!activePanel) {
      return;
    }

    activePanel.classList.remove("is-expanded");
    activePanel.setAttribute("aria-expanded", "false");
    document.body.classList.remove("panel-expanded");
    backdrop.hidden = true;
    backdrop.classList.remove("is-visible");
    activePanel = null;
  }

  function openPanel(panel) {
    if (activePanel === panel) {
      return;
    }

    closeActivePanel();
    activePanel = panel;
    panel.classList.add("is-expanded");
    panel.setAttribute("aria-expanded", "true");
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
        const popup = window.open(
          detachedUrl,
          "_blank",
          "popup=yes,width=1480,height=960,resizable=yes,scrollbars=yes"
        );
        if (popup) {
          popup.focus();
        }
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
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeActivePanel();
    }
  });
});
