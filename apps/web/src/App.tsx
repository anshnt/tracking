import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { ApiError, LOGIN_URL, get, post } from "./api/client";
import type { Me } from "./api/types";
import { MeContext, errText } from "./components/ui";
import { navFor } from "./lib/nav";
import { Admin } from "./pages/Admin";
import { Cases } from "./pages/Cases";
import { Connectors } from "./pages/Connectors";
import { DevSignIn } from "./pages/DevSignIn";
import { Devices } from "./pages/Devices";
import { ExportQueue } from "./pages/ExportQueue";
import { Exports } from "./pages/Exports";
import { Home } from "./pages/Home";
import { Offboarding } from "./pages/Offboarding";
import { Policies } from "./pages/Policies";
import { Records } from "./pages/Records";
import { Tasks } from "./pages/Tasks";
import { Team } from "./pages/Team";
import { Updates } from "./pages/Updates";
import { Workspaces } from "./pages/Workspaces";

const PAGES: Record<string, ReactElement> = {
  "/": <Home />,
  "/workspaces": <Workspaces />,
  "/tasks": <Tasks />,
  "/updates": <Updates />,
  "/exports": <Exports />,
  "/records": <Records />,
  "/team": <Team />,
  "/devices": <Devices />,
  "/cases": <Cases />,
  "/export-queue": <ExportQueue />,
  "/offboarding": <Offboarding />,
  "/connectors": <Connectors />,
  "/policies": <Policies />,
  "/admin": <Admin />,
};

export function SideNav({ me }: { me: Me }) {
  const items = navFor(me.roles);
  const groups = [...new Set(items.map((i) => i.group))];
  return (
    <nav aria-label="Main">
      {groups.map((g) => (
        <div key={g}>
          <h2 className="navgroup">{g}</h2>
          <ul className="plain">
            {items
              .filter((i) => i.group === g)
              .map((i) => (
                <li key={i.to}>
                  <NavLink to={i.to} end={i.to === "/"}>
                    {i.label}
                  </NavLink>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function Shell({ me }: { me: Me }) {
  const allowed = new Set(navFor(me.roles).map((i) => i.to));
  return (
    <MeContext.Provider value={me}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="top">
        <strong>Work and Security Portal</strong>
        <span className="muted">
          {me.display_name} ({me.roles.join(", ")}). Times shown in {me.timezone}.
        </span>
        <button
          type="button"
          onClick={async () => {
            try {
              await post("/api/auth/logout");
            } finally {
              window.location.assign("/");
            }
          }}
        >
          Sign out
        </button>
      </header>
      <div className="layout">
        <SideNav me={me} />
        <main id="main" tabIndex={-1}>
          <Routes>
            {Object.entries(PAGES).map(([path, el]) => (
              <Route key={path} path={path} element={allowed.has(path) ? el : <NotAllowed />} />
            ))}
            <Route path="*" element={<NotAllowed />} />
          </Routes>
        </main>
      </div>
    </MeContext.Provider>
  );
}

function NotAllowed() {
  return (
    <section>
      <h1>Not available</h1>
      <p>This page does not exist or is not part of your role.</p>
    </section>
  );
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [devSignIn, setDevSignIn] = useState(false);
  useEffect(() => {
    get<Me>("/me")
      .then(setMe)
      .catch(async (e) => {
        if (!(e instanceof ApiError && e.status === 401)) return setError(errText(e));
        const methods = await get<{ oidc: boolean; dev: boolean }>("/api/auth/methods").catch(() => null);
        if (methods?.dev && !methods.oidc) setDevSignIn(true);
        else window.location.assign(LOGIN_URL);
      });
  }, []);
  if (devSignIn) return <DevSignIn />;
  if (error)
    return (
      <main className="center" role="alert">
        <h1>Cannot reach the portal</h1>
        <p>{error}</p>
        <button type="button" onClick={() => window.location.reload()}>
          Try again
        </button>
      </main>
    );
  if (!me)
    return (
      <main className="center" aria-busy="true">
        <p>Signing you in...</p>
      </main>
    );
  return <Shell me={me} />;
}
