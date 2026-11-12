import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { get, patch, post } from "../api/client";
import { CLASSIFICATIONS, ROLES } from "../api/types";
import type { AdminAsset, AdminEmployee, AdminWorkspace, Classification, Role } from "../api/types";
import { Async, Button, DataTable, EmptyState, Field, IdCell, Page, Panel, Result, Section, StatStrip, StatusPill, StatusTag, useAction, useLoad, useMe } from "../components/ui";
import { count, headline } from "../lib/text";
import "../styles/ops-admin.css";

const LIFECYCLE = ["requested", "active", "suspended", "decommissioned"];

function RoleEditor({ e, onDone }: { e: AdminEmployee; onDone: () => void }) {
  const me = useMe();
  const act = useAction();
  const [roles, setRoles] = useState<Role[]>(e.roles);
  const toggle = (r: Role) => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r]);
  return (
    <details className="ops-more">
      <summary>
        Edit roles<span className="visually-hidden"> for {e.display_name}</span>
      </summary>
      <form
        onSubmit={async (ev) => {
          ev.preventDefault();
          if (await act.run(() => patch(`/admin/employees/${e.id}`, { roles }), "Roles saved.")) onDone();
        }}
      >
        <fieldset disabled={e.id === me.id || act.busy} className="ops-roles-edit">
          <legend className="visually-hidden">Roles for {e.display_name}</legend>
          {ROLES.map((r) => (
            <label key={r} className="check">
              <input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} /> {r}
            </label>
          ))}
          <Button type="submit" disabled={roles.length === 0}>Save roles</Button>
        </fieldset>
        {e.id === me.id && <p className="ops-cell-note">You cannot change your own roles.</p>}
        <Result ok={act.ok} err={act.err} />
      </form>
    </details>
  );
}

