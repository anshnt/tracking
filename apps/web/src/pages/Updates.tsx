import { useState } from "react";
import type { FormEvent } from "react";
import { get, post, put } from "../api/client";
import type { Deliverable, WorkUpdate } from "../api/types";
import { Async, Empty, Field, Page, Result, Ts, useAction, useLoad, useMe } from "../components/ui";
import { todayIn } from "../lib/time";

const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function Deliverables({ value, onChange }: { value: Deliverable[]; onChange: (v: Deliverable[]) => void }) {
  const set = (i: number, d: Deliverable) => onChange(value.map((x, j) => (j === i ? d : x)));
  return (
    <fieldset>
      <legend>Deliverables (optional)</legend>
      {value.map((d, i) => (
        <div className="row" key={i}>
          <Field label={`Deliverable ${i + 1} title`}>
            <input value={d.title} maxLength={200} onChange={(e) => set(i, { ...d, title: e.target.value })} />
          </Field>
          <Field label={`Deliverable ${i + 1} link`} hint="http(s) only">
            <input type="url" value={d.url ?? ""} onChange={(e) => set(i, { ...d, url: e.target.value })} />
          </Field>
          <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { title: "", url: "" }])}>
        Add deliverable
      </button>
    </fieldset>
  );
}

const clean = (ds: Deliverable[]) => ds.filter((d) => d.title.trim()).map((d) => ({ title: d.title.trim(), url: d.url?.trim() || null }));

function NewUpdate({ onSaved }: { onSaved: () => void }) {
  const me = useMe();
  const act = useAction();
  const [date, setDate] = useState(todayIn(me.timezone));
  const [summary, setSummary] = useState("");
  const [blocker, setBlocker] = useState("");
  const [refs, setRefs] = useState("");
  const [dels, setDels] = useState<Deliverable[]>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => post("/work-updates", { update_date: date, summary, blocker: blocker.trim() || null, task_refs: csv(refs), deliverables: clean(dels) }),
      "Update saved.",
    );
    if (ok) {
      setSummary("");
      setBlocker("");
      setRefs("");
      setDels([]);
      onSaved();
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h2>Write an update</h2>
      <p className="meta">Your update can cover meetings, research and offline work too. One per day; you can correct it later and the history is kept.</p>
      <Field label="Date" hint={`Your timezone: ${me.timezone}`}>
        <input type="date" required value={date} max={todayIn(me.timezone)} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <Field label="What did you work on?">
        <textarea required rows={4} maxLength={4000} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </Field>
      <Field label="Blocker (optional)">
        <input maxLength={2000} value={blocker} onChange={(e) => setBlocker(e.target.value)} />
      </Field>
      <Field label="Related task references (optional)" hint="Comma separated">
        <input value={refs} onChange={(e) => setRefs(e.target.value)} />
      </Field>
      <Deliverables value={dels} onChange={setDels} />
      <button className="primary" disabled={act.busy}>
        Save update
      </button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function Correct({ u, onSaved }: { u: WorkUpdate; onSaved: () => void }) {
  const act = useAction();
  const [summary, setSummary] = useState(u.summary);
  const [blocker, setBlocker] = useState(u.blocker ?? "");
  const [reason, setReason] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await act.run(
      () => put(`/work-updates/${u.id}`, { summary, blocker: blocker.trim() || null, reason, task_refs: u.task_refs, deliverables: u.deliverables }),
      "Correction saved. The previous text is kept in the history.",
    );
    if (ok) onSaved();
  }
  return (
    <form className="form" onSubmit={submit}>
      <Field label="Corrected summary">
        <textarea required rows={3} maxLength={4000} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </Field>
      <Field label="Blocker">
        <input maxLength={2000} value={blocker} onChange={(e) => setBlocker(e.target.value)} />
      </Field>
      <Field label="Reason for the correction">
        <input required maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <button disabled={act.busy}>Save correction</button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function UpdateRow({ u, onChanged }: { u: WorkUpdate; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const detail = useLoad(() => (open ? get<WorkUpdate>(`/work-updates/${u.id}`) : Promise.resolve(u)), [open, u.updated_at]);
  return (
    <li className="card">
      <h3>{u.update_date}</h3>
      <p className="prose">{u.summary}</p>
      {u.blocker && <p className="msg err">Blocker: {u.blocker}</p>}
      <p className="meta">
        Last saved <Ts iso={u.updated_at} />. {u.correction_count > 0 ? `${u.correction_count} correction(s).` : "No corrections."}
      </p>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide history and correction" : "Corrections"}
      </button>
      {open && (
        <Async load={detail}>
          {(d) => (
            <div>
              {d.corrections && d.corrections.length > 0 ? (
                <ol className="plain">
                  {d.corrections.map((c) => (
                    <li key={c.id}>
                      <Ts iso={c.created_at} />: {c.reason}
                      <blockquote>{c.previous.summary}</blockquote>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="muted">No earlier versions.</p>
              )}
              <Correct u={d} onSaved={onChanged} />
            </div>
          )}
        </Async>
      )}
    </li>
  );
}

export function Updates() {
  const list = useLoad(() => get<{ work_updates: WorkUpdate[] }>("/work-updates"));
  return (
    <Page title="Daily update">
      <NewUpdate onSaved={list.reload} />
      <h2>History</h2>
      <Async load={list}>
        {({ work_updates }) =>
          work_updates.length === 0 ? (
            <Empty>You have not written an update yet.</Empty>
          ) : (
            <ul className="stack">
              {work_updates.map((u) => (
                <UpdateRow key={u.id} u={u} onChanged={list.reload} />
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
