import { get } from "../api/client";
import type { Task } from "../api/types";
import { Link } from "react-router-dom";
import { Async, DataTable, EmptyState, Page, StatStrip, StatusTag, Ts, useLoad } from "../components/ui";
import { count, headline } from "../lib/text";
import "../styles/employee.css";

export function TaskList({ tasks }: { tasks: Task[] }) {
  return (
    <DataTable label="My tasks">
      <thead>
        <tr>
          <th scope="col">Task</th>
          <th scope="col">State</th>
          <th scope="col">Due</th>
          <th scope="col">Deliverables</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((t) => (
          <tr key={t.id}>
            <th scope="row">
              {t.url ? (
                <a href={t.url} target="_blank" rel="noopener noreferrer">
                  {t.title}
                </a>
              ) : (
                t.title
              )}
              {t.blocker && <p className="e-blocker">Blocker: {t.blocker}</p>}
            </th>
            <td>
              <StatusTag status={t.state} />
              {t.review_requested_at && (
                <p className="e-sub">
                  Review requested <Ts iso={t.review_requested_at} />
                </p>
              )}
            </td>
            <td className="mono">{t.due_date ?? "No due date"}</td>
            <td>
              {t.deliverables && t.deliverables.length > 0 ? (
                <div className="e-deliv">
                  {t.deliverables.map((d, i) =>
                    d.url ? (
                      <a key={i} href={d.url} target="_blank" rel="noopener noreferrer">
                        {d.title}
                      </a>
                    ) : (
                      <span key={i}>{d.title}</span>
                    ),
                  )}
                </div>
              ) : (
                <span className="meta">None</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

export function Tasks() {
  const load = useLoad(() => get<{ tasks: Task[] }>("/me/tasks"));
  return (
    <Page title="My tasks and deliverables" lead="Open work assigned to you, from the tracker. This is the primary evidence of progress.">
      <Async
        load={load}
        isEmpty={(d) => d.tasks.length === 0}
        empty={
          <EmptyState
            title="No open tasks"
            action={
              <Link className="btn btn-primary" to="/updates">
                Write today's update
              </Link>
            }
          >
            Tasks assigned to you in the tracker show up here with their deliverables. Until then, your daily update is the record of what you did.
          </EmptyState>
        }
      >
        {({ tasks }) => {
          const today = new Date().toISOString().slice(0, 10);
          const blocked = tasks.filter((t) => t.blocker).length;
          const overdue = tasks.filter((t) => t.due_date && t.due_date < today).length;
          const review = tasks.filter((t) => t.state === "in_review").length;
          return (
            <>
              <StatStrip
                label="Task summary"
                headline={headline([blocked > 0 && count(blocked, "blocker"), overdue > 0 && `${count(overdue, "task")} overdue`, review > 0 && `${review} in review`], `${count(tasks.length, "open task")}, none blocked or overdue`)}
                items={[
                  { label: "Open", value: tasks.length },
                  { label: "In review", value: review },
                  { label: "Blocked", value: blocked, tone: "bad" },
                  { label: "Overdue", value: overdue, tone: "bad" },
                ]}
              />
              <TaskList tasks={tasks} />
            </>
          );
        }}
      </Async>
    </Page>
  );
}
