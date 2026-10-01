import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DiffView, diffStats } from "../components/Diff";
import { ErrorBox, Loading } from "../components/States";
import { api, ApiError } from "../lib/api";
import { useAnnounceAnalysis } from "../lib/current";
import { dateTime, num, PATCH_STATUS_LABEL, seconds, signedPct, verdict as verdictToken } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Patch, ValidationRun, ValidationSide } from "../lib/types";

export function PatchPage() {
  const { patchId = "" } = useParams();
  const navigate = useNavigate();
  const patch = useApi(() => api.patch(patchId), [patchId]);
  const runs = useApi(() => api.validations(patchId), [patchId]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useAnnounceAnalysis(patch.data?.analysis_id);

  if (patch.initial)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <Loading label="Loading patch" />
      </div>
    );
  if (patch.error || !patch.data)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <ErrorBox message={patch.error ?? "That patch could not be loaded"} onRetry={patch.reload} />
      </div>
    );

  const data: Patch = patch.data;
  const run: ValidationRun | null = runs.data?.[0] ?? null;
  const token = verdictToken(run?.verdict ?? "skipped");
  const stats = diffStats(data.diff);

  const decide = async (accept: boolean) => {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.decidePatch(data.id, accept);
      patch.setData(updated);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rv-pad" style={{ padding: "24px 32px 80px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <button className="btn-quiet" onClick={() => navigate(`/findings/${data.finding_id}`)}>
            Back to the finding
          </button>
          <h1 style={{ margin: "8px 0 0", fontSize: 23, fontWeight: 600, letterSpacing: "-0.02em", wordBreak: "break-word" }}>
            Patch for {data.path}
          </h1>
          <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 6 }}>
            {PATCH_STATUS_LABEL[data.status] ?? data.status} · +{stats.additions} −{stats.deletions} ·{" "}
            written by {data.model ?? "model"} · {dateTime(data.created_at)}
          </div>
        </div>
        <Link
          to={`/analyses/${data.analysis_id}/findings`}
          className="btn"
          style={{ textDecoration: "none", color: "var(--ink)" }}
        >
          All findings
        </Link>
      </div>

      <VerdictBanner run={run} loading={runs.initial} token={token} />

      <div
        className="rv-split"
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0,1.55fr) minmax(280px,1fr)",
          gap: 32,
          marginTop: 26,
          alignItems: "start",
        }}
      >
        <DiffView diff={data.diff} path={data.path} />

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <section>
            <h2 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>What the patch does</h2>
            <p style={{ margin: 0, color: "var(--ink-2)", textWrap: "pretty", whiteSpace: "pre-wrap" }}>
              {data.explanation ?? "No explanation was recorded with this patch."}
            </p>
          </section>

          {data.risk_notes ? (
            <section style={{ border: "1px solid var(--rule)", padding: "14px 16px" }}>
              <h2 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>
                What a reviewer must check
              </h2>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 18,
                  color: "var(--ink-2)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 7,
                }}
              >
                {splitRisks(data.risk_notes).map((risk, i) => (
                  <li key={i} style={{ textWrap: "pretty" }}>
                    {risk}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <TestRuns run={run} loading={runs.initial} />

          <section style={{ borderTop: "1px solid var(--rule)", paddingTop: 16 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                className="btn-primary"
                disabled={saving || data.status === "accepted"}
                onClick={() => void decide(true)}
              >
                {data.status === "accepted" ? "Accepted" : saving ? "Saving…" : "Accept patch"}
              </button>
              <button
                className="btn"
                disabled={saving || data.status === "rejected"}
                onClick={() => void decide(false)}
              >
                {data.status === "rejected" ? "Rejected" : "Reject patch"}
              </button>
            </div>
            <p style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--ink-3)" }}>
              {run?.verdict === "pass"
                ? "Accepting marks the finding as fixed. The patch still needs a human on the pull request."
                : "This patch has no passing test run behind it, so accepting it is your judgement alone."}
            </p>
            {saveError ? (
              <p className="mono" style={{ margin: "10px 0 0", fontSize: 12, color: "var(--fail)" }}>
                {saveError}
              </p>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}

function VerdictBanner({
  run,
  loading,
  token,
}: {
  run: ValidationRun | null;
  loading: boolean;
  token: { headline: string; fg: string; border: string };
}) {
  if (loading) {
    return (
      <div style={{ marginTop: 18, border: "1px solid var(--rule)", padding: "18px 22px" }}>
        <Loading label="Loading the validation run" />
      </div>
    );
  }

  const sub = run
    ? (run.reason ??
      (run.verdict === "pass"
        ? "The suite was run in a container before and after the change. Nothing that passed before fails now."
        : run.verdict === "fail"
          ? "The patch was rejected automatically. It is here so you can see what it would have done."
          : "No verdict could be reached, so this patch carries no evidence beyond the model's reasoning."))
    : "This patch was never run against your tests. Validation needs Docker and a detectable test command.";

  const cells = run
    ? [
        { label: "Verdict", value: run.verdict, fg: token.fg },
        { label: "Tests", value: run.tests_passed ? "passed" : "failed", fg: run.tests_passed ? "var(--pass)" : "var(--fail)" },
        { label: "Runtime change", value: signedPct(run.perf_delta_pct), fg: perfTone(run.perf_delta_pct) },
        { label: "Image", value: run.image_tag ?? "—", fg: "var(--ink)" },
        { label: "Ran at", value: dateTime(run.created_at), fg: "var(--ink)" },
      ]
    : [];

  return (
    <div style={{ marginTop: 18, border: `1px solid ${token.border}`, borderLeftWidth: 4 }}>
      <div style={{ display: "flex", gap: 26, alignItems: "center", flexWrap: "wrap", padding: "18px 22px" }}>
        <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", color: token.fg }}>
          {run ? token.headline : "Not validated"}
        </div>
        <div style={{ color: "var(--ink-2)", maxWidth: "58ch", textWrap: "pretty" }}>{sub}</div>
      </div>
      {cells.length > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
            borderTop: `1px solid ${token.border}`,
          }}
        >
          {cells.map((cell) => (
            <div key={cell.label} style={{ padding: "14px 22px", borderRight: `1px solid ${token.border}` }}>
              <div style={{ fontSize: 12, color: "var(--ink-3)" }}>{cell.label}</div>
              <div className="mono" style={{ fontSize: 19, marginTop: 3, color: cell.fg, wordBreak: "break-word" }}>
                {cell.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TestRuns({ run, loading }: { run: ValidationRun | null; loading: boolean }) {
  if (loading || !run) {
    return (
      <section>
        <h2 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>Test runs</h2>
        <p style={{ margin: 0, color: "var(--ink-2)", fontSize: 13 }}>
          {loading ? "Loading…" : "No run was recorded for this patch."}
        </p>
      </section>
    );
  }

  const rows: { label: string; baseline: string; patched: string; tone?: string }[] = [
    {
      label: "result",
      baseline: sideResult(run.baseline),
      patched: sideResult(run.patched),
      tone: run.tests_passed ? "var(--pass)" : "var(--fail)",
    },
    { label: "passed", baseline: countOf(run.baseline, "tests_passed"), patched: countOf(run.patched, "tests_passed") },
    { label: "failed", baseline: countOf(run.baseline, "tests_failed"), patched: countOf(run.patched, "tests_failed") },
    { label: "median", baseline: sideTime(run.baseline), patched: sideTime(run.patched) },
  ];

  return (
    <section>
      <h2 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>Test runs</h2>
      <div style={{ display: "grid", gridTemplateColumns: "82px 1fr 1fr", borderTop: "1px solid var(--rule)" }}>
        <Cell text="" />
        <Cell text="baseline" align="right" muted />
        <Cell text="patched" align="right" muted />
        {rows.map((row) => (
          <RowCells key={row.label} label={row.label} baseline={row.baseline} patched={row.patched} tone={row.tone} />
        ))}
      </div>
      <div className="mono" style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 10, lineHeight: 1.7 }}>
        {[run.image_tag, run.test_command, "median of the recorded runs"].filter(Boolean).join(" · ")}
      </div>
      {run.logs ? (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--ink-2)" }}>Container logs</summary>
          <pre
            className="mono"
            style={{
              margin: "8px 0 0",
              fontSize: 11.5,
              lineHeight: 1.6,
              background: "var(--sunk)",
              padding: "10px 12px",
              overflowX: "auto",
              maxHeight: 320,
              color: "var(--ink-2)",
            }}
          >
            {run.logs}
          </pre>
        </details>
      ) : null}
    </section>
  );
}

function RowCells({
  label,
  baseline,
  patched,
  tone,
}: {
  label: string;
  baseline: string;
  patched: string;
  tone?: string;
}) {
  return (
    <>
      <Cell text={label} muted />
      <Cell text={baseline} align="right" />
      <Cell text={patched} align="right" tone={tone} />
    </>
  );
}

function Cell({
  text,
  align = "left",
  muted,
  tone,
}: {
  text: string;
  align?: "left" | "right";
  muted?: boolean;
  tone?: string;
}) {
  return (
    <div
      className="mono"
      style={{
        padding: align === "left" ? "8px 10px 8px 0" : "8px 0 8px 10px",
        borderBottom: "1px solid var(--rule-2)",
        fontSize: 12.5,
        color: tone ?? (muted ? "var(--ink-3)" : "var(--ink)"),
        textAlign: align,
      }}
    >
      {text}
    </div>
  );
}

function sideResult(side: ValidationSide): string {
  if (side.passed === true) return "pass";
  if (side.passed === false) return "fail";
  if (typeof side.exit_code === "number") return side.exit_code === 0 ? "pass" : `exit ${side.exit_code}`;
  return "—";
}

function countOf(side: ValidationSide, key: "tests_passed" | "tests_failed"): string {
  const value = side[key];
  return typeof value === "number" ? num(value) : "—";
}

function sideTime(side: ValidationSide): string {
  const value = side.median_sec ?? side.duration_sec;
  return typeof value === "number" ? seconds(value) : "—";
}

function perfTone(delta: number | null): string {
  if (delta === null || delta === undefined) return "var(--ink)";
  if (delta < -1) return "var(--pass)";
  if (delta > 5) return "var(--fail)";
  return "var(--ink)";
}

/** Risk notes come back as prose or as a list; render either as bullets. */
function splitRisks(notes: string): string[] {
  const lines = notes
    .split(/\n+/)
    .map((line) => line.replace(/^[-*•\d.)\s]+/, "").trim())
    .filter(Boolean);
  return lines.length > 1 ? lines : [notes.trim()];
}
