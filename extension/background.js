const SUPPORTED_URLS = [
  "https://web.whatsapp.com/",
  "https://www.instagram.com/",
  "https://mail.google.com/",
  "https://docs.google.com/",
];

function isSupportedUrl(url = "") {
  return SUPPORTED_URLS.some((prefix) => url.startsWith(prefix));
}

async function injectCalmSend(tabId) {
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ["panel.css"],
    });
  } catch (error) {
    console.error("CalmSend CSS injection failed", error);
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
  } catch (error) {
    console.error("CalmSend script injection failed", error);
  }
}

async function proxyApiFetch(path, options = {}) {
  const stored = await chrome.storage.sync.get(["calmsendApiBase"]);
  const baseUrl = stored.calmsendApiBase || "http://127.0.0.1:8000";
  const response = await fetch(`${baseUrl}${path}`, options);
  const text = await response.text();
  return {
    ok: response.ok,
    status: response.status,
    text,
  };
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.set({
    calmsendApiBase: "http://127.0.0.1:8000",
    delayMode: "smart",
  });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && isSupportedUrl(tab.url || "")) {
    injectCalmSend(tabId);
  }
});

chrome.action.onClicked.addListener((tab) => {
  if (tab.id && isSupportedUrl(tab.url || "")) {
    injectCalmSend(tab.id);
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "CALMSEND_API_FETCH") {
    return undefined;
  }

  proxyApiFetch(message.path, message.options)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: String(error) }));

  return true;
});
