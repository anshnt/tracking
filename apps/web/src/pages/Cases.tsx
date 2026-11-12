import "../styles/team-security.css";
import { useState } from "react";
import type { FormEvent } from "react";
import { get, post } from "../api/client";
import { SEVERITIES } from "../api/types";
import type { Case } from "../api/types";
import { Async, Button, EmptyState, Field, IdCell, KeyValue, Page, Panel, Result, Section, StatStrip, StatusTag, Toolbar, Ts, useAction, useLoad, useMe } from "../components/ui";
import { count, headline } from "../lib/text";

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
      <fieldset className="catalogue">
        <legend>Action</legend>
        {ACTIONS.map(([v, l]) => (
          <label key={v} className="check">
            <input type="radio" name="case-action" value={v} checked={kind === v} onChange={() => setKind(v)} />
            {l}
          </label>
        ))}
      </fieldset>
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
      <Button type="submit" variant="primary" disabled={act.busy}>
        Record action
      </Button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const load = useLoad(() => get<Case>(`/cases/${id}`), [id]);
  return (
    <Async load={load} skeleton="block">
      {(c) => (
        <Panel
          title={c.title}
          hint={
            <>
              Opened <Ts iso={c.created_at} />, updated <Ts iso={c.updated_at} />
            </>
          }
          actions={
            <>
              <StatusTag status={c.severity} />
              <StatusTag status={c.status} />
            </>
          }
        >
          <p className="prose">{c.reason}</p>
          <KeyValue
            items={[
              { label: "Owner", value: c.owner_id ? <IdCell id={c.owner_id} /> : "unassigned" },
              { label: "Subject", value: c.subject_employee_id ? <IdCell id={c.subject_employee_id} /> : "not linked" },
              { label: "Source", value: c.source ?? "none" },
              ...(c.closure_rationale ? [{ label: "Closure rationale", value: c.closure_rationale }] : []),
            ]}
          />
          <div className="case-sub case-detail">
            <h3>Evidence</h3>
            {!c.events || c.events.length === 0 ? (
              <p className="state-body">No linked events. Use "Link a security event" below to attach evidence.</p>
            ) : (
              <ol className="timeline">
                {c.events.map((e) => (
                  <li key={e.id}>
                    <span className="when">
                      <Ts iso={e.occurred_at} />
                    </span>
                    <span>
                      <StatusTag status={e.severity} /> {e.source}: {e.event_type}
                      {e.resource ? ` on ${e.resource}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="case-sub case-detail">
            <h3>Action history</h3>
            {!c.actions || c.actions.length === 0 ? (
              <p className="state-body">No actions yet. Record the first one below.</p>
            ) : (
              <ol className="timeline">
                {c.actions.map((a) => (
                  <li key={a.id}>
                    <span className="when">
                      <Ts iso={a.created_at} />
                    </span>
                    <span>
                      <strong>{a.action.replace(/_/g, " ")}</strong> by <span className="mono">{a.actor_id.slice(0, 8)}</span>{" "}
                      <span className="muted wrap">{Object.keys(a.detail ?? {}).length ? JSON.stringify(a.detail) : ""}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="case-sub case-detail">
            <h3>Add an action</h3>
            <ActionForm
              c={c}
              onDone={() => {
                load.reload();
                onChanged();
              }}
            />
          </div>
        </Panel>
      )}
    </Async>
  );
}

const STATUSES = ["open", "investigating", "resolved", "closed"];

export function Cases() {
  const [status, setStatus] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const list = useLoad(() => get<Case[]>(`/cases${status ? `?status=${status}` : ""}`), [status]);
  // The summary always counts every case, whatever the filter below is showing.
  const all = useLoad(() => get<Case[]>("/cases"));
  const cases = all.data;
  const n = (s: string) => (cases ? cases.filter((c) => c.status === s).length : 0);
  const urgent = cases ? cases.filter((c) => c.status !== "closed" && c.status !== "resolved" && (c.severity === "high" || c.severity === "critical")).length : 0;
  const reload = () => {
    list.reload();
    all.reload();
  };
  const none = cases !== null && cases.length === 0;
  return (
    <Page title="Security cases" lead="Evidence metadata and action history. Closing a case needs a written rationale.">
      {cases && cases.length > 0 && (
        <StatStrip
          label="Case summary"
          headline={headline([n("open") > 0 && `${n("open")} open`, n("investigating") > 0 && `${n("investigating")} investigating`, urgent > 0 && `${urgent} high or critical`], "No case is open.")}
          items={[
            { label: "Open", value: n("open"), tone: "warn" },
            { label: "Investigating", value: n("investigating") },
            { label: "High or critical, not resolved", value: urgent, tone: "bad" },
            { label: "Resolved", value: n("resolved") },
            { label: "Closed", value: n("closed") },
          ]}
        />
      )}
      {none ? (
        <EmptyState
          title="No security cases"
          action={
            <Button variant="primary" onClick={reload}>
              Check again
            </Button>
          }
        >
          A case is opened when a security event is escalated. Nothing has been escalated yet, so there is nothing to review.
        </EmptyState>
      ) : (
        <>
          <Toolbar label="Case filters">
            <Field label="Status">
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All statuses</option>
                {STATUSES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
          </Toolbar>
          <div className="split">
            <Section title="Cases" hint={list.data ? count(list.data.length, "case") + (status ? ` with status ${status}` : "") : undefined}>
              <Async
                load={list}
                isEmpty={(cs) => cs.length === 0}
                empty={
                  <EmptyState
                    title={status ? `No ${status} cases` : "No cases"}
                    action={
                      status ? (
                        <Button onClick={() => setStatus("")}>Show all cases</Button>
                      ) : undefined
                    }
                  >
                    {status ? "No case has this status right now." : "A case appears here when a security event is escalated."}
                  </EmptyState>
                }
              >
                {(cs) => (
                  <ul className="case-list" aria-label="Cases">
                    {cs.map((c) => (
                      <li key={c.id}>
                        <button type="button" className={`rowbtn${sel === c.id ? " on" : ""}`} aria-pressed={sel === c.id} onClick={() => setSel(c.id)}>
                          <strong>{c.title}</strong>
                          <span className="fact-meta">
                            <StatusTag status={c.severity} /> <StatusTag status={c.status} /> <Ts iso={c.created_at} />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Async>
            </Section>
            <div>
              {sel ? (
                <Detail key={sel} id={sel} onChanged={reload} />
              ) : (
                list.data &&
                list.data.length > 0 && <EmptyState title="Select a case">Its evidence, action history and the form to record an action appear here.</EmptyState>
              )}
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
