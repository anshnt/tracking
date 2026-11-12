import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import type { AdminEmployee, OffboardingJob } from "../api/types";
import { Async, Button, DataTable, EmptyState, Field, IdCell, Page, Panel, Result, Section, StatusTag, Ts, useAction, useLoad } from "../components/ui";
import { newKey } from "../lib/time";
import "../styles/ops-admin.css";

const HUMAN = ["manual_required", "failed", "skipped_not_configured"];
// Mirrors KIND internal/verify in flows/offboarding.py: the API refuses a hand-recorded completion for these (409).
export const SYSTEM_STEPS = ["terminate_portal_sessions", "revoke_export_grants", "verify"];
export const needsHuman = (s: { subsystem: string; status: string }) => HUMAN.includes(s.status) && !SYSTEM_STEPS.includes(s.subsystem);
export const needsRetry = (s: { subsystem: string; status: string }) => HUMAN.includes(s.status) && SYSTEM_STEPS.includes(s.subsystem);

const stepName = (s: string) => {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

function Start({ onDone }: { onDone: () => void }) {
  const act = useAction();
  const people = useLoad(() => get<{ employees: AdminEmployee[] }>("/admin/employees?limit=500").catch(() => ({ employees: null })));
  const [id, setId] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reason, setReason] = useState("");
  const key = useRef(newKey()); // a double click replays the same request instead of starting two jobs
  const target = people.data?.employees?.find((e) => e.id === id);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post("/offboarding-jobs", { employee_id: id, confirm_employee_id: confirm, reason }, { "Idempotency-Key": key.current }),
      "Offboarding started. Sessions are revoked now; the remaining steps run in the worker.",
    );
    if (ok) {
      key.current = newKey();
      setId("");
      setConfirm("");
      setReason("");
      onDone();
    }
  }
  return (
    <Panel title="Start offboarding" hint="This signs the person out everywhere and starts revoking access. It never touches a personal device. It cannot be undone from this page.">
      <form className="form" onSubmit={submit}>
        <div className="ops-grid">
          <Field label="Employee ID" required>
            <input required className="mono" list="emp-ids" value={id} onChange={(e) => setId(e.target.value.trim())} />
          </Field>
          <Field label="Confirm the employee ID" hint="Type it again" required error={confirm && id !== confirm ? "The two IDs do not match." : null}>
            <input required className="mono" value={confirm} onChange={(e) => setConfirm(e.target.value.trim())} />
          </Field>
          <div className="ops-wide">
            <Field label="Reason" required>
              <textarea required rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
        </div>
        <datalist id="emp-ids">
          {people.data?.employees?.filter((e) => e.status === "active").map((e) => (
            <option key={e.id} value={e.id}>
              {e.display_name}
            </option>
          ))}
        </datalist>
        {people.data && !people.data.employees && (
          <p className="msg err" role="alert">
            Name lookup is unavailable for your role. Check the employee ID against the directory before you confirm: this signs that person out everywhere.
          </p>
        )}
        {people.data?.employees && id && !target && <p className="msg err" role="alert">No employee with this ID was found.</p>}
        {target && <p aria-live="polite">Selected: <strong>{target.display_name}</strong> ({target.email})</p>}
        <div className="ops-actions">
          <Button variant="danger" type="submit" disabled={act.busy || !id || id !== confirm}>
            Start offboarding
          </Button>
          <Result ok={act.ok} err={act.err} />
        </div>
      </form>
    </Panel>
  );
}

function ManualStep({ jobId, subsystem, onDone }: { jobId: string; subsystem: string; onDone: () => void }) {
  const act = useAction();
  const [note, setNote] = useState("");
  return (
    <form
      className="ops-step-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await act.run(() => post(`/offboarding-jobs/${jobId}/steps/${subsystem}/complete`, { note }), "Recorded.")) onDone();
      }}
    >
      <Field label={`Note for ${subsystem.replace(/_/g, " ")}`} hint="What was done and where it can be checked">
        <input required maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button type="submit" disabled={act.busy}>Mark done</Button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Job({ j, onChanged }: { j: OffboardingJob; onChanged: () => void }) {
  const act = useAction();
  const done = j.status === "verified_complete";
  return (
    <li>
      <div className="ops-job-head">
        <h3>
          <IdCell id={j.employee_id} head={13} />
        </h3>
        <StatusTag status={j.status} />
        <span className="meta">
          Requested <Ts iso={j.requested_at} />
          {j.completed_at && (
            <>
              , completed <Ts iso={j.completed_at} />
            </>
          )}
        </span>
      </div>
      <p className="meta">Reason: {j.reason}</p>
      {!done && (
        <p className="ops-banner">
          Not complete. Outstanding: {j.outstanding.length ? j.outstanding.map((s) => s.replace(/_/g, " ")).join(", ") : "verification pending"}.
        </p>
      )}
      <DataTable label={`Offboarding steps for ${j.employee_id}`}>
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">Attempts</th>
            <th scope="col">Detail</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {j.steps.map((s) => (
            <tr key={s.subsystem}>
              <th scope="row">{stepName(s.subsystem)}</th>
              <td>
                <StatusTag status={s.status} />
              </td>
              <td className="num">{s.attempts}</td>
              <td className="ops-wrap">
                {s.detail ?? ""}
                {needsHuman(s) && <ManualStep jobId={j.id} subsystem={s.subsystem} onDone={onChanged} />}
                {needsRetry(s) && <p className="ops-cell-note">The system completes this step. Use Retry automatic steps below.</p>}
              </td>
              <td>
                <Ts iso={s.updated_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
      {!done && (
        <div className="ops-actions">
          <Button disabled={act.busy} onClick={async () => (await act.run(() => post(`/offboarding-jobs/${j.id}/retry`), "Retry queued.")) && onChanged()}>
            Retry automatic steps
          </Button>
          <Result ok={act.ok} err={act.err} />
        </div>
      )}
    </li>
  );
}

export function Offboarding() {
  const list = useLoad(() => get<OffboardingJob[]>("/offboarding-jobs"));
  return (
    <Page title="Offboarding" lead="A job is only complete when every step succeeded or a person recorded it and the final verification passed.">
      <Start onDone={list.reload} />
      <Section title="Jobs">
        <Async
          load={list}
          rows={3}
          isEmpty={(jobs) => jobs.length === 0}
          empty={<EmptyState title="No offboarding jobs">Jobs appear here once you start an offboarding with the form above.</EmptyState>}
        >
          {(jobs) => (
            <ul className="ops-stack">
              {jobs.map((j) => (
                <Job key={j.id} j={j} onChanged={list.reload} />
              ))}
            </ul>
          )}
        </Async>
      </Section>
    </Page>
  );
}
