import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Meter, SeverityBadge } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/States";
import { api } from "../lib/api";
import { useAnnounceAnalysis, useCurrentAnalysis } from "../lib/current";
import { categoryLabel, cite, sev } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { Finding } from "../lib/types";

export function QuickExplainPage() {
  const params = useParams();
  const { analysisId: contextAnalysisId } = useCurrentAnalysis();
  const analysisId = params.analysisId || contextAnalysisId || "";
  const navigate = useNavigate();

  useAnnounceAnalysis(analysisId || null);

  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const { data, error, initial, reload } = useApi(
    () =>
      analysisId
        ? api.findings({
            analysis_id: analysisId,
            limit: 100,
          })
        : Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }),
    [analysisId],
  );

  const items: Finding[] = useMemo(() => data?.items ?? [], [data]);

  const filtered = useMemo(() => {
    return items.filter((f) => {
      if (activeCategory !== "all" && f.category !== activeCategory) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const text = `${f.title} ${f.description} ${f.root_cause || ""} ${f.impact || ""} ${f.path}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [items, activeCategory, searchQuery]);

  return (
    <div className="rv-pad" style={{ padding: "26px 32px 80px", maxWidth: 1200 }}>
      <header style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Sidebar 07 · AI Code Doctor
            </div>
            <h1 style={{ margin: "6px 0 0", fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em" }}>
              Quick Explain
            </h1>
            <p style={{ margin: "8px 0 0", color: "var(--ink-2)", fontSize: 14.5, maxWidth: "70ch" }}>
              Every defect diagnosed by RepoVue translated into plain, human-readable explanations: what went wrong, why it hurts your app, and how it is fixed.
            </p>
          </div>
          {analysisId ? (
            <Link
              to={`/analyses/${analysisId}/findings`}
              className="btn"
              style={{ textDecoration: "none", color: "var(--ink)", alignSelf: "center" }}
            >
              View Findings Table →
            </Link>
          ) : null}
        </div>

        {analysisId && items.length > 0 ? (
          <div style={{ display: "flex", gap: 12, marginTop: 24, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="text"
              className="mono"
              placeholder="Search explanations by keyword…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                background: "var(--paper-2)",
                border: "1px solid var(--rule)",
                borderRadius: 4,
                padding: "8px 12px",
                fontSize: 13,
                color: "var(--ink)",
                width: 320,
              }}
            />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[
                { id: "all", label: "All Issues" },
                { id: "performance", label: "⚡ Performance" },
                { id: "security", label: "🔒 Security" },
                { id: "architecture", label: "🏛️ Architecture" },
                { id: "logical_bug", label: "🐛 Logical Bugs" },
              ].map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveCategory(c.id)}
                  style={{
                    background: activeCategory === c.id ? "var(--ink)" : "var(--paper-2)",
                    color: activeCategory === c.id ? "var(--paper)" : "var(--ink)",
                    border: "1px solid var(--rule)",
                    borderRadius: 4,
                    padding: "6px 12px",
                    fontSize: 12.5,
                    cursor: "pointer",
                    fontWeight: activeCategory === c.id ? 600 : 400,
                  }}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </header>

      {!analysisId ? (
        <div style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "36px 32px", background: "var(--paper-2)" }}>
          <Empty title="No repository analysis active">
            <p style={{ margin: "8px 0 20px", color: "var(--ink-2)", fontSize: 14 }}>
              Select a repository or run an analysis to see instant, plain-English human explanations of every bug, security hole, and performance bottleneck.
            </p>
            <button className="btn-primary" onClick={() => navigate("/new")}>
              Analyse a repository
            </button>
          </Empty>
        </div>
      ) : initial ? (
        <Loading label="Diagnosing and gathering explanations…" />
      ) : error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : filtered.length === 0 ? (
        <div style={{ border: "1px solid var(--rule)", borderRadius: 6, padding: "36px 32px", background: "var(--paper-2)" }}>
          <Empty title={items.length === 0 ? "No issues detected" : "No matching explanations"}>
            <p style={{ margin: "8px 0", color: "var(--ink-2)" }}>
              {items.length === 0
                ? "This repository passed all quality and security checks."
                : "No findings match your current category or search filter."}
            </p>
          </Empty>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {filtered.map((finding) => (
            <ExplainCard key={finding.id} finding={finding} />
          ))}
        </div>
      )}
    </div>
  );
}

function ExplainCard({ finding }: { finding: Finding }) {
  const token = sev(finding.severity);
  const navigate = useNavigate();

  return (
    <div
      style={{
        border: "1px solid var(--rule)",
        borderRadius: 6,
        background: "var(--paper)",
        boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
        overflow: "hidden",
        transition: "border-color 0.15s ease",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          padding: "12px 18px",
          borderBottom: "1px solid var(--rule-2)",
          background: "var(--paper-2)",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <SeverityBadge value={finding.severity} />
          <Meter rank={token.rank} width={4} height={12} />
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)" }}>
            {categoryLabel(finding.category)}
          </span>
          {finding.cwe ? (
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)", background: "var(--rule-2)", padding: "2px 6px", borderRadius: 3 }}>
              {finding.cwe}
            </span>
          ) : null}
          {finding.owasp ? (
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)", background: "var(--rule-2)", padding: "2px 6px", borderRadius: 3 }}>
              {finding.owasp}
            </span>
          ) : null}
        </div>
        <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
          {cite(finding)}
        </div>
      </div>

      {/* Main content body */}
      <div style={{ padding: "18px 20px 20px" }}>
        {/* Title */}
        <h2 style={{ margin: "0 0 14px", fontSize: 17, fontWeight: 600, color: "var(--ink)" }}>
          {finding.title}
        </h2>

        {/* 3 Core Explanation Blocks */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
          {/* 1. What is Wrong */}
          <div
            style={{
              background: "var(--paper-2)",
              border: "1px solid var(--rule-2)",
              borderRadius: 6,
              padding: "14px 16px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <span style={{ fontSize: 14 }}>💡</span>
              <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--ink-2)" }}>
                What is wrong in simple words
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--ink)", lineHeight: 1.5 }}>
              {finding.description || "The code violates best practices in its domain."}
            </p>
          </div>

          {/* 2. Why it matters (Impact & Root cause) */}
          <div
            style={{
              background: "var(--paper-2)",
              border: "1px solid var(--rule-2)",
              borderRadius: 6,
              padding: "14px 16px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <span style={{ fontSize: 14 }}>⚠️</span>
              <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--ink-2)" }}>
                Why this hurts your app
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--ink)", lineHeight: 1.5 }}>
              {finding.impact || finding.root_cause || "Can lead to performance degradation or unhandled edge cases in production."}
            </p>
          </div>
        </div>

        {/* Action footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 18,
            paddingTop: 14,
            borderTop: "1px solid var(--rule-2)",
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            File: <span style={{ color: "var(--ink-2)" }}>{finding.path}</span> (line {finding.start_line})
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              className="btn"
              style={{ fontSize: 12.5, fontWeight: 500 }}
              onClick={() => navigate(`/analyses/${finding.analysis_id}/chat?finding_id=${finding.id}`)}
            >
              Ask Chatbot 💬
            </button>
            <button
              className="btn"
              style={{ fontSize: 12.5, fontWeight: 500 }}
              onClick={() => navigate(`/findings/${finding.id}`)}
            >
              View Code Snippet &amp; Fix Details →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
