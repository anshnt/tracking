import { useState } from "react";
import type { FormEvent } from "react";
import { get, patch, post } from "../api/client";
import { CLASSIFICATIONS, ROLES } from "../api/types";
import type { AdminAsset, AdminEmployee, AdminWorkspace, Classification, Role } from "../api/types";
import { Async, Empty, Field, Page, Result, StatusTag, useAction, useLoad, useMe } from "../components/ui";

const LIFECYCLE = ["requested", "active", "suspended", "decommissioned"];

function RoleEditor({ e, onDone }: { e: AdminEmployee; onDone: () => void }) {
  const me = useMe();
  const act = useAction();
  const [roles, setRoles] = useState<Role[]>(e.roles);
  const toggle = (r: Role) => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r]);
  return (
    <form
      onSubmit={async (ev) => {
        ev.preventDefault();
        if (await act.run(() => patch(`/admin/employees/${e.id}`, { roles }), "Roles saved.")) onDone();
      }}
    >
      <fieldset disabled={e.id === me.id || act.busy}>
        <legend className="sr">Roles for {e.display_name}</legend>
        {ROLES.map((r) => (
          <label key={r} className="check">
            <input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} /> {r}
          </label>
        ))}
        <button disabled={roles.length === 0}>Save roles</button>
      </fieldset>
      {e.id === me.id && <small className="muted">You cannot change your own roles.</small>}
      <Result ok={act.ok} err={act.err} />
    </form>
  );
}

