import type { ReactNode } from "react";
import { postureBadge } from "../lib/posture";
import type { Badge as BadgeInfo } from "../lib/posture";

/** ok and bad are outcomes, warn needs action, info is waiting on someone, accent is moving, unknown is neutral and outlined. */
export type Tone = BadgeInfo["tone"] | "info" | "accent";

/** A small glyph per tone so state never rests on colour alone. */
const GLYPH: Record<Tone, string> = {
  ok: "M3 8.5l3.2 3L13 4.5",
  bad: "M4 4l8 8M12 4l-8 8",
  warn: "M8 3.5v5.5M8 12.2v.01",
  muted: "M4 8h8",
  unknown: "M6 6.2a2 2 0 1 1 2.8 1.8c-.5.3-.8.7-.8 1.3M8 12.2v.01",
  info: "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM8 5v3.2l2 1.2",
  accent: "M3.5 8h9M9 4.5L12.5 8 9 11.5",
};

/** One recipe for every state: posture, export, offboarding, task. Pass the text label as children. */
export function StatusPill({ tone, glyph = true, children }: { tone: Tone; glyph?: boolean; children: ReactNode }) {
  return (
    <span className={`pill pill-${tone}`}>
      {glyph && (
        <svg className="pill-glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d={GLYPH[tone]} />
        </svg>
      )}
      {children}
    </span>
  );
}

/** Kept for existing importers; `mark` is superseded by the tone glyph. */
export function Tag({ tone, children }: { tone: Tone; mark?: string; children: ReactNode }) {
  return <StatusPill tone={tone}>{children}</StatusPill>;
}

export function PostureBadge({ state }: { state: string }) {
  const b = postureBadge(state);
  return <StatusPill tone={b.tone}>{b.label}</StatusPill>;
}

const BAD = ["failed", "rejected", "noncompliant", "critical", "high", "incomplete", "blocked", "overdue"];
const GOOD = ["released", "succeeded", "verified", "verified_complete", "approved", "closed", "resolved", "compliant", "active"];
const WARN = ["manual_required", "skipped_not_configured", "medium"];
const INFO = ["requested", "reviewed", "staged", "in_review", "pending"];
const ACCENT = ["in_progress", "running"];

export function statusTone(status: string): Tone {
  return BAD.includes(status) ? "bad" : GOOD.includes(status) ? "ok" : WARN.includes(status) ? "warn" : INFO.includes(status) ? "info" : ACCENT.includes(status) ? "accent" : "muted";
}

/** Raw API status (snake_case) to a pill. */
export function StatusTag({ status }: { status: string }) {
  const text = status.replace(/_/g, " ");
  return <StatusPill tone={statusTone(status)}>{text.charAt(0).toUpperCase() + text.slice(1)}</StatusPill>;
}
