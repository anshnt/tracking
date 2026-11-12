import type { PostureState } from "../api/types";

export interface Badge {
  label: string;
  tone: "ok" | "bad" | "warn" | "muted" | "unknown";
  /** Symbol so the state is never conveyed by colour alone. */
  mark: string;
}

const MAP: Record<PostureState, Badge> = {
  compliant: { label: "Compliant", tone: "ok", mark: "✓" },
  noncompliant: { label: "Noncompliant", tone: "bad", mark: "!" },
  unknown: { label: "Unknown", tone: "unknown", mark: "?" },
  not_applicable: { label: "Not applicable", tone: "muted", mark: "-" },
};

/** Unrecognised states fall back to unknown, never to green. */
export function postureBadge(state: string): Badge {
  return MAP[state as PostureState] ?? MAP.unknown;
}

const REASONS: Record<string, string> = {
  personal_device: "Personal device: nothing is checked or collected.",
  no_asset: "No device is linked to this workspace.",
  no_heartbeat: "The device agent has not reported a heartbeat.",
  future_observation: "The device clock is ahead; the observation is not trusted.",
  no_observation: "No observation has been received yet.",
  stale_observation: "The last observation is too old to trust.",
  expired_observation: "The last observation has expired.",
  stale_heartbeat: "The device agent has stopped reporting.",
  failing_checks: "One or more checks are failing.",
  reported_unknown: "The device reported an unknown state.",
};

export function postureReason(reason: string | null): string {
  return reason ? (REASONS[reason] ?? reason) : "";
}
