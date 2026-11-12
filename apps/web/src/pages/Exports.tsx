import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import { CLASSIFICATIONS } from "../api/types";
import type { Classification, ExportRequest } from "../api/types";
import { Async, Empty, Field, Page, Result, StatusTag, Ts, useAction, useLoad, useMe } from "../components/ui";

// Approver/it/admin get a company-wide list from the API, so ask for the caller's own and the max page.
export const MY_EXPORTS_URL = "/export-requests?mine=true&limit=500";
export const onlyMine = (all: ExportRequest[], meId: string) => all.filter((r) => r.requester_id === meId);

const FINAL = ["rejected", "released", "expired", "cancelled"];

function Request({ onSaved }: { onSaved: () => void }) {
  const act = useAction();
  const [f, setF] = useState({
    object_ref: "",
    object_version: "",
    object_checksum: "",
    classification: "internal" as Classification,
    recipient: "",
    purpose: "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(() => post("/export-requests", { ...f, object_version: f.object_version.trim() || null }), "Request submitted for approval.");
    if (ok) {
      setF({ ...f, object_ref: "", object_version: "", object_checksum: "", recipient: "", purpose: "" });
      onSaved();
    }
  }
  return (
    <form className="card form" onSubmit={submit}>
      <h2>Request an export</h2>
      <p className="meta">A different person must approve it. Nothing leaves until it is approved, staged and released.</p>
      <Field label="Object reference" hint="Path or ID of the file inside the approved export area">
        <input required maxLength={512} value={f.object_ref} onChange={set("object_ref")} />
      </Field>
      <Field label="Version (optional)">
        <input maxLength={200} value={f.object_version} onChange={set("object_version")} />
      </Field>
      <Field label="SHA-256 checksum" hint="Binds the approval to exactly this content">
        <input required maxLength={64} pattern="[0-9a-fA-F]{64}" title="64 hex characters" className="mono" value={f.object_checksum} onChange={set("object_checksum")} />
      </Field>
      <Field label="Classification">
        <select value={f.classification} onChange={set("classification")}>
          {CLASSIFICATIONS.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </Field>
      <Field label="Recipient">
        <input required maxLength={500} value={f.recipient} onChange={set("recipient")} />
      </Field>
      <Field label="Business purpose">
        <textarea required rows={3} maxLength={2000} value={f.purpose} onChange={set("purpose")} />
      </Field>
      <button className="primary" disabled={act.busy}>
        Submit request
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

export function Receipt({ r }: { r: ExportRequest }) {
  if (!r.release_receipt) return null;
  const rc = r.release_receipt;
  return (
    <dl className="kv" aria-label="Release receipt">
      <dt>Released at</dt>
      <dd>
        <Ts iso={rc.released_at} />
      </dd>
      <dt>Recipient</dt>
      <dd>{rc.recipient}</dd>
      <dt>Checksum</dt>
      <dd className="mono wrap">{rc.checksum}</dd>
      <dt>Channel note</dt>
      <dd>{rc.channel_note}</dd>
      {r.expires_at && (
        <>
          <dt>Copy expires</dt>
          <dd>
            <Ts iso={r.expires_at} />
          </dd>
        </>
      )}
    </dl>
  );
}

export function ExportSummary({ r }: { r: ExportRequest }) {
  return (
    <>
      <h3 className="wrap">{r.object_ref}</h3>
      <p className="meta">
        <StatusTag status={r.status} /> {r.classification}. To {r.recipient}. Requested <Ts iso={r.created_at} />.
      </p>
      <p className="prose">{r.purpose}</p>
      <p className="meta mono wrap">
        {r.object_version ? `version ${r.object_version}, ` : ""}sha256 {r.object_checksum}
      </p>
      {r.decisions.map((d, i) => (
        <p key={i} className="meta">
          Decision: {d.decision} <Ts iso={d.created_at} />
          {d.reason ? `, ${d.reason}` : ""}
        </p>
      ))}
      {r.stage_error && <p className="msg err">Staging failed: {r.stage_error}</p>}
      {r.status === "approved" && <p className="muted">Approved, waiting for the worker to stage the file.</p>}
      <Receipt r={r} />
    </>
  );
}

function Cancel({ id, onDone }: { id: string; onDone: () => void }) {
  const act = useAction();
  const [reason, setReason] = useState("");
  return (
    <details>
      <summary>Cancel this request</summary>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await act.run(() => post(`/export-requests/${id}/cancel`, { reason }), "Cancelled.")) onDone();
        }}
      >
        <Field label="Reason">
          <input required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <button disabled={act.busy}>Confirm cancel</button>
        <Result ok={act.ok} err={act.err} />
      </form>
    </details>
  );
}

export function Exports() {
  const me = useMe();
  const list = useLoad(() => get<ExportRequest[]>(MY_EXPORTS_URL));
  return (
    <Page title="My exports">
      <Request onSaved={list.reload} />
      <h2>My requests</h2>
      <Async load={list}>
        {(all) => {
          const mine = onlyMine(all, me.id);
          return mine.length === 0 ? (
            <Empty>You have not requested an export.</Empty>
          ) : (
            <ul className="stack">
              {mine.map((r) => (
                <li key={r.id} className="card">
                  <ExportSummary r={r} />
                  {!FINAL.includes(r.status) && <Cancel id={r.id} onDone={list.reload} />}
                </li>
              ))}
            </ul>
          );
        }}
      </Async>
    </Page>
  );
}
