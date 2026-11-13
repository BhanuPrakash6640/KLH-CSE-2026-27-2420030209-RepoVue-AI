import type { Category, FindingStatusValue, Severity, Verdict } from "./types";

/** Severity tokens from the design brief. `rank` drives the five-bar meter. */
export const SEV: Record<
  Severity,
  { short: string; label: string; rank: number; bg: string; fg: string; border: string }
> = {
  critical: {
    short: "CRIT",
    label: "Critical",
    rank: 5,
    bg: "var(--sev5-bg)",
    fg: "var(--sev5-fg)",
    border: "var(--sev5-bg)",
  },
  high: {
    short: "HIGH",
    label: "High",
    rank: 4,
    bg: "var(--sev4-bg)",
    fg: "var(--sev4-fg)",
    border: "var(--sev4-bg)",
  },
  medium: {
    short: "MED",
    label: "Medium",
    rank: 3,
    bg: "var(--sev3-bg)",
    fg: "var(--sev3-fg)",
    border: "var(--sev3-bg)",
  },
  low: {
    short: "LOW",
    label: "Low",
    rank: 2,
    bg: "var(--sev2-bg)",
    fg: "var(--sev2-fg)",
    border: "var(--sev2-bg)",
  },
  info: {
    short: "INFO",
    label: "Info",
    rank: 1,
    bg: "var(--sev1-bg)",
    fg: "var(--sev1-fg)",
    border: "var(--rule)",
  },
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

export function sev(value: string): (typeof SEV)[Severity] {
  return SEV[(value as Severity) in SEV ? (value as Severity) : "info"];
}

export const CATEGORY_LABEL: Record<Category, string> = {
  logical_bug: "Logical bugs",
  security: "Security",
  performance: "Performance",
  architecture: "Architecture",
};

export const CATEGORIES: Category[] = [
  "logical_bug",
  "security",
  "performance",
  "architecture",
];

export function categoryLabel(value: string): string {
  return CATEGORY_LABEL[value as Category] ?? titleCase(value);
}

/** Status copy is written from the reviewer's point of view, not the schema's. */
export const FINDING_STATUS: Record<FindingStatusValue, { label: string; fg: string }> = {
  open: { label: "Open", fg: "var(--ink-2)" },
  patch_proposed: { label: "Patch proposed", fg: "var(--ink-2)" },
  validated: { label: "Fix verified", fg: "var(--pass)" },
  rejected: { label: "Patch rejected", fg: "var(--fail)" },
  false_positive: { label: "False positive", fg: "var(--ink-3)" },
  resolved: { label: "Resolved", fg: "var(--pass)" },
};

export function findingStatus(value: string) {
  return FINDING_STATUS[value as FindingStatusValue] ?? { label: titleCase(value), fg: "var(--ink-2)" };
}

export const VERDICT: Record<Verdict, { headline: string; fg: string; border: string; bg: string }> = {
  pass: {
    headline: "Your tests passed with this patch applied",
    fg: "var(--pass)",
    border: "var(--pass)",
    bg: "transparent",
  },
  fail: {
    headline: "This patch broke your tests",
    fg: "var(--fail)",
    border: "var(--fail)",
    bg: "transparent",
  },
  skipped: {
    headline: "Not validated",
    fg: "var(--warn)",
    border: "var(--warn)",
    bg: "transparent",
  },
  error: {
    headline: "Validation could not run",
    fg: "var(--warn)",
    border: "var(--warn)",
    bg: "transparent",
  },
};

export function verdict(value: string) {
  return VERDICT[(value as Verdict) in VERDICT ? (value as Verdict) : "skipped"];
}

export const PATCH_STATUS_LABEL: Record<string, string> = {
  generated: "Written, awaiting review",
  validating: "Running your tests",
  accepted: "Accepted",
  rejected: "Rejected",
  published: "Published in a pull request",
};

/** Nine pipeline stages, in order, with the copy the running screen shows. */
export const STAGES: { key: string; label: string; progress: number }[] = [
  { key: "clone", label: "Clone", progress: 5 },
  { key: "index", label: "Index symbols", progress: 20 },
  { key: "embed", label: "Embed", progress: 35 },
  { key: "review", label: "Review", progress: 65 },
  { key: "triage", label: "Triage", progress: 72 },
  { key: "fix", label: "Write patches", progress: 82 },
  { key: "validate", label: "Run your tests", progress: 92 },
  { key: "publish", label: "Publish", progress: 98 },
  { key: "done", label: "Done", progress: 100 },
];

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-GB");
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function signedPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 60) return `${value.toFixed(value < 10 ? 2 : 0)}s`;
  const mins = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return `${mins}m ${String(rest).padStart(2, "0")}s`;
}

export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "—";
}

export function timeOfDay(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** Sum of a counts map, used all over the dashboard. */
export function total(counts: Record<string, number> | undefined): number {
  if (!counts) return 0;
  return Object.values(counts).reduce((a, b) => a + b, 0);
}

export function cite(finding: { cwe: string | null; owasp: string | null }): string {
  return [finding.cwe, finding.owasp].filter(Boolean).join(" · ") || "—";
}
