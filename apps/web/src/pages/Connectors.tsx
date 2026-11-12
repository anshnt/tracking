import { useState } from "react";
import { get, post } from "../api/client";
import type { Connector, FailedJob } from "../api/types";
import { ageText } from "../lib/time";
import { Async, Empty, Field, Page, Result, Tag, Ts, useAction, useLoad } from "../components/ui";

function JobRow({ j, onDone }: { j: FailedJob; onDone: () => void }) {
  const act = useAction();
  const [note, setNote] = useState("");
  const operatorTask = j.kind === "operator.task";
  return (
    <li className="card">
      <h3>{operatorTask ? "Operator task waiting for a person" : j.kind}</h3>
      <p className="meta">
        Attempts {j.attempts}/{j.max_attempts}. Failed <Ts iso={j.finished_at} />
      </p>
      {j.last_error && <p className="msg err wrap">{j.last_error}</p>}
      {operatorTask ? (
        <form
          className="form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await act.run(() => post(`/operations/operator-tasks/${j.id}/confirm`, { note }), "Confirmed.")) onDone();
          }}
        >
          <Field label="What was done" hint="Required. Recorded in the audit log.">
            <input required maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <button disabled={act.busy}>Confirm it was done</button>
          <Result ok={act.ok} err={act.err} />
        </form>
      ) : (
        <>
          <button type="button" disabled={act.busy} onClick={async () => (await act.run(() => post(`/operations/jobs/${j.id}/retry`), "Queued for retry.")) && onDone()}>
            Retry
          </button>
          <Result ok={act.ok} err={act.err} />
        </>
      )}
    </li>
  );
}

export function Connectors() {
  const conns = useLoad(() => get<Connector[]>("/operations/connectors"));
  const failed = useLoad(() => get<FailedJob[]>("/operations/jobs/failed"));
  return (
    <Page title="Connector health" lead="A successful poll is not proof that collection is complete. Stale and failing sources are flagged, never hidden.">
      <Async load={conns}>
        {(rows) => (
          <div className="tablewrap">
            <table>
              <caption className="sr">Connectors</caption>
              <thead>
                <tr>
                  <th scope="col">Connector</th>
                  <th scope="col">State</th>
                  <th scope="col">Last success</th>
                  <th scope="col">Last attempt</th>
                  <th scope="col">Last error</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.name}>
                    <th scope="row">{c.name}</th>
                    <td>
                      {!c.enabled ? (
                        <Tag tone="muted" mark="-">
                          Disabled
                        </Tag>
                      ) : c.stale ? (
                        <Tag tone="bad" mark="!">
                          Stale
                        </Tag>
                      ) : c.polled ? (
                        <Tag tone="ok" mark={"✓"}>
                          Fresh
                        </Tag>
                      ) : (
                        <Tag tone="muted">On demand</Tag>
                      )}
                    </td>
                    <td>
                      <Ts iso={c.last_success_at} />
                      <br />
                      <small className="muted">{ageText(c.cursor_age_seconds)}</small>
                    </td>
                    <td>
                      <Ts iso={c.last_attempt_at} />
                    </td>
                    <td className="wrap">{c.last_error ?? "None"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
      <h2>Failed jobs</h2>
      <Async load={failed}>
        {(jobs) =>
          jobs.length === 0 ? (
            <Empty>No failed jobs.</Empty>
          ) : (
            <ul className="stack">
              {jobs.map((j) => (
                <JobRow key={j.id} j={j} onDone={failed.reload} />
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