function People() {
  const list = useLoad(() => get<{ employees: AdminEmployee[] }>("/admin/employees?limit=500"));
  const act = useAction();
  const [f, setF] = useState({ oidc_subject: "", display_name: "", email: "", manager_id: "", timezone: "UTC" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/employees", { ...f, manager_id: f.manager_id.trim() || null, roles: ["employee"] }), "Employee created.")) {
      setF({ oidc_subject: "", display_name: "", email: "", manager_id: "", timezone: "UTC" });
      list.reload();
    }
  }
  return (
    <>
      <form className="card form" onSubmit={submit}>
        <h2>Add an employee</h2>
        <Field label="Identity subject (from Keycloak)">
          <input required value={f.oidc_subject} onChange={set("oidc_subject")} />
        </Field>
        <Field label="Display name">
          <input required value={f.display_name} onChange={set("display_name")} />
        </Field>
        <Field label="Email">
          <input required type="email" value={f.email} onChange={set("email")} />
        </Field>
        <Field label="Manager ID (optional)">
          <input className="mono" value={f.manager_id} onChange={set("manager_id")} />
        </Field>
        <Field label="Timezone" hint="IANA name, for example Europe/London">
          <input required value={f.timezone} onChange={set("timezone")} />
        </Field>
        <button className="primary" disabled={act.busy}>
          Create
        </button>
        <Result ok={act.ok} err={act.err} />
      </form>
      <Async load={list}>
        {({ employees }) =>
          employees.length === 0 ? (
            <Empty>No employees.</Empty>
          ) : (
            <ul className="stack">
              {employees.map((e) => (
                <li key={e.id} className="card">
                  <h3>{e.display_name}</h3>
                  <p className="meta">
                    {e.email}. <StatusTag status={e.status} /> {e.timezone}. <span className="mono">{e.id}</span>
                  </p>
                  <RoleEditor e={e} onDone={list.reload} />
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </>
  );
}

function Assets() {
  const list = useLoad(() => get<{ assets: AdminAsset[] }>("/admin/assets?limit=500"));
  const act = useAction();
  const [f, setF] = useState({ name: "", ownership: "company", assigned_employee_id: "", os: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/assets", { ...f, assigned_employee_id: f.assigned_employee_id.trim() || null, os: f.os.trim() || null }), "Asset created.")) {
      setF({ ...f, name: "", assigned_employee_id: "", os: "" });
      list.reload();
    }
  }
  return (
    <>
      <form className="card form" onSubmit={submit}>
        <h2>Add an asset</h2>
        <Field label="Name">
          <input required value={f.name} onChange={set("name")} />
        </Field>
        <Field label="Ownership" hint="Personal devices are recorded for inventory only; nothing is collected from them.">
          <select value={f.ownership} onChange={set("ownership")}>
            <option>company</option>
            <option>personal</option>
          </select>
        </Field>
        <Field label="Assigned employee ID (optional)">
          <input className="mono" value={f.assigned_employee_id} onChange={set("assigned_employee_id")} />
        </Field>
        <Field label="Operating system (optional)">
          <input value={f.os} onChange={set("os")} />
        </Field>
        <button className="primary" disabled={act.busy}>
          Create
        </button>
        <Result ok={act.ok} err={act.err} />
      </form>
      <Async load={list}>
        {({ assets }) =>
          assets.length === 0 ? (
            <Empty>No assets.</Empty>
          ) : (
            <div className="tablewrap">
              <table>
                <caption className="sr">Assets</caption>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Ownership</th>
                    <th scope="col">OS</th>
                    <th scope="col">Assigned to</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.map((a) => (
                    <tr key={a.id}>
                      <th scope="row">{a.name}</th>
                      <td>{a.ownership}</td>
                      <td>{a.os ?? ""}</td>
                      <td className="mono">{a.assigned_employee_id ?? "unassigned"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Async>
    </>
  );
}

function WorkspaceRow({ w, onDone }: { w: AdminWorkspace; onDone: () => void }) {
  const act = useAction();
  return (
    <li className="card">
      <h3>{w.name}</h3>
      <p className="meta">
        {w.role_profile}, up to {w.classification_ceiling}. Owner <span className="mono">{w.owner_id}</span>
      </p>
      <Field label="Lifecycle state">
        <select
          value={w.lifecycle_state}
          disabled={act.busy}
          onChange={async (e) => {
            if (await act.run(() => patch(`/admin/workspaces/${w.id}`, { lifecycle_state: e.target.value }), "State updated.")) onDone();
          }}
        >
          {LIFECYCLE.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </Field>
      <Result ok={act.ok} err={act.err} />
    </li>
  );
}

function Workspaces() {
  const list = useLoad(() => get<{ workspaces: AdminWorkspace[] }>("/admin/workspaces?limit=500"));
  const act = useAction();
  const [f, setF] = useState({ owner_id: "", name: "", role_profile: "", classification_ceiling: "internal" as Classification, connection_ref: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/workspaces", { ...f, connection_ref: f.connection_ref.trim() || null }), "Workspace created.")) {
      setF({ ...f, name: "", connection_ref: "" });
      list.reload();
    }
  }
  return (
    <>
      <form className="card form" onSubmit={submit}>
        <h2>Add a workspace</h2>
        <Field label="Owner employee ID">
          <input required className="mono" value={f.owner_id} onChange={set("owner_id")} />
        </Field>
        <Field label="Name">
          <input required value={f.name} onChange={set("name")} />
        </Field>
        <Field label="Role profile">
          <input required value={f.role_profile} onChange={set("role_profile")} />
        </Field>
        <Field label="Classification ceiling">
          <select value={f.classification_ceiling} onChange={set("classification_ceiling")}>
            {CLASSIFICATIONS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Gateway connection reference (optional)">
          <input value={f.connection_ref} onChange={set("connection_ref")} />
        </Field>
        <button className="primary" disabled={act.busy}>
          Create
        </button>
        <Result ok={act.ok} err={act.err} />
      </form>
      <Async load={list}>
        {({ workspaces }) =>
          workspaces.length === 0 ? (
            <Empty>No workspaces.</Empty>
          ) : (
            <ul className="cards">
              {workspaces.map((w) => (
                <WorkspaceRow key={w.id} w={w} onDone={list.reload} />
              ))}
            </ul>
          )
        }
      </Async>
    </>
  );
}

const TABS = ["People", "Assets", "Workspaces"] as const;

export function Admin() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("People");
  return (
    <Page title="People, assets and workspaces">
      <div role="tablist" aria-label="Admin sections" className="tabs">
        {TABS.map((t) => (
          <button key={t} role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls="admin-panel" onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="admin-panel" aria-labelledby={`tab-${tab}`}>
        {tab === "People" && <People />}
        {tab === "Assets" && <Assets />}
        {tab === "Workspaces" && <Workspaces />}
      </div>
    </Page>
  );
}
