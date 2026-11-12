import { useState } from "react";
import { get, post } from "../api/client";
import type { Connector, FailedJob } from "../api/types";
import { ageText } from "../lib/time";
import { Async, Button, DataTable, EmptyState, Field, Page, Result, Section, StatusPill, Ts, useAction, useLoad } from "../components/ui";
import "../styles/ops-admin.css";

function ConnectorState({ c }: { c: Connector }) {
  if (!c.enabled) return <StatusPill tone="muted">Disabled</StatusPill>;
  if (c.stale) return <StatusPill tone="bad">Stale</StatusPill>;
  if (c.polled) return <StatusPill tone="ok">Fresh</StatusPill>;
  return <StatusPill tone="muted" glyph={false}>On demand</StatusPill>;
}

function JobRow({ j, onDone }: { j: FailedJob; onDone: () => void }) {
  const act = useAction();
  const [note, setNote] = useState("");
  const operatorTask = j.kind === "operator.task";
  return (
    <tr>
      <th scope="row">{operatorTask ? "Operator task waiting for a person" : <span className="mono">{j.kind}</span>}</th>
      <td className="num">
        {j.attempts}/{j.max_attempts}
      </td>
      <td>
        <Ts iso={j.finished_at} />
      </td>
      <td className="ops-wrap">{j.last_error ?? "None recorded"}</td>
      <td>
        {operatorTask ? (
          <form
            className="ops-step-form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (await act.run(() => post(`/operations/operator-tasks/${j.id}/confirm`, { note }), "Confirmed.")) onDone();
            }}
          >
            <Field label="What was done" hint="Required. Recorded in the audit log.">
              <input required maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Button type="submit" disabled={act.busy}>Confirm it was done</Button>
            <Result ok={act.ok} err={act.err} />
          </form>
        ) : (
          <div className="ops-actions">
            <Button disabled={act.busy} onClick={async () => (await act.run(() => post(`/operations/jobs/${j.id}/retry`), "Queued for retry.")) && onDone()}>
              Retry
            </Button>
            <Result ok={act.ok} err={act.err} />
          </div>
        )}
      </td>
    </tr>
  );
}

export function Connectors() {
  const conns = useLoad(() => get<Connector[]>("/operations/connectors"));
  const failed = useLoad(() => get<FailedJob[]>("/operations/jobs/failed"));
  return (
    <Page title="Connector health" lead="A successful poll is not proof that collection is complete. Stale and failing sources are flagged, never hidden.">
      <Section title="Connectors" hint="Each source with its last success and how old its cursor is.">
        <Async
          load={conns}
          rows={4}
          isEmpty={(rows) => rows.length === 0}
          empty={<EmptyState title="No connectors configured">Connectors appear here once a source is enabled in the API configuration.</EmptyState>}
        >
          {(rows) => (
            <DataTable label="Connector health">
              <thead>
                <tr>
                  <th scope="col">Connector</th>
                  <th scope="col">Enabled</th>
                  <th scope="col">State</th>
                  <th scope="col">Last success</th>
                  <th scope="col">Cursor age</th>
                  <th scope="col">Last attempt</th>
                  <th scope="col">Last error</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.name}>
                    <th scope="row">{c.name}</th>
                    <td>{c.enabled ? "Yes" : "No"}</td>
                    <td>
                      <ConnectorState c={c} />
                    </td>
                    <td>
                      <Ts iso={c.last_success_at} />
                    </td>
                    <td>{ageText(c.cursor_age_seconds)}</td>
                    <td>
                      <Ts iso={c.last_attempt_at} />
                    </td>
                    <td className="ops-wrap">{c.last_error ?? "None"}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Async>
      </Section>
      <Section title="Failed jobs" hint="Retry a job, or confirm an operator task once a person has done it.">
        <Async
          load={failed}
          rows={3}
          isEmpty={(jobs) => jobs.length === 0}
          empty={<EmptyState title="No failed jobs">Jobs that exhaust their attempts show up here with a retry.</EmptyState>}
        >
          {(jobs) => (
            <DataTable label="Failed jobs">
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col" className="num">Attempts</th>
                  <th scope="col">Failed</th>
                  <th scope="col">Last error</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <JobRow key={j.id} j={j} onDone={failed.reload} />
                ))}
              </tbody>
            </DataTable>
          )}
        </Async>
      </Section>
    </Page>
  );
}
