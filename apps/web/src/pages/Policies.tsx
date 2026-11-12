import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import type { PolicyVersion } from "../api/types";
import { Async, Empty, Field, Page, Result, Ts, useAction, useLoad } from "../components/ui";

function Create({ onDone }: { onDone: () => void }) {
  const act = useAction();
  const [notice, setNotice] = useState("");
  const [contact, setContact] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/policies", { content: { notice_text: notice, contact } }), "New version created. It applies to nobody until you activate it.")) {
      setNotice("");
      onDone();
    }
  }
  return (
    <form className="card form" onSubmit={submit}>
      <h2>New version</h2>
      <p className="meta">Versions are immutable. To change the notice, create a new version and activate it.</p>
      <Field label="Notice text shown to employees">
        <textarea required rows={6} value={notice} onChange={(e) => setNotice(e.target.value)} />
      </Field>
      <Field label="Contact person or mailbox">
        <input required value={contact} onChange={(e) => setContact(e.target.value)} />
      </Field>
      <button className="primary" disabled={act.busy}>
        Create version
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Activate({ v }: { v: PolicyVersion }) {
  const act = useAction();
  const [scope, setScope] = useState<"all" | "employee">("all");
  const [scopeId, setScopeId] = useState("");
  const [exception, setException] = useState(false);
  const [expires, setExpires] = useState("");
  const [reviewer, setReviewer] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    await act.run(
      () =>
        post(`/policies/${v.id}/activate`, {
          scope_type: scope,
          scope_id: scope === "employee" ? scopeId : null,
          is_exception: exception,
          expires_at: exception && expires ? new Date(expires).toISOString() : null,
          reviewer_id: exception ? reviewer : null,
        }),
      "Activated.",
    );
  }
  return (
    <details>
      <summary>Activate version {v.version}</summary>
      <form className="form" onSubmit={submit}>
        <Field label="Applies to">
          <select value={scope} onChange={(e) => setScope(e.target.value as "all" | "employee")}>
            <option value="all">All employees</option>
            <option value="employee">One employee</option>
          </select>
        </Field>
        {scope === "employee" && (
          <Field label="Employee ID">
            <input required className="mono" value={scopeId} onChange={(e) => setScopeId(e.target.value.trim())} />
          </Field>
        )}
        <label className="check">
          <input type="checkbox" checked={exception} onChange={(e) => setException(e.target.checked)} /> This is a time-limited exception
        </label>
        {exception && (
          <>
            <Field label="Exception expires">
              <input required type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} />
            </Field>
            <Field label="Reviewer ID">
              <input required className="mono" value={reviewer} onChange={(e) => setReviewer(e.target.value.trim())} />
            </Field>
          </>
        )}
        <button disabled={act.busy}>Activate</button>
        <Result ok={act.ok} err={act.err} />
      </form>
    </details>
  );
}

export function Policies() {
  const list = useLoad(() => get<{ policies: PolicyVersion[] }>("/policies"));
  return (
    <Page title="Policy versions">
      <Create onDone={list.reload} />
      <Async load={list}>
        {({ policies }) =>
          policies.length === 0 ? (
            <Empty>No policy versions yet.</Empty>
          ) : (
            <ul className="stack">
              {policies.map((v) => (
                <li key={v.id} className="card">
                  <h3>
                    {v.name} v{v.version}
                  </h3>
                  <p className="meta">
                    Created <Ts iso={v.created_at} />. <span className="mono">{v.content_hash.slice(0, 16)}</span>
                  </p>
                  <p className="prose">{v.content.notice_text}</p>
                  <p>Contact: {v.content.contact}</p>
                  <Activate v={v} />
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
