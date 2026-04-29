if (window.__calmsendLoaded) {
  console.debug("CalmSend already loaded on this page.");
} else {
  window.__calmsendLoaded = true;

const APP_CONFIG = [
  { id: "whatsapp", match: /web\.whatsapp\.com/, contentType: "chat" },
  { id: "instagram", match: /instagram\.com/, contentType: "chat" },
  { id: "gmail", match: /mail\.google\.com/, contentType: "email" },
  { id: "google_docs", match: /docs\.google\.com/, contentType: "document" },
];

function detectApp() {
  const host = window.location.hostname;
  return APP_CONFIG.find((item) => item.match.test(host)) || { id: "generic", contentType: "chat" };
}

function isEditable(element) {
  if (!element) {
    return false;
  }
  return (
    element.matches("textarea, input[type='text'], input[type='search']") ||
    element.isContentEditable ||
    element.getAttribute("role") === "textbox"
  );
}

function editableText(target) {
  return target.value ?? target.innerText ?? target.textContent ?? "";
}

async function fetchAppSettings(appId) {
  try {
    const response = await chrome.runtime.sendMessage({
      type: "CALMSEND_API_FETCH",
      path: "/api/settings",
      options: { method: "GET" },
    });
    if (!response?.ok || !response.result?.ok) {
      return { enabled: true, delay_mode: "smart", offline: true };
    }
    const data = JSON.parse(response.result.text);
    return data.linked_apps.find((item) => item.id === appId) || { enabled: true, delay_mode: "smart" };
  } catch (error) {
    return { enabled: true, delay_mode: "smart", offline: true };
  }
}

let activeTarget = null;
let latestRewrite = "";
let cooldownTimer = null;
let cooldownEndsAt = 0;
let lastAnalysis = null;
let analyzeTimeout = null;
let appSettings = { enabled: true, delay_mode: "smart" };
let hasAutoOpened = false;

function getDock() {
  return document.getElementById("calmsend-dock");
}

function createPanel() {
  const existing = getDock();
  if (existing) {
    return existing;
  }

  const panel = document.createElement("div");
  panel.id = "calmsend-dock";
  panel.className = "calmsend-panel";
  panel.style.position = "fixed";
  panel.style.right = "24px";
  panel.style.top = "92px";
  panel.style.zIndex = "2147483647";
  panel.innerHTML = `
    <button class="calmsend-fab" type="button">CalmSend</button>
    <div class="calmsend-popover" hidden>
      <div class="calmsend-header">
        <strong>CalmSend</strong>
        <span class="calmsend-app"></span>
      </div>
      <div class="calmsend-controls">
        <label>
          Delay
          <select class="calmsend-delay">
            <option value="light">Light</option>
            <option value="smart" selected>Smart</option>
            <option value="strict">Strict</option>
            <option value="off">Off</option>
          </select>
        </label>
      </div>
      <button class="calmsend-analyze" type="button">Analyze draft</button>
      <div class="calmsend-result">
        <div class="calmsend-metrics">
          <span>Emotion: waiting</span>
          <span>Risk: 0/100</span>
          <span>Delay: 0s</span>
        </div>
        <div class="calmsend-rewrite">Focus a message box, then analyze the draft.</div>
      </div>
      <button class="calmsend-apply" type="button" hidden>Apply rewrite</button>
    </div>
  `;

  const button = panel.querySelector(".calmsend-fab");
  const popover = panel.querySelector(".calmsend-popover");
  const result = panel.querySelector(".calmsend-result");
  const metrics = panel.querySelector(".calmsend-metrics");
  const rewrite = panel.querySelector(".calmsend-rewrite");
  const applyButton = panel.querySelector(".calmsend-apply");
  const analyzeButton = panel.querySelector(".calmsend-analyze");
  const delaySelect = panel.querySelector(".calmsend-delay");
  const appBadge = panel.querySelector(".calmsend-app");
  const app = detectApp();

  appBadge.textContent = app.id.replace("_", " ");

  async function syncSettings() {
    const linked = await fetchAppSettings(app.id);
    appSettings = linked;
    delaySelect.value = linked.delay_mode;
    panel.hidden = false;
    if (linked.offline) {
      rewrite.textContent = "CalmSend is visible. Start the local API before analyzing text.";
    }
  }

  async function analyzeDraft() {
    if (!(activeTarget instanceof HTMLElement)) {
      rewrite.textContent = "Click inside the message box first.";
      applyButton.hidden = true;
      return;
    }

    const draft = editableText(activeTarget);
    if (!draft.trim()) {
      metrics.innerHTML = "<span>Emotion: waiting</span><span>Risk: 0/100</span><span>Delay: 0s</span>";
      rewrite.textContent = "Type something first.";
      applyButton.hidden = true;
      lastAnalysis = null;
      cooldownEndsAt = 0;
      return;
    }
    rewrite.textContent = "Analyzing...";
    const response = await chrome.runtime.sendMessage({
      type: "CALMSEND_API_FETCH",
      path: "/api/analyze",
      options: {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: draft,
          recipient: "Recipient",
          source_app: app.id,
          content_type: app.contentType,
          delay_mode: delaySelect.value || appSettings.delay_mode,
        }),
      },
    });
    if (!response?.ok || !response.result?.ok) {
      throw new Error(response?.error || `API request failed with status ${response?.result?.status ?? "unknown"}`);
    }
    const data = JSON.parse(response.result.text);
    lastAnalysis = data;
    latestRewrite = data.rewritten_message;
    applyButton.hidden = false;
    const angerLevel = data.risk_score >= 80 ? "high" : data.risk_score >= 45 ? "medium" : "low";
    metrics.innerHTML = `
      <span>Emotion: ${angerLevel}</span>
      <span>Risk: ${data.risk_score}/100</span>
      <span>Delay: ${data.cooldown_seconds}s</span>
    `;
    rewrite.textContent = data.rewritten_message;
    if (cooldownTimer) {
      clearTimeout(cooldownTimer);
    }
    cooldownEndsAt = Date.now() + (data.cooldown_seconds * 1000);
    if (data.cooldown_seconds > 0) {
      disableLikelySendButtons(data.cooldown_seconds);
      cooldownTimer = setTimeout(enableLikelySendButtons, data.cooldown_seconds * 1000);
    }
  }

  function scheduleAnalysis() {
    if (analyzeTimeout) {
      clearTimeout(analyzeTimeout);
    }
    analyzeTimeout = setTimeout(() => {
      analyzeDraft().catch(() => {
        rewrite.textContent = "Could not analyze. Run the backend on http://127.0.0.1:8000, then try again.";
      });
    }, 450);
  }

  function remainingCooldown() {
    return Math.max(0, Math.ceil((cooldownEndsAt - Date.now()) / 1000));
  }

  button.addEventListener("click", () => {
    popover.hidden = !popover.hidden;
  });

  analyzeButton.addEventListener("click", () => {
    analyzeDraft().catch(() => {
      rewrite.textContent = "Could not analyze. Run the backend on http://127.0.0.1:8000, then try again.";
    });
  });

  applyButton.addEventListener("click", () => {
    if (!latestRewrite) {
      return;
    }
    if (!(activeTarget instanceof HTMLElement)) {
      return;
    }
    if ("value" in activeTarget) {
      activeTarget.value = latestRewrite;
      activeTarget.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    activeTarget.innerText = latestRewrite;
    activeTarget.dispatchEvent(new Event("input", { bubbles: true }));
  }, true);

  document.addEventListener(
    "input",
    (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !isEditable(target)) {
        return;
      }
      activeTarget = target;
    if (appSettings.enabled === false) {
        return;
      }
      scheduleAnalysis();
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !isEditable(target)) {
        return;
      }
      activeTarget = target;
      const enterSubmit = event.key === "Enter" && !event.shiftKey;
      const commandSubmit = event.key === "Enter" && (event.metaKey || event.ctrlKey);
      if (!enterSubmit && !commandSubmit) {
        return;
      }
      const remaining = remainingCooldown();
      const shouldBlock = remaining > 0 || lastAnalysis?.send_action === "rewrite_before_send";
      if (!shouldBlock) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      popover.hidden = false;
      rewrite.textContent =
        remaining > 0
          ? `Send blocked. Wait ${remaining}s or apply the calmer rewrite.`
          : "Send blocked. This draft needs a rewrite before it can be sent.";
    },
    true,
  );

  syncSettings();
  document.documentElement.appendChild(panel);
  return panel;
}

