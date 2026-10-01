import { useNavigate } from "react-router-dom";
import { clock, num, shortSha, STAGES, timeOfDay } from "../lib/format";
import { useElapsed } from "../lib/hooks";
import type { Analysis, AnalysisStats } from "../lib/types";

/** One line of evidence per stage, built from whatever the pipeline has
 *  written so far. A stage that hasn't run yet says what it will do. */
function stageDetail(key: string, stats: AnalysisStats, analysis: Analysis, reached: boolean): string {
  if (!reached) {
    return {
      clone: "Shallow clone at the requested ref",
      index: "Tree-sitter ASTs, call graph, dependency graph",
      embed: "Symbol-aligned chunks into the vector index",
      review: "Four analyzers per file, run in parallel",
      triage: "A second model deletes the findings that do not hold up",
      fix: "A minimal patch per finding worth patching",
      validate: "Your test suite, in a container, before and after",
      publish: "Check run, inline review, Jira tickets",
      done: "",
    }[key] ?? "";
  }
  switch (key) {
    case "clone":
      return `${analysis.repository_full_name ?? "repository"} at ${shortSha(
        stats.commit_sha ?? analysis.commit_sha,
      )}${stats.changed_files ? ` · ${num(stats.changed_files)} files changed` : ""}`;
    case "index":
      return `${num(stats.files_analysed)} files walked · ${num(stats.symbols)} symbols extracted`;
    case "embed":
      return stats.chunks === 0 ? "No chunks to embed" : `${num(stats.chunks)} chunks embedded`;
    case "review":
      if (stats.review_skipped) return `Skipped — ${stats.review_skipped}`;
      return `${num(stats.files_reviewed)} files reviewed · ${num(stats.raw_findings)} candidates raised`;
    case "triage":
      return `${num(stats.findings_dropped_by_triage)} deleted as false positives · ${num(
        stats.findings,
      )} kept`;
    case "fix":
      return `${num(stats.patches_generated)} patches written`;
    case "validate":
      return stats.patches_validated === undefined
        ? "Running your test suite"
        : `${num(stats.patches_validated)} patches run against your tests`;
    case "publish":
      if (stats.publish_skipped) return `Skipped — ${stats.publish_skipped}`;
      if (stats.publish_error) return `Publishing failed — ${stats.publish_error}`;
      return `${num(stats.jira_tickets ?? 0)} Jira tickets opened`;
    case "done":
      return "Run complete";
    default:
      return "";
  }
}

