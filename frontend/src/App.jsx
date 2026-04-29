import { useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const INITIAL_MESSAGE =
  "I am really upset about how that meeting went, but I want to explain it better before I send this.";
const CONNECTOR_CARDS = [
  { id: "whatsapp", name: "WhatsApp", category: "Chat", tone: "Live messaging hold", launchUrl: "https://web.whatsapp.com/" },
  { id: "instagram", name: "Instagram", category: "Social", tone: "DM and comment scan", launchUrl: "https://www.instagram.com/direct/inbox/" },
  { id: "gmail", name: "Gmail", category: "Email", tone: "Strict send review", launchUrl: "https://mail.google.com/" },
  { id: "google_docs", name: "Google Docs", category: "Docs", tone: "Comment and doc note guard", launchUrl: "https://docs.google.com/" },
  { id: "generic", name: "Any website", category: "Universal", tone: "Editable field fallback", launchUrl: "https://www.google.com/" },
];
const DELAY_OPTIONS = [
  { id: "off", label: "Off" },
  { id: "light", label: "Light" },
  { id: "smart", label: "Smart" },
  { id: "strict", label: "Strict" },
];
const CONTENT_TYPES = ["chat", "comment", "email", "document", "search", "reply"];

function formatCooldown(seconds) {
  if (seconds <= 0) {
    return "Send now";
  }
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins > 0) {
    return `${mins}m ${secs.toString().padStart(2, "0")}s cooldown`;
  }
  return `${secs}s cooldown`;
}

