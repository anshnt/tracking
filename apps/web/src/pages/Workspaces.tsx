import { get } from "../api/client";
import type { Workspace } from "../api/types";
import { postureReason } from "../lib/posture";
import { Async, Empty, Page, PostureBadge, StatusTag, useLoad } from "../components/ui";

export function Workspaces() {
  const load = useLoad(() => get<{ workspaces: Workspace[] }>("/workspaces"));
  return (
    <Page title="My workspaces" lead="Launch links open the gateway. They carry no credentials; you sign in there yourself.">
      <Async load={load}>
        {({ workspaces }) =>
          workspaces.length === 0 ? (
            <Empty>No workspace has been assigned to you.</Empty>
          ) : (
            <ul className="cards">
              {workspaces.map((w) => (
                <li key={w.id} className="card">
                  <h2>{w.name}</h2>
                  <p className="meta">
                    Profile {w.role_profile}. Data up to <strong>{w.classification_ceiling}</strong>. <StatusTag status={w.lifecycle_state} />
                  </p>
                  <p className="meta">
                    Posture: <PostureBadge state={w.posture.state} /> {postureReason(w.posture.reason)}
                  </p>
                  {w.launch_url ? (
                    <a className="button primary" href={w.launch_url} target="_blank" rel="noopener noreferrer">
                      Open workspace
                    </a>
                  ) : (
                    <p className="muted">Not launchable right now (state: {w.lifecycle_state.replace(/_/g, " ")}).</p>
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </Page>
  );
}
