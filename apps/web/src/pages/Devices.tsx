import { get } from "../api/client";
import type { Device, OverviewPerson, Posture, Workspace } from "../api/types";
import { hasRole } from "../lib/nav";
import { postureReason } from "../lib/posture";
import { Async, Empty, Page, PostureBadge, StatusTag, Ts, useLoad, useMe } from "../components/ui";

function DeviceRow({ d }: { d: Device }) {
  const load = useLoad(() => get<Posture>(`/devices/${d.id}/posture`));
  return (
    <tr>
      <th scope="row">{d.name}</th>
      <td>
        {d.ownership}
        {d.os ? `, ${d.os}` : ""}
      </td>
      {load.error && (
        <td colSpan={3} className="msg err" role="alert">
          {load.error}
        </td>
      )}
      {!load.data && !load.error && (
        <td colSpan={3} className="muted">
          Loading...
        </td>
      )}
      {load.data && (
        <>
          <td>
            <PostureBadge state={load.data.state} />
            <br />
            <small className="muted">{postureReason(load.data.reason)}</small>
          </td>
          <td>{load.data.observed_at ? <Ts iso={load.data.observed_at} /> : "never observed"}</td>
          <td>
            {load.data.failing_checks.length === 0
              ? "None"
              : load.data.failing_checks.map((c) => (c.detail ? `${c.check} (${c.detail})` : c.check)).join(", ")}
          </td>
        </>
      )}
    </tr>
  );
}

function TeamWorkspaces({ person }: { person: OverviewPerson }) {
  const load = useLoad(() => get<{ workspaces: Workspace[] }>(`/workspaces?employee_id=${person.employee_id}`));
  return (
    <li className="card">
      <h3>{person.display_name}</h3>
      <Async load={load}>
        {({ workspaces }) =>
          workspaces.length === 0 ? (
            <p className="muted">No workspace.</p>
          ) : (
            <ul className="plain">
              {workspaces.map((w) => (
                <li key={w.id}>
                  {w.name} ({w.role_profile}), up to {w.classification_ceiling} <StatusTag status={w.lifecycle_state} />
                  <br />
                  <PostureBadge state={w.posture.state} /> <small className="muted">{postureReason(w.posture.reason)}</small>
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </li>
  );
}

export function Devices() {
  const me = useMe();
  const devices = useLoad(() => get<{ devices: Device[] }>("/devices"));
  const team = hasRole(me.roles, "manager");
  const people = useLoad(() => (team ? get<{ people: OverviewPerson[] }>("/overview") : Promise.resolve({ people: [] })));
  const wide = hasRole(me.roles, "it", "security");

  return (
    <Page
      title="Devices and workspaces"
      lead="Stale or missing evidence is shown as unknown, never as compliant. Personal devices are not applicable: nothing is collected from them."
    >
      <h2>{wide ? "All devices" : "My devices"}</h2>
      <Async load={devices}>
        {({ devices: list }) =>
          list.length === 0 ? (
            <Empty>No devices.</Empty>
          ) : (
            <div className="tablewrap">
              <table>
                <caption className="sr">Device posture</caption>
                <thead>
                  <tr>
                    <th scope="col">Device</th>
                    <th scope="col">Type</th>
                    <th scope="col">State</th>
                    <th scope="col">Last observed</th>
                    <th scope="col">Failing checks</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((d) => (
                    <DeviceRow key={d.id} d={d} />
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Async>

      {team && (
        <>
          <h2>Workspaces of my team</h2>
          <Async load={people}>
            {({ people: ps }) =>
              ps.length === 0 ? (
                <Empty>No direct reports.</Empty>
              ) : (
                <ul className="cards">
                  {ps.map((p) => (
                    <TeamWorkspaces key={p.employee_id} person={p} />
                  ))}
                </ul>
              )
            }
          </Async>
        </>
      )}
    </Page>
  );
}
