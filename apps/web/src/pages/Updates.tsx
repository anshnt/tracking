import { useState } from "react";
import type { FormEvent } from "react";
import { get, post, put } from "../api/client";
import type { Deliverable, WorkUpdate } from "../api/types";
import { Async, Button, EmptyState, Field, Page, Panel, Result, Section, Ts, useAction, useLoad, useMe } from "../components/ui";
import { todayIn } from "../lib/time";
import "../styles/employee.css";

const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function Deliverables({ value, onChange }: { value: Deliverable[]; onChange: (v: Deliverable[]) => void }) {
  const set = (i: number, d: Deliverable) => onChange(value.map((x, j) => (j === i ? d : x)));
  return (
    <fieldset className="e-fieldset">
      <legend>Deliverables (optional)</legend>
      {value.map((d, i) => (
        <div className="e-del" key={i}>
          <Field label={`Deliverable ${i + 1} title`}>
            <input value={d.title} maxLength={200} onChange={(e) => set(i, { ...d, title: e.target.value })} />
          </Field>
          <Field label={`Deliverable ${i + 1} link`} hint="http(s) only">
            <input type="url" value={d.url ?? ""} onChange={(e) => set(i, { ...d, url: e.target.value })} />
          </Field>
          <Button variant="quiet" onClick={() => onChange(value.filter((_, j) => j !== i))}>
            Remove
          </Button>
        </div>
      ))}
      <Button onClick={() => onChange([...value, { title: "", url: "" }])}>Add deliverable</Button>
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
    <Panel title="Write an update" hint="Your update can cover meetings, research and offline work too. One per day; you can correct it later and the history is kept.">
    <form className="form" onSubmit={submit}>
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
      <Button type="submit" variant="primary" disabled={act.busy}>
        Save update
      </Button>
      <Result ok={act.ok} err={act.err} />
    </form>
    </Panel>
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
      <Button type="submit" variant="primary" disabled={act.busy}>
        Save correction
      </Button>
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function UpdateRow({ u, onChanged }: { u: WorkUpdate; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const detail = useLoad(() => (open ? get<WorkUpdate>(`/work-updates/${u.id}`) : Promise.resolve(u)), [open, u.updated_at]);
  return (
    <li>
      <div className="e-head">
        <h3 className="mono">{u.update_date}</h3>
        <Button variant="quiet" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide history and correction" : "Corrections"}
        </Button>
      </div>
      <p className="e-body">{u.summary}</p>
      {u.blocker && <p className="e-blocker">Blocker: {u.blocker}</p>}
      <p className="e-sub">
        Last saved <Ts iso={u.updated_at} />. {u.correction_count > 0 ? `${u.correction_count} correction(s).` : "No corrections."}
      </p>
      {open && (
        <div className="e-fine">
          <Async load={detail} skeleton="lines" rows={3}>
            {(d) => (
              <>
                {d.corrections && d.corrections.length > 0 ? (
                  <ol>
                    {d.corrections.map((c) => (
                      <li key={c.id}>
                        <Ts iso={c.created_at} />: {c.reason}
                        <blockquote>{c.previous.summary}</blockquote>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="e-sub">No earlier versions.</p>
                )}
                <Correct u={d} onSaved={onChanged} />
              </>
            )}
          </Async>
        </div>
      )}
    </li>
  );
}

export function Updates() {
  const list = useLoad(() => get<{ work_updates: WorkUpdate[] }>("/work-updates"));
  return (
    <Page title="Daily update" lead="One short note a day. Corrections keep the earlier text.">
      <div className="e-two">
        <NewUpdate onSaved={list.reload} />
        <Section title="History">
          <Async
            load={list}
            isEmpty={(d) => d.work_updates.length === 0}
            empty={<EmptyState title="No updates yet">Write your first one with the form. It will appear here with its correction history.</EmptyState>}
          >
            {({ work_updates }) => (
              <ul className="e-rows">
                {work_updates.map((u) => (
                  <UpdateRow key={u.id} u={u} onChanged={list.reload} />
                ))}
              </ul>
            )}
          </Async>
        </Section>
      </div>
    </Page>
  );
}
