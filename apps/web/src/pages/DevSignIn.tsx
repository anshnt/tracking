import { useState } from "react";
import type { FormEvent } from "react";
import { post } from "../api/client";
import { ROLES } from "../api/types";
import type { Role } from "../api/types";
import { errText } from "../components/ui";

/** Shown only when the API reports dev sign-in on and no identity provider (development only). */
export function DevSignIn() {
  const [subject, setSubject] = useState("dev-owner");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState<Role[]>(["employee"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggle(r: Role) {
    setRoles((cur) => (cur.includes(r) ? cur.filter((x) => x !== r) : [...cur, r]));
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await post("/api/auth/dev-login", { subject: subject.trim(), display_name: name.trim() || null, roles });
      window.location.reload();
    } catch (ex) {
      setErr(errText(ex));
      setBusy(false);
    }
  }
  return (
    <main className="center">
      <h1>Development sign-in</h1>
      <p>No identity provider is configured, and this server allows a sample sign-in. Production refuses to start with it on.</p>
      <form className="form" onSubmit={submit}>
        <label className="field">
          <span>Identity subject</span>
          <input name="subject" required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} autoComplete="off" />
        </label>
        <label className="field">
          <span>Display name (optional)</span>
          <input name="display_name" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
        </label>
        <fieldset>
          <legend>Roles</legend>
          <p className="meta">Used the first time a subject signs in. After that, roles change only in People and assets.</p>
          {ROLES.map((r) => (
            <label key={r} className="check">
              <input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} /> {r}
            </label>
          ))}
        </fieldset>
        <button className="primary" type="submit" disabled={busy || !subject.trim() || roles.length === 0}>
          Sign in
        </button>
        {err && <p role="alert">{err}</p>}
      </form>
    </main>
  );
}
