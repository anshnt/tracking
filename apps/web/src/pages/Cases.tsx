import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import { SEVERITIES } from "../api/types";
import type { Case } from "../api/types";
import { Async, Empty, Field, Page, Result, StatusTag, Ts, useAction, useLoad, useMe } from "../components/ui";

const ACTIONS = [
  ["comment", "Comment"],
  ["assign", "Assign to a security analyst"],
  ["change_severity", "Change severity"],
  ["link_event", "Link a security event"],
  ["close", "Close with rationale"],
  ["reopen", "Reopen"],
] as const;

function ActionForm({ c, onDone }: { c: Case; onDone: () => void }) {
  const me = useMe();
  const act = useAction();
  const [kind, setKind] = useState<(typeof ACTIONS)[number][0]>(c.status === "closed" ? "reopen" : "comment");
  const [text, setText] = useState("");
  const [assignee, setAssignee] = useState(me.id);
  const [severity, setSeverity] = useState("medium");
  const [eventId, setEventId] = useState("");

  function body(): Record<string, string> {
    switch (kind) {
      case "comment":
        return { action: kind, text };
      case "assign":
        return { action: kind, assignee_id: assignee };
      case "change_severity":
        return { action: kind, severity };
      case "link_event":
        return { action: kind, event_id: eventId };
      case "close":
        return { action: kind, rationale: text };
      case "reopen":
        return { action: kind, reason: text };
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post(`/cases/${c.id}/actions`, body()), "Action recorded.")) {
      setText("");
      onDone();
    }
  }
  const needsText = kind === "comment" || kind === "close" || kind === "reopen";
  return (
    <form className="form" onSubmit={submit}>
      <h3>Add an action</h3>
      <Field label="Action">
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          {ACTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </Field>
      {needsText && (
        <Field label={kind === "comment" ? "Comment" : kind === "close" ? "Closure rationale" : "Reason"}>
          <textarea required rows={3} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      )}
      {kind === "assign" && (
        <Field label="Analyst ID" hint="Defaults to you. Must be an active user with the security role.">
          <input required className="mono" value={assignee} onChange={(e) => setAssignee(e.target.value)} />
        </Field>
      )}
      {kind === "change_severity" && (
        <Field label="Severity">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
      )}
      {kind === "link_event" && (
        <Field label="Event ID">
          <input required className="mono" value={eventId} onChange={(e) => setEventId(e.target.value)} />
        </Field>
      )}
      <button className="primary" disabled={act.busy}>
        Record action
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const load = useLoad(() => get<Case>(`/cases/${id}`), [id]);
  return (
    <Async load={load}>
      {(c) => (
        <article className="card" aria-labelledby="case-h">
          <h2 id="case-h">{c.title}</h2>
          <p className="meta">
            <StatusTag status={c.severity} /> <StatusTag status={c.status} /> Opened <Ts iso={c.created_at} />, updated <Ts iso={c.updated_at} />
          </p>
          <p className="prose">{c.reason}</p>
          <dl className="kv">
            <dt>Owner</dt>
            <dd className="mono wrap">{c.owner_id ?? "unassigned"}</dd>
            <dt>Subject</dt>
            <dd className="mono wrap">{c.subject_employee_id ?? "not linked"}</dd>
            <dt>Source</dt>
            <dd>{c.source ?? "none"}</dd>
            {c.closure_rationale && (
              <>
                <dt>Closure rationale</dt>
                <dd>{c.closure_rationale}</dd>
              </>
            )}
          </dl>
          <h3>Evidence</h3>
          {!c.events || c.events.length === 0 ? (
            <Empty>No linked events.</Empty>
          ) : (
            <ol className="plain">
              {c.events.map((e) => (
                <li key={e.id}>
                  <Ts iso={e.occurred_at} /> <StatusTag status={e.severity} /> {e.source}: {e.event_type}
                  {e.resource ? ` on ${e.resource}` : ""}
                </li>
              ))}
            </ol>
          )}
          <h3>Action history</h3>
          {!c.actions || c.actions.length === 0 ? (
            <Empty>No actions yet.</Empty>
          ) : (
            <ol className="plain">
              {c.actions.map((a) => (
                <li key={a.id}>
                  <Ts iso={a.created_at} />: <strong>{a.action.replace(/_/g, " ")}</strong> by <span className="mono">{a.actor_id.slice(0, 8)}</span>{" "}
                  <span className="muted wrap">{Object.keys(a.detail ?? {}).length ? JSON.stringify(a.detail) : ""}</span>
                </li>
              ))}
            </ol>
          )}
          <ActionForm
            c={c}
            onDone={() => {
              load.reload();
              onChanged();
            }}
          />
        </article>
      )}
    </Async>
  );
}

export function Cases() {
  const [status, setStatus] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const list = useLoad(() => get<Case[]>(`/cases${status ? `?status=${status}` : ""}`), [status]);
  return (
    <Page title="Security cases" lead="Evidence metadata and action history. Closing a case needs a written rationale.">
      <Field label="Filter by status">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          {["open", "investigating", "resolved", "closed"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </Field>
      <div className="split">
        <Async load={list}>
          {(cases) =>
            cases.length === 0 ? (
              <Empty>No cases.</Empty>
            ) : (
              <ul className="stack" aria-label="Cases">
                {cases.map((c) => (
                  <li key={c.id}>
                    <button type="button" className={`rowbtn${sel === c.id ? " on" : ""}`} aria-pressed={sel === c.id} onClick={() => setSel(c.id)}>
                      <strong>{c.title}</strong>
                      <span className="meta">
                        <StatusTag status={c.severity} /> <StatusTag status={c.status} /> <Ts iso={c.created_at} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          }
        </Async>
        <div>{sel ? <Detail key={sel} id={sel} onChanged={list.reload} /> : <Empty>Select a case to see its detail.</Empty>}</div>
      </div>
    </Page>
  );
}
