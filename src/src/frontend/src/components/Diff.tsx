/**
 * Renders the unified diff `difflib` produced on the server. The diff is
 * parsed rather than pattern-painted, so the old and new line numbers in the
 * gutters are the real ones a reviewer would see in `git diff`.
 */

type Row =
  | { kind: "hunk"; text: string }
  | { kind: "line"; old: string; new: string; mark: string; code: string; type: "add" | "del" | "ctx" };

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/;

export function parseDiff(diff: string): { files: string[]; rows: Row[] } {
  const rows: Row[] = [];
  const files: string[] = [];
  let oldNo = 0;
  let newNo = 0;

  for (const line of diff.replace(/\n$/, "").split("\n")) {
    if (line.startsWith("diff --git") || line.startsWith("index ")) continue;

    if (line.startsWith("--- ") || line.startsWith("+++ ")) {
      const path = line.slice(4).trim();
      if (path && path !== "/dev/null" && !files.includes(path)) files.push(path);
      continue;
    }

    const hunk = HUNK.exec(line);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[3]);
      rows.push({ kind: "hunk", text: line });
      continue;
    }

    if (line.startsWith("+")) {
      rows.push({ kind: "line", old: "", new: String(newNo++), mark: "+", code: line.slice(1), type: "add" });
    } else if (line.startsWith("-")) {
      rows.push({ kind: "line", old: String(oldNo++), new: "", mark: "-", code: line.slice(1), type: "del" });
    } else if (line.startsWith("\\")) {
      // "\ No newline at end of file" — real diff output, no line numbers.
      rows.push({ kind: "line", old: "", new: "", mark: "", code: line, type: "ctx" });
    } else {
      const code = line.startsWith(" ") ? line.slice(1) : line;
      rows.push({
        kind: "line",
        old: String(oldNo++),
        new: String(newNo++),
        mark: " ",
        code,
        type: "ctx",
      });
    }
  }

  return { files, rows };
}

export function diffStats(diff: string): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) additions += 1;
    else if (line.startsWith("-") && !line.startsWith("---")) deletions += 1;
  }
  return { additions, deletions };
}

const TONE = {
  add: { bg: "var(--add-bg)", fg: "var(--add-fg)" },
  del: { bg: "var(--del-bg)", fg: "var(--del-fg)" },
  ctx: { bg: "transparent", fg: "var(--ink-2)" },
};

export function DiffView({ diff, path }: { diff: string; path: string }) {
  const { files, rows } = parseDiff(diff);
  const before = files.find((f) => f.startsWith("a/")) ?? `a/${path}`;
  const after = files.find((f) => f.startsWith("b/")) ?? `b/${path}`;

  return (
    <div style={{ border: "1px solid var(--rule)", minWidth: 0 }}>
      <div
        className="mono"
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          gap: "4px 14px",
          padding: "8px 14px",
          borderBottom: "1px solid var(--rule)",
          background: "var(--sunk)",
          fontSize: 12,
          color: "var(--ink-3)",
        }}
      >
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          --- {before}
        </span>
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          +++ {after}
        </span>
      </div>

      <div style={{ overflowX: "auto" }}>
        {rows.map((row, i) =>
          row.kind === "hunk" ? (
            <div
              key={i}
              className="mono"
              style={{
                fontSize: 12.5,
                lineHeight: 1.8,
                color: "var(--ink-3)",
                padding: "5px 14px",
                borderBottom: "1px solid var(--rule-2)",
                background: "var(--sunk)",
                whiteSpace: "pre",
                minWidth: "max-content",
              }}
            >
              {row.text}
            </div>
          ) : (
            <div
              key={i}
              className="mono"
              style={{
                display: "grid",
                gridTemplateColumns: "46px 46px 16px auto",
                minWidth: "max-content",
                fontSize: 12.5,
                lineHeight: 1.8,
                background: TONE[row.type].bg,
              }}
            >
              <span
                style={{
                  textAlign: "right",
                  paddingRight: 8,
                  color: "var(--ink-3)",
                  userSelect: "none",
                  borderRight: "1px solid var(--rule-2)",
                  position: "sticky",
                  left: 0,
                  background: "inherit",
                }}
              >
                {row.old}
              </span>
              <span
                style={{
                  textAlign: "right",
                  paddingRight: 8,
                  color: "var(--ink-3)",
                  userSelect: "none",
                  borderRight: "1px solid var(--rule-2)",
                }}
              >
                {row.new}
              </span>
              <span style={{ textAlign: "center", color: TONE[row.type].fg, userSelect: "none" }}>
                {row.mark}
              </span>
              <span style={{ whiteSpace: "pre", padding: "0 12px", color: TONE[row.type].fg }}>
                {row.code || " "}
              </span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}