function openDock(message) {
  const dock = getDock();
  const popover = dock?.querySelector(".calmsend-popover");
  const rewrite = dock?.querySelector(".calmsend-rewrite");
  if (popover instanceof HTMLElement) {
    popover.hidden = false;
  }
  if (rewrite instanceof HTMLElement && message) {
    rewrite.textContent = message;
  }
}

function disableLikelySendButtons(seconds) {
  document.querySelectorAll("button, [role='button']").forEach((button) => {
    const text = (button.textContent || "").trim().toLowerCase();
    if (["send", "post", "reply"].includes(text)) {
      button.dataset.calmsendDisabled = "true";
      button.setAttribute("disabled", "disabled");
      button.setAttribute("title", `CalmSend hold: ${seconds}s`);
    }
  });
}

function enableLikelySendButtons() {
  document.querySelectorAll("[data-calmsend-disabled='true']").forEach((button) => {
    button.removeAttribute("disabled");
    button.removeAttribute("title");
    delete button.dataset.calmsendDisabled;
  });
}

function attachToEditable(element) {
  if (!isEditable(element)) {
    return;
  }
  activeTarget = element;
  createPanel();
  if (!hasAutoOpened) {
    hasAutoOpened = true;
    openDock("Connected to the active message box. Type a draft or click Analyze draft.");
  }
}

