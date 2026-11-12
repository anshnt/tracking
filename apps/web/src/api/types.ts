// Mirrors the JSON the API routers return (apps/api/portal/routers/*.py, flows/*.py).
export type Role = "employee" | "manager" | "it" | "security" | "approver" | "admin";
export const ROLES: Role[] = ["employee", "manager", "it", "security", "approver", "admin"];
export const CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];
export const SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;

export interface Me {
  id: string;
  display_name: string;
  email: string;
  roles: Role[];
  status: string;
  timezone: string;
  manager_id: string | null;
}

export interface Policy {
  id: string;
  name: string;
  version: number;
  content_hash: string;
  notice_text: string | null;
  contact: string | null;
  activates_at: string;
  is_exception: boolean;
  expires_at: string | null;
  acknowledged_at: string | null;
}
export interface Category {
  signal: string;
  default: string;
  visible_to: string;
}
export interface CollectionPolicy {
  policy: Policy | null;
  categories: Category[];
}

export interface Deliverable {
  title: string;
  url?: string | null;
}
export interface Task {
  id: string;
  title: string;
  url: string | null;
  state: string;
  due_date: string | null;
  blocker: string | null;
  deliverables: Deliverable[] | null;
  review_requested_at: string | null;
}

export type PostureState = "compliant" | "noncompliant" | "unknown" | "not_applicable";
export interface FailingCheck {
  check: string;
  detail: string | null;
}
export interface Posture {
  asset_id: string;
  ownership: string;
  state: PostureState;
  reason: string | null;
  observed_at: string | null;
  failing_checks: FailingCheck[];
}
export interface Device {
  id: string;
  name: string;
  ownership: "company" | "personal";
  os: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  role_profile: string;
  classification_ceiling: Classification;
  lifecycle_state: string;
  launch_url: string | null;
  posture: Posture;
}

export interface WorkUpdate {
  id: string;
  employee_id: string;
  update_date: string;
  summary: string;
  task_refs: string[];
  deliverables: Deliverable[];
  blocker: string | null;
  created_at: string;
  updated_at: string;
  correction_count: number;
  corrections?: {
    id: string;
    corrected_by: string;
    previous: { summary: string; blocker: string | null };
    reason: string;
    created_at: string;
  }[];
}

export interface ExportDecision {
  reviewer_id: string;
  decision: string;
  reason: string | null;
  created_at: string;
}
export interface ExportRequest {
  id: string;
  requester_id: string;
  object_ref: string;
  object_version: string | null;
  object_checksum: string;
  classification: Classification;
  recipient: string;
  purpose: string;
  status: string;
  reviewer_id: string | null;
  expires_at: string | null;
  stage_error: string | null;
  release_checksum: string | null;
  release_receipt: Record<string, string> | null;
  released_by: string | null;
  released_at: string | null;
  created_at: string;
  decisions: ExportDecision[];
}

export interface Records {
  work_updates: {
    id: string;
    update_date: string;
    summary: string;
    blocker: string | null;
    corrections: number;
    updated_at: string;
  }[];
  posture_observations: {
    asset_id: string;
    source: string;
    observed_at: string;
    state: string;
    failing_checks: FailingCheck[];
  }[];
  security_event_summaries: {
    id: string;
    source: string;
    event_type: string;
    severity: string;
    occurred_at: string;
    classification: string;
  }[];
  export_requests: {
    id: string;
    object_ref: string;
    recipient: string;
    purpose: string;
    classification: string;
    status: string;
    expires_at: string | null;
    created_at: string;
  }[];
  notice_acknowledgements: { policy: string; version: number; acknowledged_at: string }[];
}

export interface OverviewPerson {
  employee_id: string;
  display_name: string;
  assignments: Task[];
  awaiting_review: Task[];
  blockers: Task[];
  overdue: Task[];
  latest_update: { date: string; blocker: string | null } | null;
  missing_update_for: string | null;
}

export interface CaseAction {
  id: string;
  actor_id: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}
export interface CaseEvent {
  id: string;
  source: string;
  event_type: string;
  severity: string;
  occurred_at: string;
  actor: string | null;
  resource: string | null;
}
export interface Case {
  id: string;
  title: string;
  reason: string;
  severity: string;
  status: string;
  owner_id: string | null;
  subject_employee_id: string | null;
  evidence_refs: unknown[];
  events?: CaseEvent[];
  source?: string | null;
  closure_rationale: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  actions?: CaseAction[];
}

export interface OffboardingStep {
  subsystem: string;
  status: string;
  detail: string | null;
  attempts: number;
  verified_at: string | null;
  updated_at: string;
}
export interface OffboardingJob {
  id: string;
  employee_id: string;
  requested_by: string;
  reason: string;
  status: string;
  requested_at: string;
  completed_at: string | null;
  steps: OffboardingStep[];
  outstanding: string[];
}

export interface Connector {
  name: string;
  enabled: boolean;
  polled: boolean;
  last_success_at: string | null;
  last_attempt_at: string | null;
  cursor_age_seconds: number | null;
  last_error: string | null;
  capabilities: Record<string, unknown>;
  stale: boolean;
}
export interface FailedJob {
  id: string;
  kind: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface PolicyVersion {
  id: string;
  name: string;
  version: number;
  content: { notice_text?: string; contact?: string };
  content_hash: string;
  created_at: string;
}
export interface AdminEmployee {
  id: string;
  oidc_subject: string;
  display_name: string;
  email: string;
  manager_id: string | null;
  roles: Role[];
  status: string;
  timezone: string;
}
export interface AdminAsset {
  id: string;
  name: string;
  ownership: "company" | "personal";
  assigned_employee_id: string | null;
  os: string | null;
}
export interface AdminWorkspace {
  id: string;
  owner_id: string;
  name: string;
  role_profile: string;
  classification_ceiling: Classification;
  connection_ref: string | null;
  lifecycle_state: string;
}
