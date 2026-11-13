/**
 * Renders the snippet the analyzer stored with a finding.
 *
 * The backend keeps two lines of context either side (`_snippet` in
 * services/analyzers.py), so the first rendered line number is
 * `max(1, start_line - 2)` and the lines the model actually cited can be
 * marked without storing per-line metadata.
 */
export function CodeSnippet({
  code,
  startLine,
  endLine,
  path,
  pad = 2,
}: {
  code: string;
  startLine: number;
  endLine: number;
  path: string;
  pad?: number;
}) {
  const lines = code.replace(/\n$/, "").split("\n");
  const firstLine = Math.max(1, startLine - pad);

  return (
    <div style={{ border: "1px solid var(--rule)" }}>
      <div
        className="mono"
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 14,
          padding: "8px 14px",
          borderBottom: "1px solid var(--rule)",
          fontSize: 12,
          color: "var(--ink-3)",
          background: "var(--sunk)",
        }}
      >
        <span
          style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {path}
        </span>
        <span style={{ flex: "none" }}>
          {startLine === endLine ? `line ${startLine}` : `lines ${startLine}–${endLine}`}
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        {lines.map((line, i) => {
          const n = firstLine + i;
          const cited = n >= startLine && n <= endLine;
          return (
            <div
              key={n}
              className="mono"
              style={{
                display: "grid",
                gridTemplateColumns: "52px 14px auto",
                minWidth: "max-content",
                fontSize: 12.5,
                lineHeight: 1.75,
                background: cited ? "var(--del-bg)" : "transparent",
              }}
            >
              <span
                style={{
                  textAlign: "right",
                  paddingRight: 10,
                  color: "var(--ink-3)",
                  userSelect: "none",
                  position: "sticky",
                  left: 0,
                  background: "inherit",
                }}
              >
                {n}
              </span>
              <span style={{ color: "var(--fail)", userSelect: "none" }}>{cited ? "›" : ""}</span>
              <span
                style={{
                  whiteSpace: "pre",
                  paddingRight: 14,
                  color: cited ? "var(--del-fg)" : "var(--ink-2)",
                }}
              >
                {line || " "}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
