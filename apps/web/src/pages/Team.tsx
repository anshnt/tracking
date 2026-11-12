import "../styles/team-security.css";
import { get } from "../api/client";
import type { OverviewPerson, Task } from "../api/types";
import { Async, Page, Panel, StatStrip, StatusPill, StatusTag, useLoad } from "../components/ui";
import { count, headline } from "../lib/text";

function TaskLines({ title, tasks }: { title: string; tasks: Task[] }) {
  return (
    <section>
      <h3>
        {title} <span className="num">{tasks.length}</span>
      </h3>
      {tasks.length === 0 ? (
        <p className="none">None</p>
      ) : (
        <ul>
          {tasks.map((t) => (
            <li key={t.id}>
              {t.url ? (
                <a href={t.url} target="_blank" rel="noopener noreferrer">
                  {t.title}
                </a>
              ) : (
                <span>{t.title}</span>
              )}
              <span className="fact-meta">
                <StatusTag status={t.state} />
                {t.due_date && (
                  <span>
                    due <span className="mono">{t.due_date}</span>
                  </span>
                )}
                {t.blocker && <span>blocker: {t.blocker}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Team() {
  const load = useLoad(() => get<{ people: OverviewPerson[] }>("/overview"));
  return (
    <Page
      title="Team overview"
      lead="Facts about assignments and reviews, listed alphabetically. There are no scores, percentages or rankings, and activity signals are never used to judge performance."
    >
      <Async
        load={load}
        skeleton="block"
        isEmpty={(d) => d.people.length === 0}
        empty={<p className="state-body">No active direct reports. People who report to you appear here once they are assigned to you.</p>}
      >
        {({ people }) => {
          const sum = (pick: (p: OverviewPerson) => unknown[]) => people.reduce((n, p) => n + pick(p).length, 0);
          const blockers = sum((p) => p.blockers);
          const overdue = sum((p) => p.overdue);
          const review = sum((p) => p.awaiting_review);
          const missing = people.filter((p) => p.missing_update_for).length;
          return (
          <>
          <StatStrip
            label="Team summary"
            headline={headline(
              [blockers > 0 && count(blockers, "blocker"), overdue > 0 && count(overdue, "overdue task"), review > 0 && `${review} awaiting review`, missing > 0 && `${count(missing, "missing update")}`],
              "Nothing is blocked, overdue or waiting for review.",
            )}
            items={[
              { label: "Direct reports", value: people.length },
              { label: "Blockers", value: blockers, tone: "bad" },
              { label: "Overdue", value: overdue, tone: "bad" },
              { label: "Awaiting review", value: review },
              { label: "Missing updates", value: missing, tone: "warn" },
            ]}
          />
          <ul className="people" aria-label="Direct reports">
            {people.map((p) => (
              <li key={p.employee_id}>
                <Panel
                  title={p.display_name}
                  hint={p.latest_update ? `Latest update ${p.latest_update.date}` : "No updates yet"}
                  actions={
                    p.missing_update_for ? (
                      <StatusPill tone="warn">No update for {p.missing_update_for}</StatusPill>
                    ) : (
                      <StatusPill tone="ok">Update received</StatusPill>
                    )
                  }
                >
                  {p.latest_update?.blocker && <p className="person-blocker">Latest blocker: {p.latest_update.blocker}</p>}
                  <div className="facts">
                    <TaskLines title="Active assignments" tasks={p.assignments} />
                    <TaskLines title="Awaiting review" tasks={p.awaiting_review} />
                    <TaskLines title="Blockers" tasks={p.blockers} />
                    <TaskLines title="Overdue" tasks={p.overdue} />
                  </div>
                </Panel>
              </li>
            ))}
          </ul>
          </>
          );
        }}
      </Async>
    </Page>
  );
}
