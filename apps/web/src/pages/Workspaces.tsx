import { get } from "../api/client";
import type { Workspace } from "../api/types";
import { postureReason } from "../lib/posture";
import { Async, DataTable, EmptyState, Page, PostureBadge, StatusTag, useLoad } from "../components/ui";
import "../styles/employee.css";

export function Workspaces() {
  const load = useLoad(() => get<{ workspaces: Workspace[] }>("/workspaces"));
  return (
    <Page title="My workspaces" lead="Launch links open the gateway. They carry no credentials; you sign in there yourself.">
      <Async
        load={load}
        isEmpty={(d) => d.workspaces.length === 0}
        empty={<EmptyState title="No workspace assigned">Workspaces appear here once an administrator assigns one to you.</EmptyState>}
      >
        {({ workspaces }) => (
          <DataTable label="My workspaces">
            <thead>
              <tr>
                <th scope="col">Workspace</th>
                <th scope="col">State</th>
                <th scope="col">Data up to</th>
                <th scope="col">Device posture</th>
                <th scope="col">Launch</th>
              </tr>
            </thead>
            <tbody>
              {workspaces.map((w) => (
                <tr key={w.id}>
                  <th scope="row">
                    {w.name}
                    <p className="e-sub">Profile {w.role_profile}</p>
                  </th>
                  <td>
                    <StatusTag status={w.lifecycle_state} />
                  </td>
                  <td>{w.classification_ceiling}</td>
                  <td>
                    <PostureBadge state={w.posture.state} />
                    <p className="e-sub">{postureReason(w.posture.reason)}</p>
                  </td>
                  <td>
                    {w.launch_url ? (
                      <a className="btn btn-secondary" href={w.launch_url} target="_blank" rel="noopener noreferrer">
                        Open workspace
                      </a>
                    ) : (
                      <span className="meta">Not launchable (state: {w.lifecycle_state.replace(/_/g, " ")})</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Async>
    </Page>
  );
}
