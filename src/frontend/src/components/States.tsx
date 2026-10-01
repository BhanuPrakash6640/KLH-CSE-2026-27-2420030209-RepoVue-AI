import type { ReactNode } from "react";

/** A quiet sweeping rule rather than a spinner: it reads as "still working"
 *  without pretending to know how much is left. */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div style={{ padding: "40px 0", maxWidth: 320 }}>
      <div style={{ height: 3, background: "var(--rule-2)", overflow: "hidden" }}>
        <div className="sweep" style={{ height: 3, width: "45%", background: "var(--ink)" }} />
      </div>
      <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 8 }}>
        {label}
      </div>
    </div>
  );
}

export function ErrorBox({
  message,
  onRetry,
  hint,
}: {
  message: string;
  onRetry?: () => void;
  hint?: ReactNode;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--fail)",
        borderLeftWidth: 3,
        padding: "18px 20px",
        maxWidth: 760,
      }}
      role="alert"
    >
      <div style={{ fontWeight: 600, color: "var(--fail)", fontSize: 16 }}>
        That request did not go through
      </div>
      <p style={{ margin: "8px 0 0", color: "var(--ink-2)" }}>{message}</p>
      {hint ? <p style={{ margin: "10px 0 0", color: "var(--ink-2)" }}>{hint}</p> : null}
      {onRetry ? (
        <div style={{ marginTop: 14 }}>
          <button className="btn" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Empty screens are an invitation to act, so each one carries its own action. */
export function Empty({
  title,
  children,
  accent = "var(--ink)",
}: {
  title: string;
  children?: ReactNode;
  accent?: string;
}) {
  return (
    <div style={{ maxWidth: 660, padding: "44px 0" }}>
      <div style={{ borderLeft: `2px solid ${accent}`, paddingLeft: 18 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 19, fontWeight: 600 }}>{title}</h2>
        <div style={{ color: "var(--ink-2)" }}>{children}</div>
      </div>
    </div>
  );
}

export function Fact({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div
      style={{
        borderBottom: "1px solid var(--rule-2)",
        borderRight: "1px solid var(--rule-2)",
        padding: "14px 16px 14px 0",
      }}
    >
      <div className="mono" style={{ fontSize: 20 }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 3 }}>{label}</div>
    </div>
  );
}
