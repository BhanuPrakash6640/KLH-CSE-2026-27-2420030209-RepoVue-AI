import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CodeSnippet } from "../components/Code";
import { Meter, SeverityBadge } from "../components/Severity";
import { ErrorBox, Loading } from "../components/States";
import { api, ApiError } from "../lib/api";
import { useAnnounceAnalysis } from "../lib/current";
import { categoryLabel, dateTime, findingStatus, sev } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { FindingDetail, FindingStatusValue } from "../lib/types";

const VERDICTS: { value: FindingStatusValue; label: string; note: string }[] = [
  {
    value: "resolved",
    label: "Real, and I have handled it",
    note: "Counted as a true positive. The finding drops out of the open list.",
  },
  {
    value: "open",
    label: "Real, still open",
    note: "Counted as a true positive and left in the open list for someone to pick up.",
  },
  {
    value: "false_positive",
    label: "Not a real problem",
    note: "Counted against RepoVue's precision, which is the number the evaluation reports.",
  },
];

export function FindingDetailPage() {
  const { findingId = "" } = useParams();
  const navigate = useNavigate();
  const { data, error, initial, reload, setData } = useApi(() => api.finding(findingId), [findingId]);
  const jira = useApi(() => api.jira(findingId).catch(() => null), [findingId]);
  const [saving, setSaving] = useState<FindingStatusValue | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useAnnounceAnalysis(data?.analysis_id);

  if (initial)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <Loading label="Loading finding" />
      </div>
    );
  if (error || !data)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <ErrorBox message={error ?? "That finding could not be loaded"} onRetry={reload} />
      </div>
    );

  const finding = data;
  const token = sev(finding.severity);
  const status = findingStatus(finding.status);
  const patch = finding.patches[0] ?? null;
  const triageNote = readEvidence(finding, ["triage_reason", "triage", "rationale", "why_kept"]);
  const reviewerNote = readEvidence(finding, ["reviewer_note"]);

  const record = async (value: FindingStatusValue) => {
    setSaving(value);
    setSaveError(null);
    try {
      const updated = await api.updateFinding(finding.id, value);
      setData(updated);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div
      className="rv-split"
      style={{ display: "grid", gridTemplateColumns: "198px minmax(0,1fr)", alignItems: "start" }}
    >
      <aside
        className="rv-pad"
        style={{
          borderRight: "1px solid var(--rule)",
          padding: "26px 18px 40px 32px",
          position: "sticky",
          top: 0,
        }}
      >
        <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 14 }}>
          provenance
        </div>
        {[
          { label: "category", value: categoryLabel(finding.category) },
          { label: "severity", value: token.label },
          { label: "confidence", value: finding.confidence.toFixed(2) },
          { label: "file", value: finding.path },
          {
            label: "lines",
            value:
              finding.start_line === finding.end_line
                ? String(finding.start_line)
                : `${finding.start_line}–${finding.end_line}`,
          },
          { label: "cwe", value: finding.cwe ?? "—" },
          { label: "owasp", value: finding.owasp ?? "—" },
          { label: "raised by", value: finding.model ?? "—" },
          { label: "raised at", value: dateTime(finding.created_at) },
          { label: "status", value: status.label, fg: status.fg },
        ].map((row) => (
          <div key={row.label} style={{ padding: "9px 0", borderTop: "1px solid var(--rule-2)" }}>
            <div style={{ fontSize: 11, color: "var(--ink-3)" }}>{row.label}</div>
            <div
              className="mono"
              style={{ fontSize: 12.5, marginTop: 2, wordBreak: "break-word", color: row.fg ?? "var(--ink)" }}
            >
              {row.value}
            </div>
          </div>
        ))}
        {jira.data ? (
          <div style={{ padding: "9px 0", borderTop: "1px solid var(--rule-2)" }}>
            <div style={{ fontSize: 11, color: "var(--ink-3)" }}>jira</div>
            <div className="mono" style={{ fontSize: 12.5, marginTop: 2 }}>
              <a href={jira.data.url} target="_blank" rel="noreferrer">
                {jira.data.key}
              </a>{" "}
              · {jira.data.status}
            </div>
          </div>
        ) : null}
      </aside>

      <div className="rv-pad" style={{ padding: "26px 32px 80px", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button className="btn-quiet" onClick={() => navigate(`/analyses/${finding.analysis_id}/findings`)}>
            Back to findings
          </button>
          <Link
            to={`/analyses/${finding.analysis_id}/chat?finding_id=${finding.id}`}
            className="btn"
            style={{
              textDecoration: "none",
              fontSize: 12.5,
              fontWeight: 500,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "var(--accent-soft)",
              color: "var(--accent)",
              border: "1px solid var(--accent)",
            }}
          >
            <span>💬</span> Ask AI Chatbot about this finding
          </Link>
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
          <SeverityBadge value={finding.severity} />
          <Meter rank={token.rank} width={4} height={13} />
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
            {categoryLabel(finding.category)} · confidence {finding.confidence.toFixed(2)}
          </span>
        </div>

        <h1
          style={{
            margin: "10px 0 0",
            fontSize: 27,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            maxWidth: "24ch",
            textWrap: "pretty",
          }}
        >
          {finding.title}
        </h1>

        {finding.snippet ? (
          <div style={{ marginTop: 26 }}>
            <CodeSnippet
              code={finding.snippet}
              startLine={finding.start_line}
              endLine={finding.end_line}
              path={finding.path}
            />
          </div>
        ) : null}

        <div style={{ display: "grid", marginTop: 30, maxWidth: "76ch" }}>
          <Section title="What it is" emphasis>
            {finding.description}
          </Section>
          {finding.root_cause ? (
            <Section title="Why it happens" sunk>
              {finding.root_cause}
            </Section>
          ) : null}
          {finding.impact ? <Section title="What it costs you">{finding.impact}</Section> : null}
        </div>

        {triageNote ? (
          <div style={{ marginTop: 30, border: "1px solid var(--rule)", padding: "14px 16px", maxWidth: "76ch" }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 5 }}>Why triage kept it</div>
            <p style={{ margin: 0, color: "var(--ink-2)", textWrap: "pretty" }}>{triageNote}</p>
          </div>
        ) : null}

        <div
          style={{
            marginTop: 30,
            display: "flex",
            gap: 20,
            alignItems: "center",
            flexWrap: "wrap",
            borderTop: "1px solid var(--rule)",
            paddingTop: 20,
          }}
        >
          {patch ? (
            <>
              <Link
                to={`/patches/${patch.id}`}
                className="btn-primary"
                style={{ padding: "11px 18px", fontSize: 15, textDecoration: "none", display: "inline-block" }}
              >
                Review the patch and its test run
              </Link>
              <span className="mono" style={{ fontSize: 12, color: status.fg }}>
                {status.label} · {dateTime(patch.created_at)}
              </span>
            </>
          ) : (
            <span style={{ color: "var(--ink-2)", fontSize: 13, maxWidth: "60ch" }}>
              No patch was written for this one. Patch generation is budgeted per run and skips
              findings where a minimal, safe edit is not obvious.
            </span>
          )}
        </div>

        <section
          style={{
            marginTop: 34,
            border: "1px solid var(--rule)",
            borderTopWidth: 3,
            borderTopColor: "var(--ink)",
            padding: "18px 20px",
            maxWidth: "76ch",
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Your verdict</h2>
          <p style={{ margin: "6px 0 16px", color: "var(--ink-2)" }}>
            This is how RepoVue measures its own precision. If this finding is wrong, saying so is
            the most useful thing you can do here — it is counted against the tool, not against you.
          </p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {VERDICTS.map((verdictOption) => {
              const active = finding.status === verdictOption.value;
              return (
                <button
                  key={verdictOption.value}
                  onClick={() => void record(verdictOption.value)}
                  disabled={saving !== null}
                  style={{
                    border: `1px solid ${active ? "var(--ink)" : "var(--rule)"}`,
                    background: active ? "var(--ink)" : "var(--paper)",
                    color: active ? "var(--paper)" : "var(--ink)",
                    padding: "10px 16px",
                    cursor: saving ? "wait" : "pointer",
                    fontWeight: 500,
                  }}
                >
                  {saving === verdictOption.value ? "Saving…" : verdictOption.label}
                </button>
              );
            })}
          </div>
          <div style={{ marginTop: 14, fontSize: 13, color: "var(--ink-2)" }}>
            {VERDICTS.find((v) => v.value === finding.status)?.note ??
              "Nothing recorded yet. Your answer feeds the false-positive rate the evaluation reports."}
          </div>
          {reviewerNote ? (
            <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--ink-3)" }}>
              note: {reviewerNote}
            </div>
          ) : null}
          {saveError ? (
            <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--fail)" }}>
              {saveError}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
  emphasis,
  sunk,
}: {
  title: string;
  children: React.ReactNode;
  emphasis?: boolean;
  sunk?: boolean;
}) {
  return (
    <div
      style={{
        borderTop: emphasis ? "2px solid var(--ink)" : "1px solid var(--rule)",
        padding: sunk ? "14px 16px 18px" : "14px 0 18px",
        background: sunk ? "var(--sunk)" : "transparent",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 5 }}>{title}</div>
      <p style={{ margin: 0, color: "var(--ink-2)", textWrap: "pretty", whiteSpace: "pre-wrap" }}>
        {children}
      </p>
    </div>
  );
}

/** The analyzers write free-form evidence; take the first key that is present
 *  rather than assuming one shape. */
function readEvidence(finding: FindingDetail, keys: string[]): string | null {
  for (const key of keys) {
    const value = finding.evidence?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}
