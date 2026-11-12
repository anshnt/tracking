import { get } from "../api/client";
import type { CollectionPolicy, Records as RecordsT, Workspace } from "../api/types";
import { Async, Empty, Page, PostureBadge, StatusTag, Ts, useLoad, useMe } from "../components/ui";

export function Records() {
  const me = useMe();
  const recs = useLoad(() => get<RecordsT>("/me/records"));
  const pol = useLoad(() => get<CollectionPolicy>("/me/collection-policy"));
  const ws = useLoad(() => get<{ workspaces: Workspace[] }>("/workspaces"));

  return (
    <Page title="My records" lead="Everything the portal holds about you, what is collected, and what restricts your access. Nobody else's data is shown here.">
      <h2>What is collected</h2>
      <Async load={pol}>
        {({ categories }) => (
          <div className="tablewrap">
            <table>
              <caption className="sr">Collection categories</caption>
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
                    <td>{c.default.replace(/_/g, " ")}</td>
                    <td>{c.visible_to}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>

      <h2>Access restrictions affecting you</h2>
      <Async load={ws}>
        {({ workspaces }) => (
          <ul className="plain">
            <li>Account status: <StatusTag status={me.status} /></li>
            {workspaces.map((w) => (
              <li key={w.id}>
                Workspace {w.name}: state {w.lifecycle_state.replace(/_/g, " ")}, data up to {w.classification_ceiling}.
              </li>
            ))}
            {pol.data?.policy?.is_exception && <li>A policy exception applies to you{pol.data.policy.expires_at ? <> until <Ts iso={pol.data.policy.expires_at} /></> : null}.</li>}
            {workspaces.length === 0 && <li>No workspace assigned.</li>}
          </ul>
        )}
      </Async>

      <Async load={recs}>
        {(r) => (
          <>
            <h2>Daily updates</h2>
            {r.work_updates.length === 0 ? (
              <Empty>None yet.</Empty>
            ) : (
              <ul className="plain">
                {r.work_updates.map((u) => (
                  <li key={u.id}>
                    {u.update_date}: {u.summary.slice(0, 120)}
                    {u.summary.length > 120 ? "..." : ""} ({u.corrections} correction(s))
                  </li>
                ))}
              </ul>
            )}

            <h2>Company device checks</h2>
            <p className="meta">Personal devices are never checked. Observed readings can be stale; see the Devices page for the current state.</p>
            {r.posture_observations.length === 0 ? (
              <Empty>No device observations.</Empty>
            ) : (
              <ul className="plain">
                {r.posture_observations.map((o, i) => (
                  <li key={i}>
                    <Ts iso={o.observed_at} /> from {o.source}: <PostureBadge state={o.state} />
                    {o.failing_checks.length > 0 && <> failing {o.failing_checks.map((c) => c.check).join(", ")}</>}
                  </li>
                ))}
              </ul>
            )}

            <h2>Security events about you (summary only)</h2>
            {r.security_event_summaries.length === 0 ? (
              <Empty>None.</Empty>
            ) : (
              <ul className="plain">
                {r.security_event_summaries.map((e) => (
                  <li key={e.id}>
                    <Ts iso={e.occurred_at} />: {e.event_type} from {e.source}, severity {e.severity}, {e.classification}
                  </li>
                ))}
              </ul>
            )}

            <h2>Export requests</h2>
            {r.export_requests.length === 0 ? (
              <Empty>None.</Empty>
            ) : (
              <ul className="plain">
                {r.export_requests.map((x) => (
                  <li key={x.id}>
                    {x.object_ref} to {x.recipient} <StatusTag status={x.status} /> (<Ts iso={x.created_at} />)
                  </li>
                ))}
              </ul>
            )}

            <h2>Notices you acknowledged</h2>
            {r.notice_acknowledgements.length === 0 ? (
              <Empty>None yet.</Empty>
            ) : (
              <ul className="plain">
                {r.notice_acknowledgements.map((a, i) => (
                  <li key={i}>
                    {a.policy} v{a.version}, <Ts iso={a.acknowledged_at} />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Async>
    </Page>
  );
}
