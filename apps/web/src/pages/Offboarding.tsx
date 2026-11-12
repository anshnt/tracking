import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import type { AdminEmployee, OffboardingJob } from "../api/types";
import { Async, Empty, Field, Page, Result, StatusTag, Ts, useAction, useLoad } from "../components/ui";
import { newKey } from "../lib/time";

const HUMAN = ["manual_required", "failed", "skipped_not_configured"];
// Mirrors KIND internal/verify in flows/offboarding.py: the API refuses a hand-recorded completion for these (409).
export const SYSTEM_STEPS = ["terminate_portal_sessions", "revoke_export_grants", "verify"];
export const needsHuman = (s: { subsystem: string; status: string }) => HUMAN.includes(s.status) && !SYSTEM_STEPS.includes(s.subsystem);
export const needsRetry = (s: { subsystem: string; status: string }) => HUMAN.includes(s.status) && SYSTEM_STEPS.includes(s.subsystem);

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
    <form className="card form" onSubmit={submit}>
      <h2>Start offboarding</h2>
      <p className="meta">
        This signs the person out everywhere and starts revoking access. It never touches a personal device. It cannot be undone from this page.
      </p>
      <Field label="Employee ID">
        <input required className="mono" list="emp-ids" value={id} onChange={(e) => setId(e.target.value.trim())} />
      </Field>
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
      <Field label="Type the employee ID again to confirm">
        <input required className="mono" value={confirm} onChange={(e) => setConfirm(e.target.value.trim())} />
      </Field>
      <Field label="Reason">
        <textarea required rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <button className="primary" disabled={act.busy || !id || id !== confirm}>
        Start offboarding
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function ManualStep({ jobId, subsystem, onDone }: { jobId: string; subsystem: string; onDone: () => void }) {
  const act = useAction();
  const [note, setNote] = useState("");
  return (
    <form
      className="inline"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await act.run(() => post(`/offboarding-jobs/${jobId}/steps/${subsystem}/complete`, { note }), "Recorded.")) onDone();
      }}
    >
      <Field label={`Note for ${subsystem.replace(/_/g, " ")}`} hint="What was done and where it can be checked">
        <input required maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <button disabled={act.busy}>Mark done</button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Job({ j, onChanged }: { j: OffboardingJob; onChanged: () => void }) {
  const act = useAction();
  return (
    <li className="card">
      <h3 className="mono wrap">{j.employee_id}</h3>
      <p className="meta">
        <StatusTag status={j.status} /> Requested <Ts iso={j.requested_at} />
        {j.completed_at && (
          <>
            , completed <Ts iso={j.completed_at} />
          </>
        )}
        . Reason: {j.reason}
      </p>
      {j.status !== "verified_complete" && (
        <p className="msg err">
          Not complete. Outstanding: {j.outstanding.length ? j.outstanding.map((s) => s.replace(/_/g, " ")).join(", ") : "verification pending"}.
        </p>
      )}
      <div className="tablewrap">
        <table>
          <caption className="sr">Offboarding steps</caption>
          <thead>
            <tr>
              <th scope="col">Step</th>
              <th scope="col">Status</th>
              <th scope="col">Detail</th>
              <th scope="col">Updated</th>
            </tr>
          </thead>
          <tbody>
            {j.steps.map((s) => (
              <tr key={s.subsystem}>
                <th scope="row">{s.subsystem.replace(/_/g, " ")}</th>
                <td>
                  <StatusTag status={s.status} />
                </td>
                <td>
                  {s.detail ?? ""}
                  {needsHuman(s) && <ManualStep jobId={j.id} subsystem={s.subsystem} onDone={onChanged} />}
                  {needsRetry(s) && <p className="meta">The system completes this step. Use Retry automatic steps below.</p>}
                </td>
                <td>
                  <Ts iso={s.updated_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {j.status !== "verified_complete" && (
        <>
          <button type="button" disabled={act.busy} onClick={async () => (await act.run(() => post(`/offboarding-jobs/${j.id}/retry`), "Retry queued.")) && onChanged()}>
            Retry automatic steps
          </button>
          <Result ok={act.ok} err={act.err} />
        </>
      )}
    </li>
  );
}

export function Offboarding() {
  const list = useLoad(() => get<OffboardingJob[]>("/offboarding-jobs"));
  return (
    <Page title="Offboarding" lead="A job is only complete when every step succeeded or a person recorded it and the final verification passed.">
      <Start onDone={list.reload} />
      <h2>Jobs</h2>
      <Async load={list}>
        {(jobs) =>
          jobs.length === 0 ? (
            <Empty>No offboarding jobs.</Empty>
          ) : (
            <ul className="stack">
              {jobs.map((j) => (
                <Job key={j.id} j={j} onChanged={list.reload} />
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
