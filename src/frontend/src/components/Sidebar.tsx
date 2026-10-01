import { NavLink } from "react-router-dom";
import { api } from "../lib/api";
import { num } from "../lib/format";
import { useApi } from "../lib/hooks";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

/**
 * The analysis-scoped links only appear once there is an analysis to scope
 * them to — an always-visible "Findings" link that 404s is worse than no link.
 */
function navItems(analysisId: string | null): NavItem[] {
  const base: NavItem[] = [
    { to: "/", label: "Repositories", end: true },
    { to: "/new", label: "Analyse a repository" },
  ];
  if (analysisId) {
    base.push(
      { to: `/analyses/${analysisId}`, label: "This run", end: true },
      { to: `/analyses/${analysisId}/findings`, label: "Findings" },
      { to: `/analyses/${analysisId}/search`, label: "Search the code" },
    );
  }
  base.push({ to: "/settings", label: "Settings" });
  base.push({
    to: analysisId ? `/analyses/${analysisId}/quick-explain` : "/quick-explain",
    label: "Quick Explain",
  });
  base.push({
    to: analysisId ? `/analyses/${analysisId}/chat` : "/chat",
    label: "Finding Chatbot",
  });
  return base;
}

export function Sidebar({
  analysisId,
  theme,
  density,
  onToggleTheme,
  onToggleDensity,
}: {
  analysisId: string | null;
  theme: string;
  density: string;
  onToggleTheme: () => void;
  onToggleDensity: () => void;
}) {
  const health = useApi(() => api.health(), [], 30_000);
  const metrics = useApi(() => api.metrics(), [], 30_000);

  const online = health.data?.status === "ok";
  const dot = health.error ? "var(--fail)" : online ? "var(--pass)" : "var(--warn)";
  const items = navItems(analysisId);

  return (
    <nav
      className="rv-nav"
      style={{
        borderRight: "1px solid var(--rule)",
        display: "flex",
        flexDirection: "column",
        position: "sticky",
        top: 0,
        height: "100vh",
        overflow: "auto",
        background: "var(--paper)",
      }}
    >
      <div style={{ padding: "18px 16px 14px", borderBottom: "1px solid var(--rule)" }}>
        <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>RepoVue</div>
        <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 3 }}>
          evidence, not opinions
        </div>
      </div>

      {items.map((item, i) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          style={({ isActive }) => ({
            display: "flex",
            gap: 9,
            alignItems: "baseline",
            width: "100%",
            textAlign: "left",
            border: 0,
            borderBottom: "1px solid var(--rule-2)",
            background: isActive ? "var(--sel)" : "transparent",
            color: "var(--ink)",
            padding: "9px 16px",
            cursor: "pointer",
            fontWeight: isActive ? 600 : 400,
            textDecoration: "none",
          })}
        >
          <span
            className="mono"
            style={{ fontSize: 11, color: "var(--ink-3)", width: 14, flex: "none" }}
          >
            {String(i + 1).padStart(2, "0")}
          </span>
          <span>{item.label}</span>
        </NavLink>
      ))}

      <div
        style={{
          marginTop: "auto",
          padding: "14px 16px",
          borderTop: "1px solid var(--rule)",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div
          className="mono"
          style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--ink-3)" }}
        >
          <span style={{ width: 7, height: 7, background: dot, borderRadius: "50%", flex: "none" }} />
          <span>
            {health.error
              ? "api unreachable"
              : `api ${health.data?.status ?? "…"} · ${num(metrics.data?.jobs_pending ?? 0)} queued`}
          </span>
        </div>

        <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", lineHeight: 1.7 }}>
          <div>
            analyses {num(metrics.data?.analyses ?? 0)} · findings {num(metrics.data?.findings ?? 0)}
          </div>
          <div>false positives marked {num(metrics.data?.false_positives ?? 0)}</div>
          {health.data && !health.data.llm_configured ? (
            <div style={{ color: "var(--warn)" }}>no model key · review stages skip</div>
          ) : null}
          {health.data && health.data.docker !== "ok" ? (
            <div style={{ color: "var(--warn)" }}>no docker · patches go unvalidated</div>
          ) : null}
        </div>

        <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
          <button className="btn" style={{ fontSize: 12, padding: "6px 9px" }} onClick={onToggleTheme}>
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          <button className="btn" style={{ fontSize: 12, padding: "6px 9px" }} onClick={onToggleDensity}>
            {density === "compact" ? "Comfortable" : "Compact"}
          </button>
        </div>
      </div>
    </nav>
  );
}
