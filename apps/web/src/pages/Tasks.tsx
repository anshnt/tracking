import { get } from "../api/client";
import type { Task } from "../api/types";
import { Async, Empty, Page, StatusTag, Ts, useLoad } from "../components/ui";

export function TaskList({ tasks }: { tasks: Task[] }) {
  return (
    <ul className="stack">
      {tasks.map((t) => (
        <li key={t.id} className="card">
          <h3>{t.url ? <a href={t.url} target="_blank" rel="noopener noreferrer">{t.title}</a> : t.title}</h3>
          <p className="meta">
            <StatusTag status={t.state} /> {t.due_date ? <>Due {t.due_date}. </> : "No due date. "}
            {t.review_requested_at && (
              <>
                Review requested <Ts iso={t.review_requested_at} />.
              </>
            )}
          </p>
          {t.blocker && <p className="msg err">Blocker: {t.blocker}</p>}
          {t.deliverables && t.deliverables.length > 0 && (
            <ul className="plain">
              {t.deliverables.map((d, i) => (
                <li key={i}>
                  Deliverable:{" "}
                  {d.url ? (
                    <a href={d.url} target="_blank" rel="noopener noreferrer">
                      {d.title}
                    </a>
                  ) : (
                    d.title
                  )}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Tasks() {
  const load = useLoad(() => get<{ tasks: Task[] }>("/me/tasks"));
  return (
    <Page title="My tasks and deliverables" lead="Open work assigned to you, from the tracker. This is the primary evidence of progress.">
      <Async load={load}>{({ tasks }) => (tasks.length === 0 ? <Empty>No open tasks assigned to you.</Empty> : <TaskList tasks={tasks} />)}</Async>
    </Page>
  );
}
