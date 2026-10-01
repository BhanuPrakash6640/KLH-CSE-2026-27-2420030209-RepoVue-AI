import { Link, useNavigate } from "react-router-dom";
import { Meter } from "../components/Severity";
import { Empty, ErrorBox, Fact, Loading } from "../components/States";
import { api } from "../lib/api";
import {
  categoryLabel,
  num,
  PATCH_STATUS_LABEL,
  seconds,
  SEV,
  SEVERITY_ORDER,
  shortSha,
  dateTime,
  total,
} from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Analysis, AnalysisSummary } from "../lib/types";

export function DashboardView({ analysis }: { analysis: Analysis }) {
  const { data, error, initial, reload } = useApi(() => api.summary(analysis.id), [analysis.id]);

  if (initial) return <div className="rv-pad" style={{ padding: "26px 32px" }}><Loading label="Loading the run" /></div>;
  if (error || !data)
    return (
      <div className="rv-pad" style={{ padding: "26px 32px" }}>
        <ErrorBox message={error ?? "No summary came back"} onRetry={reload} />
      </div>
    );

  return <Dashboard summary={data} />;
}

function Dashboard({ summary }: { summary: AnalysisSummary }) {
  const navigate = useNavigate();
  const { analysis } = summary;
  const stats = analysis.stats ?? {};
  const kept = total(summary.findings_by_severity);
  const deleted = stats.findings_dropped_by_triage ?? 0;
  const raised = stats.raw_findings ?? kept + deleted;
  const verified = summary.patches.accepted ?? 0;
  const rejected = summary.patches.rejected ?? 0;
  const findingsLink = `/analyses/${analysis.id}/findings`;

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
            {summary.repository?.full_name ?? analysis.repository_full_name ?? "repository"} ·{" "}
            {analysis.branch ?? "default"} · {shortSha(stats.commit_sha ?? analysis.commit_sha)} ·{" "}
            {dateTime(analysis.finished_at ?? analysis.created_at)}
          </div>
          <h1 style={{ margin: "5px 0 0", fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
            {kept === 0
              ? "Nothing to report on this commit"
              : `${num(kept)} ${kept === 1 ? "finding" : "findings"} worth your time`}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn" onClick={() => navigate(`/analyses/${analysis.id}/search`)}>
            Search the code
          </button>
          {kept > 0 ? (
            <button className="btn-primary" onClick={() => navigate(findingsLink)}>
              Open the findings
            </button>
          ) : null}
        </div>
      </header>

      {kept === 0 ? (
        <>
          <Empty title="618 files in, nothing kept" accent="var(--pass)">
            <p style={{ margin: 0 }}>
              {num(stats.files_reviewed ?? 0)} files were reviewed and {num(raised)} candidate
              findings were raised. Triage rejected all of them. The run is complete and the record
              below is the audit trail.
            </p>
          </Empty>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
              marginTop: 28,
              borderTop: "1px solid var(--rule)",
            }}
          >
            <Fact value={num(stats.files_analysed)} label="files indexed" />
            <Fact value={num(stats.symbols)} label="symbols extracted" />
            <Fact value={num(raised)} label="candidates raised" />
            <Fact value={seconds(stats.duration_sec)} label="wall clock" />
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))",
              borderTop: "1px solid var(--rule-2)",
            }}
          >
            <BigNumber value={kept} label="findings kept" />
            <BigNumber
              value={deleted}
              label="deleted by triage"
              sub={`out of ${num(raised)} raised`}
              tone="var(--ink-3)"
            />
            <BigNumber value={verified} label="fixes verified by your tests" tone="var(--pass)" />
            <BigNumber
              value={rejected}
              label="patches rejected — they broke tests"
              tone="var(--fail)"
            />
          </div>

          <div
            className="rv-split"
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(300px,1.1fr) minmax(260px,1fr) minmax(230px,0.9fr)",
              gap: 36,
              paddingTop: 26,
            }}
          >
            <section>
              <h2 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600 }}>Severity</h2>
              {SEVERITY_ORDER.map((key) => {
                const count = summary.findings_by_severity[key] ?? 0;
                const token = SEV[key];
                const width = kept ? `${Math.round((count / kept) * 100)}%` : "0%";
                return (
                  <Link
                    key={key}
                    to={`${findingsLink}?severity=${key}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "78px 34px 1fr 46px",
                      gap: 10,
                      alignItems: "center",
                      padding: "8px 0",
                      borderBottom: "1px solid var(--rule-2)",
                      textDecoration: "none",
                      color: "var(--ink)",
                    }}
                  >
                    <span style={{ fontSize: 13 }}>{token.label}</span>
                    <Meter rank={token.rank} width={4} height={12} />
                    <span style={{ height: 12, background: "var(--rule-2)", position: "relative" }}>
                      <span
                        style={{
                          position: "absolute",
                          inset: "0 auto 0 0",
                          width,
                          background: token.rank >= 4 ? "var(--ink)" : "var(--ink-3)",
                        }}
                      />
                    </span>
                    <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
                      {num(count)}
                    </span>
                  </Link>
                );
              })}

              <h2 style={{ margin: "26px 0 12px", fontSize: 14, fontWeight: 600 }}>Category</h2>
              {Object.entries(summary.findings_by_category)
                .sort((a, b) => b[1] - a[1])
                .map(([key, count]) => (
                  <Link
                    key={key}
                    to={`${findingsLink}?category=${key}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 46px",
                      gap: 10,
                      padding: "7px 0",
                      borderBottom: "1px solid var(--rule-2)",
                      textDecoration: "none",
                      color: "var(--ink-2)",
                    }}
                  >
                    <span style={{ fontSize: 13 }}>{categoryLabel(key)}</span>
                    <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
                      {num(count)}
                    </span>
                  </Link>
                ))}
            </section>

            <section>
              <h2 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600 }}>
                Files carrying the most
              </h2>
              {summary.top_files.length === 0 ? (
                <p style={{ color: "var(--ink-3)", fontSize: 13 }}>Nothing concentrated anywhere.</p>
              ) : (
                summary.top_files.map((file) => (
                  <Link
                    key={file.path}
                    to={`${findingsLink}?path=${encodeURIComponent(file.path)}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 34px",
                      gap: 10,
                      padding: "8px 0",
                      borderBottom: "1px solid var(--rule-2)",
                      textDecoration: "none",
                      color: "var(--ink)",
                    }}
                  >
                    <span
                      className="mono"
                      style={{
                        fontSize: 12,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        direction: "rtl",
                        textAlign: "left",
                      }}
                      title={file.path}
                    >
                      {file.path}
                    </span>
                    <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
                      {file.findings}
                    </span>
                  </Link>
                ))
              )}

              <h2 style={{ margin: "26px 0 12px", fontSize: 14, fontWeight: 600 }}>Patch status</h2>
              {Object.keys(summary.patches).length === 0 ? (
                <p style={{ color: "var(--ink-3)", fontSize: 13 }}>No patches were written.</p>
              ) : (
                Object.entries(summary.patches).map(([key, count]) => (
                  <div
                    key={key}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 40px",
                      gap: 10,
                      padding: "7px 0",
                      borderBottom: "1px solid var(--rule-2)",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 13,
                        color:
                          key === "accepted" || key === "published"
                            ? "var(--pass)"
                            : key === "rejected"
                              ? "var(--fail)"
                              : "var(--ink-2)",
                      }}
                    >
                      {PATCH_STATUS_LABEL[key] ?? key}
                    </span>
                    <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
                      {num(count)}
                    </span>
                  </div>
                ))
              )}
            </section>

            <section>
              <h2 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600 }}>Project</h2>
              {projectRows(summary).map((row) => (
                <div key={row.label} style={{ padding: "8px 0", borderBottom: "1px solid var(--rule-2)" }}>
                  <div style={{ fontSize: 12, color: "var(--ink-3)" }}>{row.label}</div>
                  <div className="mono" style={{ fontSize: 13, marginTop: 2, wordBreak: "break-word" }}>
                    {row.value}
                  </div>
                </div>
              ))}
              {stats.fix_pr_url ? (
                <p style={{ margin: "14px 0 0", fontSize: 13 }}>
                  <a href={stats.fix_pr_url} target="_blank" rel="noreferrer">
                    Pull request with the patches that passed
                  </a>
                </p>
              ) : null}
              {(stats.dependency_cycles ?? 0) > 0 ? (
                <p style={{ margin: "14px 0 0", fontSize: 12, color: "var(--ink-3)" }}>
                  {num(stats.dependency_cycles)} import{" "}
                  {stats.dependency_cycles === 1 ? "cycle was" : "cycles were"} detected. They are
                  listed under architecture findings; there is no graph to explore.
                </p>
              ) : null}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function projectRows(summary: AnalysisSummary): { label: string; value: string }[] {
  const stats = summary.analysis.stats ?? {};
  const project = (stats.project ?? {}) as Record<string, unknown>;
  const languages = Object.entries(stats.languages ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([lang, count]) => `${lang} ${count}`)
    .join(" · ");

  const rows: { label: string; value: string }[] = [
    { label: "Files indexed", value: num(stats.files_analysed) },
    { label: "Lines of code", value: num(stats.loc) },
    { label: "Symbols", value: num(stats.symbols) },
    { label: "Languages", value: languages || "—" },
    { label: "Chunks embedded", value: num(stats.chunks) },
    { label: "Wall clock", value: seconds(stats.duration_sec) },
  ];

  const testCommand = project.test_command ?? project.tests;
  if (typeof testCommand === "string" && testCommand) {
    rows.push({ label: "Test command", value: testCommand });
  }
  if (typeof project.package_manager === "string") {
    rows.push({ label: "Package manager", value: project.package_manager });
  }
  return rows;
}

function BigNumber({
  value,
  label,
  sub,
  tone = "var(--ink)",
}: {
  value: number;
  label: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div
      style={{
        padding: "22px 24px 20px 0",
        borderRight: "1px solid var(--rule-2)",
        borderBottom: "1px solid var(--rule)",
      }}
    >
      <div
        className="mono"
        style={{ fontSize: 52, lineHeight: 1, letterSpacing: "-0.03em", color: tone }}
      >
        {value}
      </div>
      <div style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 6 }}>{label}</div>
      {sub ? <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 3 }}>{sub}</div> : null}
    </div>
  );
}
