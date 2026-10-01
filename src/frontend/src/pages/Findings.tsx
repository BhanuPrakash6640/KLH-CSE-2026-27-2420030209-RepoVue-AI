import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Meter, SeverityBadge } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/States";
import { api } from "../lib/api";
import { categoryLabel, cite, findingStatus, num, sev, SEVERITY_ORDER } from "../lib/format";
import { useAnnounceAnalysis } from "../lib/current";
import { useApi, useKeyboard } from "../lib/hooks";
import type { Finding } from "../lib/types";

const COLUMNS = "66px 34px minmax(0,1.7fr) minmax(0,2.1fr) minmax(0,1.2fr) 60px 108px";
const PAGE = 14;

export function FindingsPage() {
  const { analysisId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  useAnnounceAnalysis(analysisId);

  const severity = params.get("severity") ?? "";
  const category = params.get("category") ?? "";
  const path = params.get("path") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [selected, setSelected] = useState(0);
  const [pending, setPending] = useState<string | null>(null);

  // Typing filters the list, but only once the reviewer stops typing — one
  // request per keystroke is noise the API does not need.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        if (query) next.set("q", query);
        else next.delete("q");
        next.delete("offset");
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const q = params.get("q") ?? "";
  const { data, error, initial, reload } = useApi(
    () =>
      api.findings({
        analysis_id: analysisId,
        severity: severity || undefined,
        category: category || undefined,
        path: path || undefined,
        q: q || undefined,
        limit: PAGE,
        offset,
      }),
    [analysisId, severity, category, path, q, offset],
  );

  const items = useMemo(() => data?.items ?? [], [data]);

  useEffect(() => {
    setSelected(0);
  }, [severity, category, path, q, offset]);

  /** Chips toggle: clicking the active one clears it. Changing any filter
   *  returns to the first page, since page 3 of the old result set is
   *  meaningless against the new one. */
  const setFilter = (key: string, value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value && next.get(key) !== value) next.set(key, value);
      else next.delete(key);
      next.delete("offset");
      return next;
    });

  const goToOffset = (value: number) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value > 0) next.set("offset", String(value));
      else next.delete("offset");
      return next;
    });

  const markFalsePositive = async (finding: Finding) => {
    setPending(finding.id);
    try {
      await api.updateFinding(finding.id, "false_positive");
      reload();
    } finally {
      setPending(null);
    }
  };

  useKeyboard((event) => {
    if (items.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "j") {
      event.preventDefault();
      setSelected((i) => Math.min(i + 1, items.length - 1));
    } else if (event.key === "ArrowUp" || event.key === "k") {
      event.preventDefault();
      setSelected((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      navigate(`/findings/${items[selected].id}`);
    } else if (event.key === "f") {
      event.preventDefault();
      void markFalsePositive(items[selected]);
    }
  });

  const totalCount = data?.total ?? 0;
  const from = totalCount === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, totalCount);

  return (
    <div>
      <header className="rv-pad" style={{ padding: "22px 32px 14px", borderBottom: "1px solid var(--rule)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 20, flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>Findings</h1>
          <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            {from}–{to} of {num(totalCount)} · ↑↓ to move · enter to open · f to mark false positive
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
          <input
            className="field-boxed"
            placeholder="Search title"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: 260 }}
            aria-label="Search findings by title"
          />
          {SEVERITY_ORDER.map((key) => (
            <Chip
              key={key}
              label={sev(key).label}
              active={severity === key}
              onClick={() => setFilter("severity", key)}
            />
          ))}
          {["logical_bug", "security", "performance", "architecture"].map((key) => (
            <Chip
              key={key}
              label={categoryLabel(key)}
              active={category === key}
              onClick={() => setFilter("category", key)}
            />
          ))}
          {path ? (
            <Chip label={`path: ${path}`} active onClick={() => setFilter("path", path)} />
          ) : null}
        </div>
      </header>

      {initial ? (
        <div className="rv-pad" style={{ padding: "0 32px" }}>
          <Loading label="Loading findings" />
        </div>
      ) : error ? (
        <div className="rv-pad" style={{ padding: "26px 32px" }}>
          <ErrorBox message={error} onRetry={reload} />
        </div>
      ) : items.length === 0 ? (
        <div className="rv-pad" style={{ padding: "0 32px" }}>
          <Empty title="Nothing matches those filters">
            <p style={{ margin: 0 }}>
              Clear a filter to widen the search, or go back to the run summary to see what this
              analysis actually produced.
            </p>
          </Empty>
        </div>
      ) : (
        <>
          <div
            className="rv-pad"
            style={{
              display: "grid",
              gridTemplateColumns: COLUMNS,
              padding: "0 32px",
              borderBottom: "1px solid var(--rule)",
              fontSize: 12,
              color: "var(--ink-3)",
            }}
          >
            <div style={{ padding: "8px 10px 8px 0" }}>Severity</div>
            <div style={{ padding: "8px 0" }} />
            <div style={{ padding: "8px 10px" }}>Finding</div>
            <div style={{ padding: "8px 10px" }}>Quick Explain</div>
            <div style={{ padding: "8px 10px" }}>Location</div>
            <div style={{ padding: "8px 10px", textAlign: "right" }}>Conf.</div>
            <div style={{ padding: "8px 0 8px 10px" }}>Status</div>
          </div>

          {items.map((finding, i) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              selected={i === selected}
              busy={pending === finding.id}
              onHover={() => setSelected(i)}
              onOpen={() => navigate(`/findings/${finding.id}`)}
            />
          ))}

          <div
            className="rv-pad mono"
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "16px 32px",
              fontSize: 12,
              color: "var(--ink-3)",
            }}
          >
            <span>
              offset {offset} · limit {PAGE} · total {num(totalCount)}
            </span>
            <span style={{ display: "flex", gap: 14 }}>
              {offset > 0 ? (
                <button className="btn-quiet" onClick={() => goToOffset(Math.max(0, offset - PAGE))}>
                  ← Previous {PAGE}
                </button>
              ) : null}
              {to < totalCount ? (
                <button className="btn-quiet" onClick={() => goToOffset(offset + PAGE)}>
                  Next {PAGE} →
                </button>
              ) : null}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function FindingRow({
  finding,
  selected,
  busy,
  onHover,
  onOpen,
}: {
  finding: Finding;
  selected: boolean;
  busy: boolean;
  onHover: () => void;
  onOpen: () => void;
}) {
  const token = sev(finding.severity);
  const status = findingStatus(finding.status);
  const muted = finding.status === "false_positive";

  return (
    <button
      onClick={onOpen}
      onMouseEnter={onHover}
      className="rv-pad"
      style={{
        display: "grid",
        gridTemplateColumns: COLUMNS,
        alignItems: "center",
        width: "100%",
        textAlign: "left",
        border: 0,
        borderBottom: "1px solid var(--rule-2)",
        borderLeft: `3px solid ${selected ? "var(--ink)" : "transparent"}`,
        padding: "0 32px 0 29px",
        background: selected ? "var(--sel)" : "transparent",
        cursor: "pointer",
        opacity: muted ? 0.55 : busy ? 0.6 : 1,
      }}
    >
      <span style={{ padding: "var(--row-pad) 10px var(--row-pad) 0" }}>
        <SeverityBadge value={finding.severity} />
      </span>
      <span style={{ padding: "var(--row-pad) 0" }}>
        <Meter rank={token.rank} />
      </span>
      <span style={{ padding: "var(--row-pad) 10px", minWidth: 0 }}>
        <span
          style={{
            display: "block",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontSize: 13.5,
            fontWeight: 500,
            textDecoration: muted ? "line-through" : "none",
          }}
        >
          {finding.title}
        </span>
        <span className="mono" style={{ display: "block", fontSize: 11, color: "var(--ink-3)", marginTop: 2 }}>
          {categoryLabel(finding.category)} · {cite(finding)}
        </span>
      </span>
      <span
        style={{
          padding: "var(--row-pad) 10px",
          minWidth: 0,
          fontSize: 12.5,
          color: "var(--ink-2)",
          lineHeight: 1.35,
        }}
        title={finding.description || finding.root_cause || ""}
      >
        <span
          style={{
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {finding.description || finding.root_cause || "No description recorded"}
        </span>
      </span>
      <span
        className="mono"
        style={{
          padding: "var(--row-pad) 10px",
          minWidth: 0,
          fontSize: 12,
          color: "var(--ink-2)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={finding.path}
      >
        {finding.path}:{finding.start_line}
      </span>
      <span className="mono" style={{ padding: "var(--row-pad) 10px", textAlign: "right", fontSize: 12.5 }}>
        {finding.confidence.toFixed(2)}
      </span>
      <span style={{ padding: "var(--row-pad) 0 var(--row-pad) 10px", fontSize: 12, color: status.fg }}>
        {busy ? "saving…" : status.label}
      </span>
    </button>
  );
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      style={{
        border: `1px solid ${active ? "var(--ink)" : "var(--rule)"}`,
        background: active ? "var(--ink)" : "var(--paper)",
        color: active ? "var(--paper)" : "var(--ink-2)",
        padding: "6px 11px",
        cursor: "pointer",
        fontSize: 13,
      }}
    >
      {label}
    </button>
  );
}
