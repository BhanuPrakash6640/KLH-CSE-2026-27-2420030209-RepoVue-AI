import { useState } from "react";
import { ErrorBox } from "../components/States";
import { api, getApiKey, setApiKey } from "../lib/api";
import { useApi } from "../lib/hooks";

export function SettingsPage() {
  const [key, setKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);
  const health = useApi(() => api.health(), []);

  const save = () => {
    setApiKey(key);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
    health.reload();
  };

  return (
    <div className="rv-pad" style={{ maxWidth: 680, padding: "48px 32px 80px" }}>
      <h1 style={{ margin: 0, fontSize: 23, fontWeight: 600, letterSpacing: "-0.02em" }}>Settings</h1>
      <p style={{ margin: "8px 0 36px", color: "var(--ink-2)" }}>
        Stored in this browser only. Nothing here is sent anywhere except as the key on each API
        request.
      </p>

      <label style={{ display: "block", fontSize: 13, color: "var(--ink-2)", marginBottom: 7 }}>
        API key
        <input
          className="field"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          style={{ marginTop: 7, fontSize: 15, borderBottomColor: "var(--ink)" }}
        />
      </label>
      <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <button className="btn-primary" onClick={save}>
          Save key
        </button>
        {saved ? (
          <span className="mono" style={{ fontSize: 12, color: "var(--pass)" }}>
            Saved
          </span>
        ) : null}
      </div>
      <p className="mono" style={{ margin: "12px 0 0", fontSize: 12, color: "var(--ink-3)" }}>
        Must match one of the comma-separated values in the API's API_KEYS setting.
      </p>

      <h2 style={{ margin: "44px 0 12px", fontSize: 16, fontWeight: 600 }}>Service</h2>
      {health.error ? (
        <ErrorBox message={health.error} onRetry={health.reload} />
      ) : (
        <div style={{ borderTop: "1px solid var(--rule)" }}>
          {[
            { label: "status", value: health.data?.status ?? "…" },
            { label: "environment", value: health.data?.env ?? "…" },
            { label: "database", value: health.data?.database ?? "…" },
            {
              label: "model key",
              value: health.data ? (health.data.llm_configured ? "configured" : "missing") : "…",
              warn: health.data ? !health.data.llm_configured : false,
            },
            {
              label: "docker",
              value: health.data?.docker ?? "…",
              warn: health.data ? health.data.docker !== "ok" : false,
            },
            { label: "version", value: health.data?.version ?? "…" },
          ].map((row) => (
            <div
              key={row.label}
              style={{
                display: "grid",
                gridTemplateColumns: "160px 1fr",
                gap: 12,
                padding: "9px 0",
                borderBottom: "1px solid var(--rule-2)",
              }}
            >
              <span style={{ fontSize: 13, color: "var(--ink-3)" }}>{row.label}</span>
              <span
                className="mono"
                style={{ fontSize: 12.5, color: row.warn ? "var(--warn)" : "var(--ink)", wordBreak: "break-word" }}
              >
                {row.value}
              </span>
            </div>
          ))}
        </div>
      )}
      <p style={{ margin: "16px 0 0", fontSize: 13, color: "var(--ink-2)", maxWidth: "66ch" }}>
        Without a model key the pipeline still clones, indexes and embeds, but the review and patch
        stages are skipped. Without Docker, patches are written but never run against your tests,
        and every verdict reads "not validated".
      </p>
    </div>
  );
}
