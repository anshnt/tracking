import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { Route, Routes } from "react-router-dom";
import { ApiError, LOGIN_URL, get } from "./api/client";
import type { Me } from "./api/types";
import { AppFrame, SideNav } from "./components/Shell";
import { EmptyState, ErrorState, MeContext, Skeleton, errText } from "./components/ui";
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

export { SideNav };

export function Shell({ me }: { me: Me }) {
  const allowed = new Set(navFor(me.roles).map((i) => i.to));
  return (
    <MeContext.Provider value={me}>
      <AppFrame me={me}>
        <Routes>
          {Object.entries(PAGES).map(([path, el]) => (
            <Route key={path} path={path} element={allowed.has(path) ? el : <NotAllowed />} />
          ))}
          <Route path="*" element={<NotAllowed />} />
        </Routes>
      </AppFrame>
    </MeContext.Provider>
  );
}

function NotAllowed() {
  return (
    <section className="page">
      <header className="page-head">
        <div className="page-titles">
          <h1>Not available</h1>
        </div>
      </header>
      <EmptyState title="This page does not exist or is not part of your role.">Use the menu to open a page you have access to.</EmptyState>
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
      <main className="signin">
        <div className="signin-card">
          <ErrorState title="Cannot reach the portal" message={error} onRetry={() => window.location.reload()} />
        </div>
      </main>
    );
  if (!me)
    return (
      <main className="signin" aria-busy="true">
        <div className="signin-card">
          <Skeleton shape="lines" rows={3} label="Signing you in" />
        </div>
      </main>
    );
  return <Shell me={me} />;
}