export function RunningView({ analysis }: { analysis: Analysis }) {
  const navigate = useNavigate();
  const stats = analysis.stats ?? {};
  const inFlight = analysis.status === "running" || analysis.status === "queued";
  const stopped = analysis.status === "failed" || analysis.status === "cancelled";
  const elapsed = useElapsed(
    analysis.started_at ?? analysis.created_at,
    inFlight,
    inFlight ? null : analysis.finished_at,
  );

  const currentIndex = STAGES.findIndex((s) => s.key === analysis.stage);
  const progress = analysis.progress ?? 0;

  const headline = stopped
    ? analysis.status === "cancelled"
      ? "This run was cancelled"
      : "The run stopped"
    : analysis.status === "queued"
      ? "Queued — waiting for a worker"
      : `Working through ${analysis.repository_full_name ?? "the repository"}`;

  return (
    <div className="rv-pad" style={{ padding: "26px 32px 80px" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: 20,
          flexWrap: "wrap",
          borderBottom: "1px solid var(--rule)",
          paddingBottom: 16,
        }}
      >
        <div>
          <div className="mono" style={{ fontSize: 13, color: "var(--ink-3)" }}>
            {analysis.repository_full_name ?? "repository"} · {analysis.branch ?? "default"} ·{" "}
            {shortSha(stats.commit_sha ?? analysis.commit_sha)}
            {analysis.pr_number ? ` · PR #${analysis.pr_number}` : ""}
          </div>
          <h1 style={{ margin: "5px 0 0", fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
            {headline}
          </h1>
        </div>
        <div className="mono" style={{ fontSize: 22, letterSpacing: "-0.02em" }}>
          {clock(elapsed)}
        </div>
      </header>

      {stopped ? (
        <div
          style={{
            marginTop: 22,
            border: "1px solid var(--fail)",
            borderLeftWidth: 3,
            padding: "18px 20px",
            maxWidth: 760,
          }}
        >
          <div style={{ fontWeight: 600, color: "var(--fail)", fontSize: 16 }}>
            Stopped at stage {currentIndex >= 0 ? currentIndex + 1 : "?"} · {analysis.stage ?? "unknown"}
          </div>
          <p style={{ margin: "8px 0 0", color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>
            {analysis.error ??
              (analysis.status === "cancelled"
                ? "Cancelled before it finished. Nothing from this run was published."
                : "No error was recorded, which usually means the worker died mid-run.")}
          </p>
          <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn-primary" onClick={() => navigate("/new")}>
              Start another run
            </button>
            <button className="btn" onClick={() => navigate("/")}>
              Back to repositories
            </button>
          </div>
          <div
            className="mono"
            style={{
              marginTop: 16,
              fontSize: 12,
              color: "var(--ink-3)",
              borderTop: "1px solid var(--rule-2)",
              paddingTop: 10,
            }}
          >
            error · {analysis.stage ?? "unknown"} · {timeOfDay(analysis.finished_at)}
          </div>
        </div>
      ) : (
        <div
          className="rv-split"
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0,1.5fr) minmax(260px,1fr)",
            gap: 40,
            marginTop: 24,
            alignItems: "start",
          }}
        >
          <div>
            <div
              style={{ height: 3, background: "var(--rule-2)", position: "relative", overflow: "hidden" }}
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div style={{ height: 3, background: "var(--ink)", width: `${progress}%` }} />
            </div>
            <div
              className="mono"
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 11,
                color: "var(--ink-3)",
                padding: "4px 0 14px",
              }}
            >
              <span>{progress}%</span>
              <span>
                stage {Math.max(currentIndex + 1, 1)} of {STAGES.length}
              </span>
            </div>

            {STAGES.map((stage, i) => {
              const done = currentIndex > i;
              const active = currentIndex === i;
              const mark = done ? "·" : active ? "▸" : "";
              return (
                <div
                  key={stage.key}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "62px 18px minmax(0,1fr)",
                    gap: 10,
                    alignItems: "baseline",
                    borderBottom: "1px solid var(--rule-2)",
                    padding: "9px 0",
                    opacity: done ? 0.6 : active ? 1 : 0.38,
                  }}
                >
                  <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
                    {done || active ? `${stage.progress}%` : ""}
                  </div>
                  <div className="mono" style={{ fontSize: 13, color: active ? "var(--ink)" : "var(--ink-3)" }}>
                    {mark}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "baseline", justifyContent: "space-between" }}>
                      <span style={{ fontWeight: active ? 600 : 400 }}>{stage.label}</span>
                      <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>
                        {done ? "done" : active ? "running" : "waiting"}
                      </span>
                    </div>
                    <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>
                      {stageDetail(stage.key, stats, analysis, done || active)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <aside style={{ border: "1px solid var(--rule)", padding: "18px 20px 20px" }}>
            <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 14 }}>Counted so far</div>
            {[
              { label: "Files reviewed", value: stats.files_reviewed, fg: "var(--ink)" },
              { label: "Candidates raised", value: stats.raw_findings, fg: "var(--ink)" },
              { label: "Deleted by triage", value: stats.findings_dropped_by_triage, fg: "var(--ink-3)" },
              { label: "Findings kept", value: stats.findings, fg: "var(--ink)", big: true },
              { label: "Patches validated", value: stats.patches_validated, fg: "var(--pass)" },
            ].map((counter) => (
              <div
                key={counter.label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: 12,
                  padding: "7px 0",
                  borderBottom: "1px solid var(--rule-2)",
                }}
              >
                <span style={{ color: counter.fg, fontSize: 13 }}>{counter.label}</span>
                <span
                  className="mono"
                  style={{ fontSize: counter.big ? 18 : 14, fontWeight: 500, color: counter.fg }}
                >
                  {counter.value === undefined ? "—" : num(counter.value)}
                </span>
              </div>
            ))}
            <p style={{ margin: "14px 0 0", fontSize: 13, color: "var(--ink-2)" }}>
              Every raised finding is re-read by a second model whose only job is to delete the ones
              that do not hold up. Those deletions are counted above.
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}
