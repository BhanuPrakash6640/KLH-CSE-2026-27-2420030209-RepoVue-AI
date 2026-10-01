import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { CATEGORIES, CATEGORY_LABEL } from "../lib/format";
import type { Category } from "../lib/types";

export function NewAnalysisPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const repositoryId = params.get("repository");

  const [url, setUrl] = useState("https://github.com/");
  const [branch, setBranch] = useState("");
  const [commit, setCommit] = useState("");
  const [pr, setPr] = useState("");
  const [categories, setCategories] = useState<Category[]>([...CATEGORIES]);
  const [diffOnly, setDiffOnly] = useState(false);
  const [openPr, setOpenPr] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleCategory = (c: Category) =>
    setCategories((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const analysis = await api.startAnalysis({
        ...(repositoryId ? { repository_id: repositoryId } : { url: url.trim() }),
        branch: branch.trim() || null,
        commit_sha: commit.trim() || null,
        pr_number: pr.trim() ? Number(pr.trim()) : null,
        diff_only: diffOnly,
        open_pr: openPr,
        categories,
      });
      navigate(`/analyses/${analysis.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  };

  const ready = categories.length > 0 && (repositoryId || /github\.com\/.+\/.+/.test(url));

  return (
    <div className="rv-pad" style={{ maxWidth: 720, padding: "64px 32px 80px" }}>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
        Analyse a repository
      </h1>
      <p style={{ margin: "8px 0 40px", color: "var(--ink-2)" }}>
        Point it at a branch or a pull request. Everything else has a sensible default.
      </p>

      <label
        htmlFor="repo-url"
        style={{ display: "block", fontSize: 13, color: "var(--ink-2)", marginBottom: 7 }}
      >
        Repository URL
      </label>
      <input
        id="repo-url"
        className="field"
        value={repositoryId ? "Using the repository you just connected" : url}
        disabled={Boolean(repositoryId)}
        onChange={(e) => setUrl(e.target.value)}
        style={{ fontSize: 15, padding: "11px 12px", borderBottomColor: "var(--ink)" }}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3,minmax(0,1fr))",
          gap: 22,
          marginTop: 32,
        }}
      >
        <Field label="Branch" value={branch} onChange={setBranch} placeholder="default branch" />
        <Field label="Commit" value={commit} onChange={setCommit} placeholder="latest" />
        <Field label="Pull request" value={pr} onChange={setPr} placeholder="none" />
      </div>

      <div style={{ marginTop: 40 }}>
        <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 10 }}>What to look for</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {CATEGORIES.map((c) => {
            const on = categories.includes(c);
            return (
              <button
                key={c}
                onClick={() => toggleCategory(c)}
                aria-pressed={on}
                style={{
                  border: `1px solid ${on ? "var(--ink)" : "var(--rule)"}`,
                  background: on ? "var(--ink)" : "var(--paper)",
                  color: on ? "var(--paper)" : "var(--ink-2)",
                  padding: "7px 13px",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                {CATEGORY_LABEL[c]}
              </button>
            );
          })}
        </div>
        {categories.length === 0 ? (
          <p style={{ margin: "10px 0 0", fontSize: 13, color: "var(--warn)" }}>
            Pick at least one thing to look for.
          </p>
        ) : null}
      </div>

      <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 2 }}>
        <Option
          checked={diffOnly}
          onToggle={() => setDiffOnly((v) => !v)}
          label="Only review what this commit or pull request changed"
          hint="Faster and cheaper. Issues elsewhere in the repository stay unreported."
        />
        <Option
          checked={openPr}
          onToggle={() => setOpenPr((v) => !v)}
          label="Open a pull request with the patches that pass"
          hint="Patches that fail your tests are never proposed, whatever this is set to."
        />
      </div>

      <div style={{ marginTop: 36, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <button
          className="btn-primary"
          style={{ padding: "11px 20px", fontSize: 15 }}
          disabled={busy || !ready}
          onClick={() => void start()}
        >
          {busy ? "Starting…" : "Start analysis"}
        </button>
        <span className="mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>
          A medium repository takes 4–7 minutes.
        </span>
      </div>

      {error ? (
        <p className="mono" style={{ marginTop: 16, fontSize: 12.5, color: "var(--fail)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 13, color: "var(--ink-2)", marginBottom: 7 }}>
        {label}
        <input
          className="field"
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          style={{ marginTop: 7 }}
        />
      </label>
    </div>
  );
}

function Option({
  checked,
  onToggle,
  label,
  hint,
}: {
  checked: boolean;
  onToggle: () => void;
  label: string;
  hint: string;
}) {
  return (
    <button
      onClick={onToggle}
      role="checkbox"
      aria-checked={checked}
      style={{
        display: "flex",
        gap: 12,
        alignItems: "flex-start",
        textAlign: "left",
        border: 0,
        borderTop: "1px solid var(--rule-2)",
        background: "transparent",
        padding: "14px 0",
        cursor: "pointer",
        width: "100%",
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          flex: "none",
          marginTop: 2,
          border: "1px solid var(--ink)",
          background: checked ? "var(--ink)" : "transparent",
        }}
      />
      <span>
        <span style={{ display: "block", fontWeight: 500 }}>{label}</span>
        <span style={{ display: "block", color: "var(--ink-3)", fontSize: 13, marginTop: 2 }}>
          {hint}
        </span>
      </span>
    </button>
  );
}
