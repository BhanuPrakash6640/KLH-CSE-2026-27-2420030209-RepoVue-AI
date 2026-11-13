import { useState } from "react";
import { useParams } from "react-router-dom";
import { Empty, ErrorBox } from "../components/States";
import { api, ApiError } from "../lib/api";
import { useAnnounceAnalysis } from "../lib/current";
import type { SearchHit } from "../lib/types";

const EXAMPLES = [
  "where do we build SQL by concatenation",
  "how are sessions issued",
  "retry logic around outbound payments",
];

export function SearchPage() {
  const { analysisId = "" } = useParams();
  useAnnounceAnalysis(analysisId);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tookMs, setTookMs] = useState<number | null>(null);

  const run = async (text: string) => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    const started = performance.now();
    try {
      const results = await api.search(analysisId, text.trim(), 10);
      setHits(results);
      setTookMs(Math.round(performance.now() - started));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setHits(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rv-pad" style={{ padding: "26px 32px 80px" }}>
      <h1 style={{ margin: 0, fontSize: 23, fontWeight: 600, letterSpacing: "-0.02em" }}>
        Search the analysed code
      </h1>
      <p style={{ margin: "7px 0 0", color: "var(--ink-2)", maxWidth: "70ch" }}>
        Meaning and exact text together, across the same index the review used. Ask in words or
        paste an identifier.
      </p>

      <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap", alignItems: "center" }}>
        <input
          className="field"
          value={query}
          placeholder="what are you looking for?"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void run(query)}
          style={{ flex: 1, minWidth: 280, fontSize: 15, padding: "11px 12px", borderBottomColor: "var(--ink)" }}
          aria-label="Search query"
        />
        <button className="btn-primary" disabled={busy || !query.trim()} onClick={() => void run(query)}>
          {busy ? "Searching…" : "Search"}
        </button>
        {tookMs !== null && hits ? (
          <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            {hits.length} hits · {tookMs} ms
          </span>
        ) : null}
      </div>

      {!hits && !error ? (
        <div style={{ marginTop: 26 }}>
          <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 10 }}>Try</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                className="btn"
                style={{ fontSize: 13 }}
                onClick={() => {
                  setQuery(example);
                  void run(example);
                }}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {error ? (
        <div style={{ marginTop: 26 }}>
          <ErrorBox
            message={error}
            hint="Search needs an embedded index. A run that skipped the embed stage has nothing to search."
          />
        </div>
      ) : null}

      {hits && hits.length === 0 ? (
        <Empty title="No matches in this run's index">
          <p style={{ margin: 0 }}>
            Try fewer words, or an identifier you know is in the code. The index only covers files
            this analysis walked.
          </p>
        </Empty>
      ) : null}

      {hits && hits.length > 0 ? (
        <div style={{ marginTop: 26 }}>
          {hits.map((hit, i) => (
            <article key={`${hit.path}:${hit.start_line}:${i}`} style={{ borderTop: "1px solid var(--rule)", padding: "14px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "baseline" }}>
                <span className="mono" style={{ fontSize: 13, wordBreak: "break-all" }}>
                  {hit.path}:{hit.start_line}–{hit.end_line}
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 60, height: 6, background: "var(--rule-2)", display: "inline-block", position: "relative" }}>
                    <span
                      style={{
                        position: "absolute",
                        inset: "0 auto 0 0",
                        width: `${Math.max(0, Math.min(100, hit.score * 100))}%`,
                        background: "var(--accent)",
                      }}
                    />
                  </span>
                  <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
                    {hit.score.toFixed(3)}
                  </span>
                </span>
              </div>
              <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 3 }}>
                {hit.symbol_name ?? "—"}
              </div>
              <pre
                className="mono"
                style={{
                  margin: "9px 0 0",
                  fontSize: 12.5,
                  lineHeight: 1.75,
                  background: "var(--sunk)",
                  padding: "10px 12px",
                  overflowX: "auto",
                  color: "var(--ink-2)",
                  maxHeight: 320,
                }}
              >
                {hit.content}
              </pre>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
