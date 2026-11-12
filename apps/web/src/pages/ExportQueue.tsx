import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import type { ExportRequest } from "../api/types";
import { hasRole } from "../lib/nav";
import { Async, Empty, Field, Page, Result, useAction, useLoad, useMe } from "../components/ui";
import { ExportSummary } from "./Exports";

function Decide({ r, onDone }: { r: ExportRequest; onDone: () => void }) {
  const act = useAction();
  const [reason, setReason] = useState("");
  async function go(decision: "approved" | "rejected") {
    if (await act.run(() => post(`/export-requests/${r.id}/decisions`, { decision, reason: reason.trim() || null }), `Recorded: ${decision}.`)) onDone();
  }
  return (
    <div className="form">
      <p className="meta">
        {r.classification === "restricted" ? "Restricted: needs two distinct approvers, one after the other. " : ""}
        You cannot approve your own request.
      </p>
      <Field label="Reason (required to reject)">
        <input maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="row">
        <button type="button" className="primary" disabled={act.busy} onClick={() => go("approved")}>
          Approve
        </button>
        <button type="button" disabled={act.busy || !reason.trim()} onClick={() => go("rejected")}>
          Reject
        </button>
      </div>
      <Result ok={act.ok} err={act.err} />
    </div>
  );
}

function Release({ r, onDone }: { r: ExportRequest; onDone: () => void }) {
  const act = useAction();
  const [recipient, setRecipient] = useState("");
  const [note, setNote] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post(`/export-requests/${r.id}/release`, { recipient, channel_note: note }), "Released. The receipt is on the request.")) onDone();
  }
  return (
    <form className="form" onSubmit={submit}>
      <p className="meta">Re-type the approved recipient to confirm who receives the file. The release is checked again against the approved checksum and expiry.</p>
      <Field label="Confirm recipient" hint={`Approved recipient: ${r.recipient}`}>
        <input required maxLength={500} value={recipient} onChange={(e) => setRecipient(e.target.value)} />
      </Field>
      <Field label="Delivery channel note">
        <input required maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <button className="primary" disabled={act.busy}>
        Release
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

export const QUEUE_LIMIT = 500; // API maximum
const ACTIONABLE = ["requested", "reviewed", "staged"];
/** One URL per status: the API takes a single status, and an unfiltered page would hide old pending rows behind newer ones. */
export const queueUrls = (status: string): string[] =>
  (status === "" ? ACTIONABLE : status === "all" ? [""] : [status]).map((s) => `/export-requests?limit=${QUEUE_LIMIT}${s ? `&status=${s}` : ""}`);

export function ExportQueue() {
  const me = useMe();
  const [status, setStatus] = useState("");
  const list = useLoad(async () => {
    const pages = await Promise.all(queueUrls(status).map((u) => get<ExportRequest[]>(u)));
    return { rows: pages.flat().sort((a, b) => b.created_at.localeCompare(a.created_at)), truncated: pages.some((p) => p.length >= QUEUE_LIMIT) };
  }, [status]);
  const approver = hasRole(me.roles, "approver");
  const releaser = hasRole(me.roles, "approver", "it");
  return (
    <Page title="Export queue" lead="Approved destination, justification, expiry, reviewers and release receipts.">
      <Field label="Filter by status">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Needs action (requested, reviewed, staged)</option>
          <option value="all">All</option>
          {["requested", "reviewed", "approved", "staged", "released", "rejected", "expired", "cancelled"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </Field>
      <Async load={list}>
        {({ rows, truncated }) =>
          rows.length === 0 ? (
            <Empty>No export requests.</Empty>
          ) : (
            <>
            {truncated && <p className="msg err" role="alert">Showing the newest {QUEUE_LIMIT} only. Older requests are hidden: filter by status.</p>}
            <ul className="stack">
              {rows.map((r) => {
                const own = r.requester_id === me.id;
                return (
                  <li key={r.id} className="card">
                    <ExportSummary r={r} />
                    {own && <p className="muted">This is your own request, so you cannot decide or release it.</p>}
                    {!own && approver && (r.status === "requested" || r.status === "reviewed") && <Decide r={r} onDone={list.reload} />}
                    {!own && releaser && r.status === "staged" && <Release r={r} onDone={list.reload} />}
                  </li>
                );
              })}
            </ul>
            </>
          )
        }
      </Async>
    </Page>
  );
}
