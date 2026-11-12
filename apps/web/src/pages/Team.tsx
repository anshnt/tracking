import { get } from "../api/client";
import type { OverviewPerson, Task } from "../api/types";
import { Async, Empty, Page, StatusTag, useLoad } from "../components/ui";

function TaskLines({ title, tasks }: { title: string; tasks: Task[] }) {
  return (
    <div>
      <h4>
        {title} ({tasks.length})
      </h4>
      {tasks.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul className="plain">
          {tasks.map((t) => (
            <li key={t.id}>
              {t.url ? (
                <a href={t.url} target="_blank" rel="noopener noreferrer">
                  {t.title}
                </a>
              ) : (
                t.title
              )}{" "}
              <StatusTag status={t.state} />
              {t.due_date ? ` due ${t.due_date}` : ""}
              {t.blocker ? `, blocker: ${t.blocker}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Team() {
  const load = useLoad(() => get<{ people: OverviewPerson[] }>("/overview"));
  return (
    <Page
      title="Team overview"
      lead="Facts about assignments and reviews, listed alphabetically. There are no scores, percentages or rankings, and activity signals are never used to judge performance."
    >
      <Async load={load}>
        {({ people }) =>
          people.length === 0 ? (
            <Empty>No active direct reports.</Empty>
          ) : (
            <ul className="cards">
              {people.map((p) => (
                <li key={p.employee_id} className="card">
                  <h2>{p.display_name}</h2>
                  <p className="meta">
                    {p.missing_update_for ? (
                      <span className="badge warn">
                        <span aria-hidden="true">? </span>No update for {p.missing_update_for}
                      </span>
                    ) : (
                      <span className="badge ok">
                        <span aria-hidden="true">{"✓"} </span>Update received
                      </span>
                    )}{" "}
                    {p.latest_update ? `Latest update ${p.latest_update.date}.` : "No updates yet."}
                  </p>
                  {p.latest_update?.blocker && <p className="msg err">Latest blocker: {p.latest_update.blocker}</p>}
                  <TaskLines title="Active assignments" tasks={p.assignments} />
                  <TaskLines title="Awaiting review" tasks={p.awaiting_review} />
                  <TaskLines title="Blockers" tasks={p.blockers} />
                  <TaskLines title="Overdue" tasks={p.overdue} />
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
