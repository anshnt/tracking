import { get } from "../api/client";
import type { CollectionPolicy, Records as RecordsT, Workspace } from "../api/types";
import { Async, DataTable, EmptyState, Page, PostureBadge, Section, StatStrip, StatusPill, StatusTag, Ts, useLoad, useMe } from "../components/ui";
import "../styles/employee.css";

const DEFAULTS: Record<string, string> = { on: "On", off: "Off", excluded: "Excluded", optional: "Optional", company_devices_only: "Company devices only" };
export const collectionDefault = (d: string) => DEFAULTS[d] ?? d.replace(/_/g, " ");

const trim = (s: string) => (s.length > 120 ? `${s.slice(0, 120)}...` : s);

export function Records() {
  const me = useMe();
  const recs = useLoad(() => get<RecordsT>("/me/records"));
  const pol = useLoad(() => get<CollectionPolicy>("/me/collection-policy"));
  const ws = useLoad(() => get<{ workspaces: Workspace[] }>("/workspaces"));

  return (
    <Page title="My records" lead="Everything the portal holds about you, what is collected, and what restricts your access. Nobody else's data is shown here.">
      <div className="e-stack">
        <StatStrip
          label="What the portal holds"
          headline={recs.data ? `${recs.data.work_updates.length} daily updates, ${recs.data.security_event_summaries.length} security events, ${recs.data.export_requests.length} export requests.` : undefined}
          items={[
            { label: "Signals collected", value: pol.data ? pol.data.categories.length : "-" },
            { label: "Daily updates", value: recs.data ? recs.data.work_updates.length : "-" },
            { label: "Device readings", value: recs.data ? recs.data.posture_observations.length : "-" },
            { label: "Security events", value: recs.data ? recs.data.security_event_summaries.length : "-" },
            { label: "Export requests", value: recs.data ? recs.data.export_requests.length : "-" },
          ]}
        />
        <Section title="What is collected" hint="Signals the monitoring notice lists, and who can see each one.">
          <Async load={pol} isEmpty={(d) => d.categories.length === 0} empty={<EmptyState title="No collection categories">No notice applies to you yet, so nothing is listed.</EmptyState>}>
            {({ categories }) => (
              <DataTable label="Collection categories">
                <thead>
                  <tr>
                    <th scope="col">Signal</th>
                    <th scope="col">Default</th>
                    <th scope="col">Who can see it</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((c) => (
                    <tr key={c.signal}>
                      <th scope="row">{c.signal}</th>
                      <td>
                        <StatusPill tone="muted" glyph={false}>
                          {collectionDefault(c.default)}
                        </StatusPill>
                      </td>
                      <td>{c.visible_to}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Access restrictions affecting you">
          <Async load={ws} skeleton="rows" rows={2}>
            {({ workspaces }) => (
              <DataTable label="Access restrictions">
                <thead>
                  <tr>
                    <th scope="col">Applies to</th>
                    <th scope="col">State</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Your account</th>
                    <td>
                      <StatusTag status={me.status} />
                    </td>
                    <td className="meta">Account status</td>
                  </tr>
                  {workspaces.map((w) => (
                    <tr key={w.id}>
                      <th scope="row">Workspace {w.name}</th>
                      <td>
                        <StatusTag status={w.lifecycle_state} />
                      </td>
                      <td>Data up to {w.classification_ceiling}</td>
                    </tr>
                  ))}
                  {workspaces.length === 0 && (
                    <tr>
                      <th scope="row">Workspaces</th>
                      <td colSpan={2} className="meta">
                        No workspace assigned.
                      </td>
                    </tr>
                  )}
                  {pol.data?.policy?.is_exception && (
                    <tr>
                      <th scope="row">Policy</th>
                      <td>
                        <StatusPill tone="warn">Exception</StatusPill>
                      </td>
                      <td>
                        A policy exception applies to you
                        {pol.data.policy.expires_at ? (
                          <>
                            {" "}
                            until <Ts iso={pol.data.policy.expires_at} />
                          </>
                        ) : null}
                        .
                      </td>
                    </tr>
                  )}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Daily updates" hint="Your last updates, with how often each was corrected.">
          <Async load={recs} isEmpty={(r) => r.work_updates.length === 0} empty={<EmptyState title="No daily updates yet">Updates you write on the Daily update page are listed here.</EmptyState>}>
            {(r) => (
              <DataTable label="Daily updates">
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Summary</th>
                    <th scope="col" className="num">
                      Corrections
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {r.work_updates.map((u) => (
                    <tr key={u.id}>
                      <th scope="row" className="mono">
                        {u.update_date}
                      </th>
                      <td>{trim(u.summary)}</td>
                      <td className="num">{u.corrections}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Company device checks" hint="Personal devices are never checked. Observed readings can be stale; see the Devices page for the current state.">
          <Async load={recs} isEmpty={(r) => r.posture_observations.length === 0} empty={<EmptyState title="No device observations">Readings from company devices appear here when an agent reports one.</EmptyState>}>
            {(r) => (
              <DataTable label="Device checks">
                <thead>
                  <tr>
                    <th scope="col">Observed</th>
                    <th scope="col">Source</th>
                    <th scope="col">State</th>
                    <th scope="col">Failing checks</th>
                  </tr>
                </thead>
                <tbody>
                  {r.posture_observations.map((o, i) => (
                    <tr key={i}>
                      <th scope="row">
                        <Ts iso={o.observed_at} />
                      </th>
                      <td>{o.source}</td>
                      <td>
                        <PostureBadge state={o.state} />
                      </td>
                      <td>{o.failing_checks.length > 0 ? o.failing_checks.map((c) => c.check).join(", ") : <span className="meta">None</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Security events about you" hint="Summary only.">
          <Async load={recs} isEmpty={(r) => r.security_event_summaries.length === 0} empty={<EmptyState title="No security events">Nothing has been recorded about you.</EmptyState>}>
            {(r) => (
              <DataTable label="Security events">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Event</th>
                    <th scope="col">Source</th>
                    <th scope="col">Severity</th>
                    <th scope="col">Classification</th>
                  </tr>
                </thead>
                <tbody>
                  {r.security_event_summaries.map((e) => (
                    <tr key={e.id}>
                      <th scope="row">
                        <Ts iso={e.occurred_at} />
                      </th>
                      <td>{e.event_type}</td>
                      <td>{e.source}</td>
                      <td>
                        <StatusTag status={e.severity} />
                      </td>
                      <td>{e.classification}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Export requests">
          <Async load={recs} isEmpty={(r) => r.export_requests.length === 0} empty={<EmptyState title="No export requests">Requests you make on the My exports page are listed here.</EmptyState>}>
            {(r) => (
              <DataTable label="Export requests">
                <thead>
                  <tr>
                    <th scope="col">Object</th>
                    <th scope="col">Recipient</th>
                    <th scope="col">Status</th>
                    <th scope="col">Requested</th>
                  </tr>
                </thead>
                <tbody>
                  {r.export_requests.map((x) => (
                    <tr key={x.id}>
                      <th scope="row" className="mono">
                        {x.object_ref}
                      </th>
                      <td>{x.recipient}</td>
                      <td>
                        <StatusTag status={x.status} />
                      </td>
                      <td>
                        <Ts iso={x.created_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>

        <Section title="Notices you acknowledged">
          <Async load={recs} isEmpty={(r) => r.notice_acknowledgements.length === 0} empty={<EmptyState title="No acknowledgements yet">Acknowledge the notice on the Home page and it is recorded here.</EmptyState>}>
            {(r) => (
              <DataTable label="Acknowledged notices">
                <thead>
                  <tr>
                    <th scope="col">Notice</th>
                    <th scope="col" className="num">
                      Version
                    </th>
                    <th scope="col">Acknowledged</th>
                  </tr>
                </thead>
                <tbody>
                  {r.notice_acknowledgements.map((a, i) => (
                    <tr key={i}>
                      <th scope="row">{a.policy}</th>
                      <td className="num">v{a.version}</td>
                      <td>
                        <Ts iso={a.acknowledged_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Async>
        </Section>
      </div>
    </Page>
  );
}