function People() {
  const list = useLoad(() => get<{ employees: AdminEmployee[] }>("/admin/employees?limit=500"));
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ oidc_subject: "", display_name: "", email: "", manager_id: "", timezone: "UTC" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/employees", { ...f, manager_id: f.manager_id.trim() || null, roles: ["employee"] }), "Employee created.")) {
      setF({ oidc_subject: "", display_name: "", email: "", manager_id: "", timezone: "UTC" });
      list.reload();
      setOpen(false);
    }
  }
  const emps = list.data?.employees;
  const inactive = emps ? emps.filter((e) => e.status !== "active").length : 0;
  return (
    <>
      {emps && emps.length > 0 && (
        <StatStrip
          label="People summary"
          headline={headline([inactive > 0 && `${count(inactive, "person", "people")} not active`], `${count(emps.length, "person", "people")}, all active`)}
          items={[
            { label: "People", value: emps.length },
            { label: "Active", value: emps.length - inactive },
            { label: "Not active", value: inactive, tone: "warn" },
            { label: "Admins", value: emps.filter((e) => e.roles.includes("admin")).length },
            { label: "Managers", value: emps.filter((e) => e.roles.includes("manager")).length },
          ]}
        />
      )}
      {open && (
      <Panel title="Add an employee">
        <form className="form" onSubmit={submit}>
          <div className="ops-grid">
            <Field label="Identity subject" hint="As it appears in Keycloak." required>
              <input required value={f.oidc_subject} onChange={set("oidc_subject")} />
            </Field>
            <Field label="Display name" required>
              <input required value={f.display_name} onChange={set("display_name")} />
            </Field>
            <Field label="Email" required>
              <input required type="email" value={f.email} onChange={set("email")} />
            </Field>
            <Field label="Manager ID (optional)" hint="Leave empty for no manager.">
              <input className="mono" value={f.manager_id} onChange={set("manager_id")} />
            </Field>
            <Field label="Timezone" hint="IANA name, such as Europe/London." required>
              <input required value={f.timezone} onChange={set("timezone")} />
            </Field>
          </div>
          <div className="ops-actions">
            <Button variant="primary" type="submit" disabled={act.busy}>
              Create
            </Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Result ok={act.ok} err={act.err} />
          </div>
        </form>
      </Panel>
      )}
      <Section
        title="People"
        actions={
          !open && (
            <Button variant="primary" aria-expanded={open} onClick={() => setOpen(true)}>
              Add an employee
            </Button>
          )
        }
      >
        <Async
          load={list}
          rows={5}
          isEmpty={(d) => d.employees.length === 0}
          empty={
            <EmptyState
              title="No employees yet"
              action={
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add the first employee
                </Button>
              }
            >
              Employees you add here can sign in with their Keycloak identity.
            </EmptyState>
          }
        >
          {({ employees }) => (
            <DataTable label="People">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Status</th>
                  <th scope="col">Timezone</th>
                  <th scope="col">ID</th>
                  <th scope="col">Roles</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((e) => (
                  <tr key={e.id}>
                    <th scope="row" className="nowrap">
                      {e.display_name}
                    </th>
                    <td>{e.email}</td>
                    <td>
                      <StatusTag status={e.status} />
                    </td>
                    <td>{e.timezone}</td>
                    <td>
                      <IdCell id={e.id} />
                    </td>
                    <td>
                      <div className="ops-roles">
                        {e.roles.map((r) => (
                          <StatusPill key={r} tone="muted" glyph={false}>
                            {r}
                          </StatusPill>
                        ))}
                      </div>
                      <RoleEditor e={e} onDone={list.reload} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Async>
      </Section>
    </>
  );
}

function Assets() {
  const list = useLoad(() => get<{ assets: AdminAsset[] }>("/admin/assets?limit=500"));
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", ownership: "company", assigned_employee_id: "", os: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/assets", { ...f, assigned_employee_id: f.assigned_employee_id.trim() || null, os: f.os.trim() || null }), "Asset created.")) {
      setF({ ...f, name: "", assigned_employee_id: "", os: "" });
      list.reload();
      setOpen(false);
    }
  }
  return (
    <>
      {open && (
      <Panel title="Add an asset">
        <form className="form" onSubmit={submit}>
          <div className="ops-grid">
            <Field label="Name" required>
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
          </div>
          <div className="ops-actions">
            <Button variant="primary" type="submit" disabled={act.busy}>
              Create
            </Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Result ok={act.ok} err={act.err} />
          </div>
        </form>
      </Panel>
      )}
      <Section
        title="Assets"
        actions={
          !open && (
            <Button variant="primary" aria-expanded={open} onClick={() => setOpen(true)}>
              Add an asset
            </Button>
          )
        }
      >
        <Async
          load={list}
          rows={5}
          isEmpty={(d) => d.assets.length === 0}
          empty={
            <EmptyState
              title="No assets yet"
              action={
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add the first asset
                </Button>
              }
            >
              Company and personal devices are listed here.
            </EmptyState>
          }
        >
          {({ assets }) => (
            <DataTable label="Assets">
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
                    <td>{a.assigned_employee_id ? <IdCell id={a.assigned_employee_id} /> : <span className="meta">Unassigned</span>}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Async>
      </Section>
    </>
  );
}

function WorkspaceRow({ w, onDone }: { w: AdminWorkspace; onDone: () => void }) {
  const act = useAction();
  return (
    <tr>
      <th scope="row">{w.name}</th>
      <td>{w.role_profile}</td>
      <td>{w.classification_ceiling}</td>
      <td>
        <IdCell id={w.owner_id} />
      </td>
      <td>
        <select
          className="ops-ws-select"
          aria-label={`Lifecycle state for ${w.name}`}
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
        <Result ok={act.ok} err={act.err} />
      </td>
    </tr>
  );
}

function Workspaces() {
  const list = useLoad(() => get<{ workspaces: AdminWorkspace[] }>("/admin/workspaces?limit=500"));
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ owner_id: "", name: "", role_profile: "", classification_ceiling: "internal" as Classification, connection_ref: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await act.run(() => post("/admin/workspaces", { ...f, connection_ref: f.connection_ref.trim() || null }), "Workspace created.")) {
      setF({ ...f, name: "", connection_ref: "" });
      list.reload();
      setOpen(false);
    }
  }
  return (
    <>
      {open && (
      <Panel title="Add a workspace">
        <form className="form" onSubmit={submit}>
          <div className="ops-grid">
            <Field label="Owner employee ID" required>
              <input required className="mono" value={f.owner_id} onChange={set("owner_id")} />
            </Field>
            <Field label="Name" required>
              <input required value={f.name} onChange={set("name")} />
            </Field>
            <Field label="Role profile" required>
              <input required value={f.role_profile} onChange={set("role_profile")} />
            </Field>
            <Field label="Classification ceiling">
              <select value={f.classification_ceiling} onChange={set("classification_ceiling")}>
                {CLASSIFICATIONS.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label="Gateway reference (optional)">
              <input value={f.connection_ref} onChange={set("connection_ref")} />
            </Field>
          </div>
          <div className="ops-actions">
            <Button variant="primary" type="submit" disabled={act.busy}>
              Create
            </Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Result ok={act.ok} err={act.err} />
          </div>
        </form>
      </Panel>
      )}
      <Section
        title="Workspaces"
        actions={
          !open && (
            <Button variant="primary" aria-expanded={open} onClick={() => setOpen(true)}>
              Add a workspace
            </Button>
          )
        }
      >
        <Async
          load={list}
          rows={4}
          isEmpty={(d) => d.workspaces.length === 0}
          empty={
            <EmptyState
              title="No workspaces yet"
              action={
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add the first workspace
                </Button>
              }
            >
              A workspace is where one person works, with a classification ceiling.
            </EmptyState>
          }
        >
          {({ workspaces }) => (
            <DataTable label="Workspaces">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role profile</th>
                  <th scope="col">Ceiling</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {workspaces.map((w) => (
                  <WorkspaceRow key={w.id} w={w} onDone={list.reload} />
                ))}
              </tbody>
            </DataTable>
          )}
        </Async>
      </Section>
    </>
  );
}

const TABS = ["People", "Assets", "Workspaces"] as const;

export function Admin() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("People");
  const onKeys = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(TABS.indexOf(tab) + step + TABS.length) % TABS.length];
    setTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  };
  return (
    <Page title="People, assets and workspaces" lead="Directory records the portal acts on. Changes are written to the audit log.">
      <div role="tablist" aria-label="Admin sections" className="tabs ops-tabs" onKeyDown={onKeys}>
        {TABS.map((t) => (
          <button key={t} role="tab" tabIndex={tab === t ? 0 : -1} id={`tab-${t}`} aria-selected={tab === t} aria-controls="admin-panel" onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="admin-panel" aria-labelledby={`tab-${tab}`} className="ops-panel">
        {tab === "People" && <People />}
        {tab === "Assets" && <Assets />}
        {tab === "Workspaces" && <Workspaces />}
      </div>
    </Page>
  );
}
