import { sev } from "../lib/format";

/** Five bars, filled to the severity's rank. Reads at a glance in a dense
 *  table where the colour of a badge alone would not. */
export function Meter({ rank, width = 3, height = 11 }: { rank: number; width?: number; height?: number }) {
  return (
    <span style={{ display: "flex", gap: 2 }} aria-hidden="true">
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          style={{
            width,
            height,
            background: i <= rank ? "var(--ink)" : "var(--rule)",
          }}
        />
      ))}
    </span>
  );
}

export function SeverityBadge({ value, size = 11 }: { value: string; size?: number }) {
  const token = sev(value);
  return (
    <span
      className="mono"
      style={{
        display: "inline-block",
        fontSize: size,
        fontWeight: 700,
        padding: "2px 6px",
        background: token.bg,
        color: token.fg,
        border: `1px solid ${token.border}`,
      }}
    >
      {token.short}
    </span>
  );
}

export function SeverityMark({ value }: { value: string }) {
  const token = sev(value);
  return (
    <span style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <SeverityBadge value={value} />
      <Meter rank={token.rank} width={4} height={13} />
    </span>
  );
}