function scanForEditors(root = document) {
  root
    .querySelectorAll("textarea, input[type='text'], input[type='search'], [contenteditable], [role='textbox']")
    .forEach((element) => {
      if (element instanceof HTMLElement) {
        attachToEditable(element);
      }
    });
}

function findPreferredEditor() {
  const app = detectApp();
  const selectors = {
    whatsapp: [
      "div[contenteditable='true'][data-tab]",
      "footer div[contenteditable='true']",
      "div[role='textbox'][contenteditable='true']",
    ],
    instagram: [
      "div[contenteditable='true'][role='textbox']",
      "textarea",
    ],
    gmail: [
      "div[aria-label='Message Body']",
      "div[role='textbox'][g_editable='true']",
    ],
    google_docs: [
      "div[contenteditable='true']",
      "textarea",
    ],
  };
  const appSelectors = selectors[app.id] || [];
  for (const selector of appSelectors) {
    const match = document.querySelector(selector);
    if (match instanceof HTMLElement) {
      return match;
    }
  }
  const fallback = document.activeElement;
  if (fallback instanceof HTMLElement && isEditable(fallback)) {
    return fallback;
  }
  const anyEditable = document.querySelector("textarea, input[type='text'], input[type='search'], [contenteditable='true'], [role='textbox']");
  return anyEditable instanceof HTMLElement ? anyEditable : null;
}

document.addEventListener("focusin", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement) {
    attachToEditable(target);
  }
});

function boot() {
  createPanel();
  scanForEditors();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}

const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    mutation.addedNodes.forEach((node) => {
      if (node instanceof HTMLElement) {
        if (isEditable(node)) {
          attachToEditable(node);
        }
        scanForEditors(node);
      }
    });
  }
});

observer.observe(document.documentElement, { childList: true, subtree: true });
}
