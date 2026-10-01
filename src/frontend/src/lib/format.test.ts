import { describe, expect, it } from "vitest";
import { diffStats, parseDiff } from "../components/Diff";
import { cite, clock, seconds, sev, signedPct, total } from "./format";

/** A real `difflib.unified_diff` payload of the kind services/patcher.py emits. */
const DIFF = `--- a/app/api/ledger/search.py
+++ b/app/api/ledger/search.py
@@ -112,7 +112,9 @@ def search_entries(filter: str, column: str):
     conn = get_connection()
     cur = conn.cursor()
-    sql = f"SELECT * FROM entries WHERE {column} ILIKE '%{filter}%'"
-    cur.execute(sql)
+    if column not in SEARCHABLE_COLUMNS:
+        raise ValueError(f"column not searchable: {column}")
+    sql = f"SELECT * FROM entries WHERE {column} ILIKE %s"
+    cur.execute(sql, (f"%{filter}%",))
     return [Entry.from_row(r) for r in cur.fetchall()]
`;

describe("parseDiff", () => {
  const { files, rows } = parseDiff(DIFF);

  it("picks up both sides of the file header", () => {
    expect(files).toEqual(["a/app/api/ledger/search.py", "b/app/api/ledger/search.py"]);
  });

  it("keeps the hunk header as its own row", () => {
    expect(rows.filter((r) => r.kind === "hunk")).toHaveLength(1);
  });

  it("numbers context lines from the hunk header", () => {
    const first = rows.find((r) => r.kind === "line");
    expect(first).toMatchObject({ old: "112", new: "112", type: "ctx" });
  });

  it("advances only the old gutter on a deletion", () => {
    const deletions = rows.filter((r) => r.kind === "line" && r.type === "del");
    expect(deletions).toHaveLength(2);
    expect(deletions[0]).toMatchObject({ old: "114", new: "" });
    expect(deletions[1]).toMatchObject({ old: "115", new: "" });
  });

  it("advances only the new gutter on an addition", () => {
    const additions = rows.filter((r) => r.kind === "line" && r.type === "add");
    expect(additions).toHaveLength(4);
    expect(additions[0]).toMatchObject({ old: "", new: "114" });
    expect(additions[3]).toMatchObject({ old: "", new: "117" });
  });

  it("realigns the gutters after the hunk", () => {
    const lines = rows.filter((r) => r.kind === "line");
    const last = lines[lines.length - 1];
    expect(last).toMatchObject({ old: "116", new: "118", type: "ctx" });
  });

  it("strips the leading marker from the rendered code", () => {
    const addition = rows.find((r) => r.kind === "line" && r.type === "add");
    expect(addition && "code" in addition && addition.code.startsWith("    if column")).toBe(true);
  });
});

describe("diffStats", () => {
  it("counts changed lines without counting the file headers", () => {
    expect(diffStats(DIFF)).toEqual({ additions: 4, deletions: 2 });
  });
});

describe("format helpers", () => {
  it("falls back to info for a severity it does not know", () => {
    expect(sev("nonsense").short).toBe("INFO");
    expect(sev("critical").rank).toBe(5);
  });

  it("signs a runtime delta so an improvement reads as negative", () => {
    expect(signedPct(-38)).toBe("-38.0%");
    expect(signedPct(4.2)).toBe("+4.2%");
    expect(signedPct(null)).toBe("—");
  });

  it("switches to minutes past a minute", () => {
    expect(seconds(4.219)).toBe("4.22s");
    expect(seconds(92)).toBe("1m 32s");
  });

  it("renders a running clock", () => {
    expect(clock(0)).toBe("00:00");
    expect(clock(65_000)).toBe("01:05");
  });

  it("sums a counts map", () => {
    expect(total({ critical: 2, high: 3 })).toBe(5);
    expect(total(undefined)).toBe(0);
  });

  it("joins the taxonomy references it has", () => {
    expect(cite({ cwe: "CWE-89", owasp: "A03:2021" })).toBe("CWE-89 · A03:2021");
    expect(cite({ cwe: null, owasp: null })).toBe("—");
  });
});
