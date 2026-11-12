import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import type { PolicyVersion } from "../api/types";
import { Async, Button, EmptyState, Field, Page, Panel, Result, Section, Ts, useAction, useLoad } from "../components/ui";
import "../styles/ops-admin.css";

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
    <Panel title="New version" hint="Versions are immutable. To change the notice, create a new version and activate it.">
      <form className="form" onSubmit={submit}>
        <div className="ops-grid">
          <div className="ops-wide">
            <Field label="Notice text shown to employees" required>
              <textarea required rows={6} value={notice} onChange={(e) => setNotice(e.target.value)} />
            </Field>
          </div>
          <Field label="Contact person or mailbox" required>
            <input required value={contact} onChange={(e) => setContact(e.target.value)} />
          </Field>
        </div>
        <div className="ops-actions">
          <Button variant="primary" type="submit" disabled={act.busy}>
            Create version
          </Button>
          <Result ok={act.ok} err={act.err} />
        </div>
      </form>
    </Panel>
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
    <details className="ops-more">
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
        <div className="ops-actions">
          <Button type="submit" disabled={act.busy}>Activate</Button>
          <Result ok={act.ok} err={act.err} />
        </div>
      </form>
    </details>
  );
}

export function Policies() {
  const list = useLoad(() => get<{ policies: PolicyVersion[] }>("/policies"));
  return (
    <Page title="Policy versions" lead="The monitoring notice employees acknowledge. Each version is fixed once created.">
      <Create onDone={list.reload} />
      <Section title="Versions">
        <Async
          load={list}
          skeleton="lines"
          rows={4}
          isEmpty={(d) => d.policies.length === 0}
          empty={<EmptyState title="No policy versions yet">Create the first version with the form above, then activate it for employees.</EmptyState>}
        >
          {({ policies }) => (
            <ol className="ops-versions" aria-label="Policy versions">
              {policies.map((v) => (
                <li key={v.id}>
                  <div className="ops-vhead">
                    <h3>
                      {v.name} v{v.version}
                    </h3>
                    <span className="meta">
                      Created <Ts iso={v.created_at} />
                    </span>
                    <span className="mono meta" title={v.content_hash}>
                      {v.content_hash.slice(0, 16)}
                    </span>
                  </div>
                  <p className="ops-notice">{v.content.notice_text}</p>
                  <p className="meta">Contact: {v.content.contact}</p>
                  <Activate v={v} />
                </li>
              ))}
            </ol>
          )}
        </Async>
      </Section>
    </Page>
  );
}
