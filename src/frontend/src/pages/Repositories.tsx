import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SeverityBadge } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/States";
import { api, ApiError } from "../lib/api";
import { num, relativeTime, shortSha, titleCase } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { RepositoryOverview } from "../lib/types";

const COLUMNS = "minmax(240px,2fr) 108px 96px repeat(3,minmax(78px,1fr)) 116px";

const STATUS_TONE: Record<string, string> = {
  succeeded: "var(--pass)",
  failed: "var(--fail)",
  running: "var(--ink)",
  queued: "var(--ink-3)",
  cancelled: "var(--ink-3)",
};

export function RepositoriesPage() {
  const navigate = useNavigate();
  const { data, error, initial, reload } = useApi(() => api.repositoriesOverview(), []);

  if (initial) return <div style={{ padding: "26px 32px" }}><Loading label="Loading repositories" /></div>;
  if (error)
    return (
      <div style={{ padding: "26px 32px" }}>
        <ErrorBox
          message={error}
          onRetry={reload}
          hint="Check the API is running and that the key on the Settings screen matches one in API_KEYS."
        />
      </div>
    );

  const rows = data ?? [];

  return (
    <div>
      <header
        className="rv-pad"
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 20,
          flexWrap: "wrap",
          padding: "26px 32px 18px",
          borderBottom: "1px solid var(--rule)",
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
            Repositories
          </h1>
          <p style={{ margin: "6px 0 0", color: "var(--ink-2)", maxWidth: "62ch" }}>
            {rows.length === 0
              ? "Nothing connected yet."
              : `${rows.length} ${rows.length === 1 ? "repository is" : "repositories are"} connected. Each row shows the most recent run and what it left behind.`}
          </p>
        </div>
        <button className="btn-primary" onClick={() => navigate("/new")}>
          Start an analysis
        </button>
      </header>

      {rows.length === 0 ? (
        <div className="rv-pad" style={{ padding: "0 32px" }}>
          <ConnectFirstRepository />
        </div>
      ) : (
        <>
          <div
            className="rv-pad"
            style={{
              display: "grid",
              gridTemplateColumns: COLUMNS,
              borderBottom: "1px solid var(--rule)",
              fontSize: 12,
              color: "var(--ink-3)",
              padding: "0 32px",
            }}
          >
            <div style={{ padding: "9px 10px 9px 0" }}>Repository</div>
            <div style={{ padding: "9px 10px" }}>Last run</div>
            <div style={{ padding: "9px 10px" }}>Status</div>
            <div style={{ padding: "9px 10px", textAlign: "right" }}>Findings</div>
            <div style={{ padding: "9px 10px", textAlign: "right" }}>Patched</div>
            <div style={{ padding: "9px 10px", textAlign: "right" }}>Verified</div>
            <div style={{ padding: "9px 0 9px 10px" }}>Worst</div>
          </div>

          {rows.map((row) => (
            <RepositoryRow key={row.repository.id} row={row} />
          ))}
        </>
      )}
    </div>
  );
}

function RepositoryRow({ row }: { row: RepositoryOverview }) {
  const navigate = useNavigate();
  const last = row.last_analysis;
  const worst = ["critical", "high", "medium", "low", "info"].find(
    (s) => (row.by_severity[s] ?? 0) > 0,
  );

  return (
    <button
      className="row-link rv-pad"
      onClick={() => (last ? navigate(`/analyses/${last.id}`) : navigate("/new"))}
      style={{
        display: "grid",
        gridTemplateColumns: COLUMNS,
        alignItems: "center",
        padding: "0 32px",
      }}
    >
      <span style={{ padding: "var(--row-pad) 10px var(--row-pad) 0", minWidth: 0 }}>
        <span
          className="mono"
          style={{
            display: "block",
            fontSize: 13,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {row.repository.full_name}
        </span>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
          {last?.branch ?? row.repository.default_branch} · {shortSha(last?.commit_sha)}
          {row.repository.is_private ? " · private" : ""}
        </span>
      </span>
      <span className="mono" style={{ padding: "var(--row-pad) 10px", fontSize: 12, color: "var(--ink-2)" }}>
        {relativeTime(last?.finished_at ?? last?.created_at ?? null)}
      </span>
      <span
        style={{
          padding: "var(--row-pad) 10px",
          fontSize: 12.5,
          color: last ? STATUS_TONE[last.status] ?? "var(--ink-2)" : "var(--ink-3)",
        }}
      >
        {last ? titleCase(last.status) : "Never run"}
      </span>
      <span className="mono" style={{ padding: "var(--row-pad) 10px", textAlign: "right", fontSize: 13 }}>
        {last ? num(row.findings) : "—"}
      </span>
      <span className="mono" style={{ padding: "var(--row-pad) 10px", textAlign: "right", fontSize: 13 }}>
        {last ? num(row.patched) : "—"}
      </span>
      <span
        className="mono"
        style={{
          padding: "var(--row-pad) 10px",
          textAlign: "right",
          fontSize: 13,
          color: row.validated > 0 ? "var(--pass)" : "var(--ink-2)",
        }}
      >
        {last ? num(row.validated) : "—"}
      </span>
      <span style={{ padding: "var(--row-pad) 0 var(--row-pad) 10px" }}>
        {worst ? <SeverityBadge value={worst} /> : <span style={{ color: "var(--ink-3)" }}>—</span>}
      </span>
    </button>
  );
}

function ConnectFirstRepository() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("https://github.com/");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const repo = await api.registerRepository(url.trim());
      navigate(`/new?repository=${repo.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Empty title="No repositories yet">
      <p style={{ margin: "0 0 18px" }}>
        Connect a repository and RepoVue clones it, indexes the symbols, reviews the code, and —
        where it can — writes a patch and runs your test suite against it before showing you
        anything.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          className="field-boxed mono"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void connect()}
          style={{ width: 320, padding: "9px 11px" }}
          aria-label="Repository URL"
        />
        <button className="btn-primary" style={{ padding: "9px 14px" }} disabled={busy} onClick={() => void connect()}>
          {busy ? "Connecting…" : "Connect repository"}
        </button>
      </div>
      {error ? (
        <p className="mono" style={{ margin: "12px 0 0", fontSize: 12, color: "var(--fail)" }}>
          {error}
        </p>
      ) : null}
      <p className="mono" style={{ margin: "14px 0 0", fontSize: 12, color: "var(--ink-3)" }}>
        Read access is enough. Nothing is written to your repository unless you ask for a pull
        request.
      </p>
    </Empty>
  );
}
