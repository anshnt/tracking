import "../styles/team-security.css";
import { get } from "../api/client";
import type { Device, OverviewPerson, Posture, Workspace } from "../api/types";
import { hasRole } from "../lib/nav";
import { postureReason } from "../lib/posture";
import { count, headline } from "../lib/text";
import { Async, Button, DataTable, Page, PostureBadge, Section, StatStrip, StatusTag, Ts, errText, useLoad, useMe } from "../components/ui";

type PostureResult = { posture: Posture } | { error: string };

function DeviceRow({ d, result, retry }: { d: Device; result: PostureResult | undefined; retry: () => void }) {
  const p = result && "posture" in result ? result.posture : null;
  return (
    <tr>
      <th scope="row" className="dev-name">
        {d.name}
        <small className="sub">
          {d.ownership}
          {d.os ? `, ${d.os}` : ""}
        </small>
      </th>
      {result && "error" in result && (
        <td colSpan={3} className="cell-error" role="alert">
          Posture could not be loaded: {result.error}{" "}
          <Button variant="quiet" onClick={retry}>
            Try again
          </Button>
        </td>
      )}
      {!result && (
        <td colSpan={3} className="cell-state">
          Checking posture
        </td>
      )}
      {p && (
        <>
          <td>
            <div className="posture-cell">
              <PostureBadge state={p.state} />
              <small>{postureReason(p.reason)}</small>
            </div>
          </td>
          <td>{p.observed_at ? <Ts iso={p.observed_at} /> : <span className="cell-state">Never observed</span>}</td>
          <td>
            {p.failing_checks.length === 0 ? (
              <span className="cell-state">None</span>
            ) : (
              <ul className="checks">
                {p.failing_checks.map((c) => (
                  <li key={c.check} className="chip">
                    {c.detail ? `${c.check} (${c.detail})` : c.check}
                  </li>
                ))}
              </ul>
            )}
          </td>
        </>
      )}
    </tr>
  );
}

function TeamWorkspaces({ person }: { person: OverviewPerson }) {
  const load = useLoad(() => get<{ workspaces: Workspace[] }>(`/workspaces?employee_id=${person.employee_id}`));
  const ws = load.data?.workspaces;
  return (
    <tbody className="group-first">
      {load.error && (
        <tr>
          <th scope="row">{person.display_name}</th>
          <td colSpan={5} className="cell-error" role="alert">
            Workspaces could not be loaded: {load.error}{" "}
            <Button variant="quiet" onClick={load.reload}>
              Try again
            </Button>
          </td>
        </tr>
      )}
      {!ws && !load.error && (
        <tr>
          <th scope="row">{person.display_name}</th>
          <td colSpan={5} className="cell-state">
            Loading workspaces
          </td>
        </tr>
      )}
      {ws && ws.length === 0 && (
        <tr>
          <th scope="row">{person.display_name}</th>
          <td colSpan={5} className="cell-state">
            No workspace.
          </td>
        </tr>
      )}
      {ws?.map((w, i) => (
        <tr key={w.id}>
          <th scope="row">{i === 0 ? person.display_name : <span className="visually-hidden">{person.display_name}</span>}</th>
          <td>{w.name}</td>
          <td>{w.role_profile}</td>
          <td>Up to {w.classification_ceiling}</td>
          <td>
            <StatusTag status={w.lifecycle_state} />
          </td>
          <td>
            <div className="posture-cell">
              <PostureBadge state={w.posture.state} />
              <small>{postureReason(w.posture.reason)}</small>
            </div>
          </td>
        </tr>
      ))}
    </tbody>
  );
}

export function Devices() {
  const me = useMe();
  const devices = useLoad(() => get<{ devices: Device[] }>("/devices"));
  // One posture read per device, kept here so the summary strip and the rows share them.
  const postures = useLoad(async () => {
    const list = devices.data?.devices ?? [];
    const entries = await Promise.all(
      list.map(async (d): Promise<[string, PostureResult]> => {
        try {
          return [d.id, { posture: await get<Posture>(`/devices/${d.id}/posture`) }];
        } catch (e) {
          return [d.id, { error: errText(e) }];
        }
      }),
    );
    return Object.fromEntries(entries) as Record<string, PostureResult>;
  }, [devices.data]);
  const team = hasRole(me.roles, "manager");
  const people = useLoad(() => (team ? get<{ people: OverviewPerson[] }>("/overview") : Promise.resolve({ people: [] })));
  const wide = hasRole(me.roles, "it", "security");

  const list = devices.data?.devices ?? [];
  const results = postures.data ?? {};
  const read = list.map((d) => results[d.id]).filter((r): r is { posture: Posture } => !!r && "posture" in r);
  const by = (state: string) => read.filter((r) => r.posture.state === state).length;
  const failing = read.reduce((n, r) => n + r.posture.failing_checks.length, 0);
  const unknown = by("unknown");
  const bad = by("noncompliant");

  return (
    <Page
      title="Devices and workspaces"
      lead="Stale or missing evidence is shown as unknown, never as compliant. Personal devices are not applicable: nothing is collected from them."
    >
      {list.length > 0 && (
        <StatStrip
          label="Device summary"
          headline={headline(
            [bad > 0 && `${count(bad, "device")} noncompliant`, unknown > 0 && `${count(unknown, "device")} unknown`, failing > 0 && count(failing, "failing check")],
            read.length < list.length ? "Checking posture." : "Nothing needs attention.",
          )}
          items={[
            { label: "Devices", value: list.length },
            { label: "Compliant", value: by("compliant") },
            { label: "Unknown", value: unknown },
            { label: "Noncompliant", value: bad, tone: "bad" },
            { label: "Failing checks", value: failing, tone: "warn" },
            { label: "Not applicable", value: by("not_applicable") },
          ]}
        />
      )}
      <Section title={wide ? "All devices" : "My devices"}>
        <Async
          load={devices}
          isEmpty={(d) => d.devices.length === 0}
          empty={<p className="state-body">No devices are registered. Devices appear here once they are enrolled.</p>}
        >
          {({ devices: list }) => {
            return (
              <DataTable label="Device posture">
                  <colgroup>
                    <col className="col-name" />
                    <col className="col-state" />
                    <col className="col-when" />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Device</th>
                      <th scope="col">State</th>
                      <th scope="col">Last observed</th>
                      <th scope="col">Failing checks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((d) => (
                      <DeviceRow key={d.id} d={d} result={results[d.id]} retry={postures.reload} />
                    ))}
                  </tbody>
                </DataTable>
            );
          }}
        </Async>
      </Section>

      {team && (
        <Section title="Workspaces of my team">
          <Async
            load={people}
            isEmpty={(d) => d.people.length === 0}
            empty={<p className="state-body">No direct reports, so there are no team workspaces to show.</p>}
          >
            {({ people: ps }) => (
              <DataTable label="Team workspaces">
                <thead>
                  <tr>
                    <th scope="col">Person</th>
                    <th scope="col">Workspace</th>
                    <th scope="col">Role profile</th>
                    <th scope="col">Classification</th>
                    <th scope="col">Lifecycle</th>
                    <th scope="col">Posture</th>
                  </tr>
                </thead>
                {ps.map((p) => (
                  <TeamWorkspaces key={p.employee_id} person={p} />
                ))}
              </DataTable>
            )}
          </Async>
        </Section>
      )}
    </Page>
  );
}