export default function App() {
  const [recipient, setRecipient] = useState("Jordan");
  const [message, setMessage] = useState(INITIAL_MESSAGE);
  const [sourceApp, setSourceApp] = useState("whatsapp");
  const [contentType, setContentType] = useState("chat");
  const [delayMode, setDelayMode] = useState("smart");
  const [result, setResult] = useState(null);
  const [settings, setSettings] = useState(null);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [timeLeft, setTimeLeft] = useState(0);
  const deadlineRef = useRef(0);

  useEffect(() => {
    if (!deadlineRef.current) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((deadlineRef.current - Date.now()) / 1000));
      setTimeLeft(remaining);
      if (remaining === 0) {
        window.clearInterval(timer);
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [result]);

  useEffect(() => {
    async function loadSettings() {
      try {
        const response = await fetch(`${API_BASE}/api/settings`);
        if (!response.ok) {
          throw new Error("Settings request failed");
        }
        const data = await response.json();
        setSettings(data);
      } catch (err) {
        console.error(err);
      }
    }
    loadSettings();
  }, []);

  async function analyzeMessage() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, recipient, source_app: sourceApp, content_type: contentType, delay_mode: delayMode }),
      });
      if (!response.ok) {
        throw new Error("Backend request failed");
      }
      const data = await response.json();
      deadlineRef.current = Date.now() + data.cooldown_seconds * 1000;
      setTimeLeft(data.cooldown_seconds);
      setResult(data);
    } catch (err) {
      setError("Start the Python API on port 8000 before analyzing messages.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  function applyRewrite() {
    if (result?.rewritten_message) {
      setMessage(result.rewritten_message);
    }
  }

  async function saveLinkedApps(nextSettings) {
    setSettingsSaving(true);
    try {
      const response = await fetch(`${API_BASE}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextSettings),
      });
      if (!response.ok) {
        throw new Error("Settings save failed");
      }
      const data = await response.json();
      setSettings(data);
    } catch (err) {
      setError("Could not save linked app settings.");
      console.error(err);
    } finally {
      setSettingsSaving(false);
    }
  }

  function toggleLinkedApp(appId) {
    if (!settings) {
      return;
    }
    const nextSettings = {
      ...settings,
      linked_apps: settings.linked_apps.map((item) =>
        item.id === appId ? { ...item, enabled: !item.enabled } : item,
      ),
    };
    saveLinkedApps(nextSettings);
  }

  function updateLinkedDelay(appId, nextDelay) {
    if (!settings) {
      return;
    }
    const nextSettings = {
      ...settings,
      linked_apps: settings.linked_apps.map((item) =>
        item.id === appId ? { ...item, delay_mode: nextDelay } : item,
      ),
    };
    saveLinkedApps(nextSettings);
  }

  function ensureLinkedState(appId) {
    if (!settings) {
      return { enabled: false, delay_mode: "smart" };
    }
    return settings.linked_apps.find((item) => item.id === appId) ?? { enabled: false, delay_mode: "smart" };
  }

  const displayCooldown = result ? formatCooldown(timeLeft) : "No scan yet";

  return (
    <div className="page-shell">
      <div className="aurora aurora-a" />
      <div className="aurora aurora-b" />
      <main className="layout">
        <section className="hero-card">
          <p className="eyebrow">Cross-app emotional writing copilot</p>
          <h1>CalmSend works like a Grammarly-style safety layer for every send box.</h1>
          <p className="lede">
            Route the same engine across WhatsApp, Instagram, Gmail, Google Docs, and any editable
            field the extension sees. CalmSend scores tone, delays risky sends, and offers a calmer
            rewrite before the message leaves your keyboard.
          </p>
          <div className="stats-row">
            <article>
              <span>Scoring stack</span>
              <strong>Hybrid word + character TF-IDF ensemble</strong>
            </article>
            <article>
              <span>Coverage</span>
              <strong>Chats, comments, docs, email, search boxes</strong>
            </article>
            <article>
              <span>Status</span>
              <strong>{displayCooldown}</strong>
            </article>
          </div>
        </section>

        <section className="integration-strip">
          {CONNECTOR_CARDS.map((connector) => (
            <button
              key={connector.id}
              className={`integration-card ${sourceApp === connector.id ? "selected" : ""}`}
              onClick={() => setSourceApp(connector.id)}
            >
              <span>{connector.category}</span>
              <strong>{connector.name}</strong>
              <small>{connector.tone}</small>
            </button>
          ))}
        </section>

        <section className="linked-apps-card">
          <div className="section-heading">
            <h2>Linked apps</h2>
            <span>{settingsSaving ? "Saving..." : "Saved settings power the extension"}</span>
          </div>
          <p className="lede compact">
            Link an app once here, keep the extension installed, and CalmSend can work directly
            inside the app editor without reopening this website every time.
          </p>
          <div className="linked-grid">
            {CONNECTOR_CARDS.filter((card) => card.id !== "generic").map((connector) => {
              const linked = ensureLinkedState(connector.id);
              return (
                <article key={connector.id} className={`linked-tile ${linked?.enabled ? "enabled" : ""}`}>
                  <div>
                    <strong>{connector.name}</strong>
                    <span>{linked.enabled ? "Connected and ready in the extension" : "Not connected yet"}</span>
                  </div>
                  <div className="linked-actions">
                    <button type="button" className="ghost" onClick={() => toggleLinkedApp(connector.id)}>
                      {linked.enabled ? "Disconnect" : "Connect"}
                    </button>
                    <a className="open-link" href={connector.launchUrl} target="_blank" rel="noreferrer">
                      Open {connector.name}
                    </a>
                  </div>
                  <select
                    value={linked.delay_mode ?? "smart"}
                    onChange={(event) => updateLinkedDelay(connector.id, event.target.value)}
                  >
                    {DELAY_OPTIONS.filter((item) => item.id !== "off").map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label} delay
                      </option>
                    ))}
                  </select>
                </article>
              );
            })}
          </div>
        </section>

        <section className="panel-grid">
          <article className="composer-card">
            <div className="section-heading">
              <h2>Universal composer guard</h2>
              <span>{sourceApp.replace("_", " ")}</span>
            </div>

            <label>
              Recipient
              <input value={recipient} onChange={(event) => setRecipient(event.target.value)} />
            </label>

            <div className="field-row">
              <label>
                Source app
                <select value={sourceApp} onChange={(event) => setSourceApp(event.target.value)}>
                  {CONNECTOR_CARDS.map((connector) => (
                    <option key={connector.id} value={connector.id}>
                      {connector.name}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Content type
                <select value={contentType} onChange={(event) => setContentType(event.target.value)}>
                  {CONTENT_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label>
              Delay option
              <div className="delay-toggle">
                {DELAY_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={`chip ${delayMode === option.id ? "active" : ""}`}
                    onClick={() => setDelayMode(option.id)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </label>

            <label>
              Draft message
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={10}
              />
            </label>

            <div className="actions">
              <button onClick={analyzeMessage} disabled={loading || !message.trim()}>
                {loading ? "Scanning..." : "Analyze message"}
              </button>
              <button className="ghost" onClick={applyRewrite} disabled={!result?.rewritten_message}>
                Use calmer rewrite
              </button>
            </div>
            {error ? <p className="error-text">{error}</p> : null}
          </article>

          <article className={`result-card ${result?.label ?? "idle"}`}>
            <div className="section-heading">
              <h2>Risk readout</h2>
              <span>{result ? `${result.label.replace("_", " ")} · ${result.send_action.replaceAll("_", " ")}` : "Waiting"}</span>
            </div>

            {result ? (
              <>
                <div className="pill-row">
                  <span className="pill">Confidence {Math.round(result.confidence * 100)}%</span>
                  <span className="pill">Accuracy {Math.round(result.model_accuracy * 100)}%</span>
                  <span className="pill">Risk score {result.risk_score}/100</span>
                  <span className="pill">Anger level {result.risk_score >= 80 ? "High" : result.risk_score >= 45 ? "Medium" : "Low"}</span>
                  <span className="pill">{formatCooldown(timeLeft)}</span>
                </div>

                <div className="reason-block">
                  <h3>Why CalmSend flagged it</h3>
                  <ul>
                    {result.reasoning.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="rewrite-block">
                  <h3>Suggested rewrite</h3>
                  <p>{result.rewritten_message}</p>
                </div>

                <div className="rewrite-block">
                  <h3>Blocked actions</h3>
                  <p>
                    {result.blocked_features.length > 0
                      ? result.blocked_features.join(", ").replaceAll("_", " ")
                      : "No send controls are blocked for this draft."}
                  </p>
                </div>
              </>
            ) : (
              <p className="placeholder-copy">
                Run an analysis to see app-aware risk scoring, blocked send actions, cooldown timing,
                and a calmer rewrite.
              </p>
            )}
          </article>
        </section>

        <section className="extension-card">
          <div>
            <p className="eyebrow">Extension mode</p>
            <h2>Attach CalmSend to real compose boxes.</h2>
          </div>
          <p>
            Load the browser extension from the `extension` folder once. After that, the linked app
            settings saved here are used directly inside supported editors, so you do not need this
            website open while typing in WhatsApp, Instagram, Gmail, or Google Docs.
          </p>
          <p>
            `Connect` saves CalmSend for that app. `Open` launches the actual app website where the
            extension will appear in the editor.
          </p>
        </section>
      </main>
    </div>
  );
}
