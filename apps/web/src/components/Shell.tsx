import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { post } from "../api/client";
import type { Me, Role } from "../api/types";
import { NAV, navFor } from "../lib/nav";

const NARROW = "(max-width: 60rem)";

function useNarrow(): boolean {
  return useSyncExternalStore(
    (cb) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const mq = window.matchMedia(NARROW);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches,
    () => false,
  );
}

/** The mark: a trail of three points ending in a solid one. */
export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 28 28" width="28" height="28" aria-hidden="true">
      <circle cx="5" cy="21" r="2" className="mark-a" />
      <circle cx="12" cy="15" r="2.6" className="mark-b" />
      <circle cx="20.5" cy="8" r="4" className="mark-c" />
    </svg>
  );
}

export function Wordmark({ sub = true }: { sub?: boolean }) {
  return (
    <span className="wordmark-inner">
      <Mark />
      <span className="wordmark-text">
        <span className="wordmark-name">tracking</span>
        {sub && <span className="wordmark-sub">Work and security portal</span>}
      </span>
    </span>
  );
}

export const ROLE_LABEL: Record<Role, string> = {
  employee: "Employee",
  manager: "Manager",
  it: "IT",
  security: "Security",
  approver: "Approver",
  admin: "Admin",
};

/** Grouped links for the roles this person holds. The server enforces the same rules; this only hides links. */
export function SideNav({ me, onNavigate }: { me: Me; onNavigate?: () => void }) {
  const items = navFor(me.roles);
  const groups = [...new Set(items.map((i) => i.group))];
  return (
    <nav className="nav" aria-label="Main">
      {groups.map((g) => (
        <div key={g}>
          <p className="nav-group" id={`nav-${g}`}>
            {g}
          </p>
          <ul className="nav-list" aria-labelledby={`nav-${g}`}>
            {items
              .filter((i) => i.group === g)
              .map((i) => (
                <li key={i.to}>
                  <NavLink className="nav-link" to={i.to} end={i.to === "/"} onClick={onNavigate}>
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

function Account({ me }: { me: Me }) {
  return (
    <div className="account">
      <div>
        <p className="account-name">{me.display_name}</p>
        <p className="account-roles">{me.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")}</p>
        <p className="account-tz">
          Times shown in <span className="mono">{me.timezone}</span>
        </p>
      </div>
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
    </div>
  );
}

function Crumbs() {
  const { pathname } = useLocation();
  const here = NAV.find((i) => i.to === pathname);
  if (!here) return <span className="crumbs" />;
  return (
    <nav aria-label="Breadcrumb">
      <ol className="crumbs">
        <li>{here.group}</li>
        <li aria-current="page">{here.label}</li>
      </ol>
    </nav>
  );
}

/** Sidebar, top bar and content column. Under 60rem the sidebar becomes a menu: Escape closes, focus returns to the button. */
export function AppFrame({ me, children }: { me: Me; children: ReactNode }) {
  const narrow = useNarrow();
  const [open, setOpen] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const side = useRef<HTMLElement>(null);
  const isOpen = open && narrow;

  const close = useCallback(() => {
    setOpen(false);
    menuBtn.current?.focus();
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    side.current?.querySelector<HTMLElement>("a")?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, close]);

  // keep Tab inside the open menu
  function trap(e: KeyboardEvent) {
    if (!isOpen || e.key !== "Tab") return;
    const f = side.current?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)");
    if (!f || f.length === 0) return;
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside id="sidebar" ref={side} className="sidebar" data-open={isOpen} inert={narrow && !isOpen} onKeyDown={trap}>
        <Link className="wordmark" to="/" aria-label="tracking, home" onClick={isOpen ? close : undefined}>
          <Wordmark />
        </Link>
        <SideNav me={me} onNavigate={isOpen ? close : undefined} />
        <Account me={me} />
      </aside>
      {isOpen && <div className="scrim" onClick={close} aria-hidden="true" />}
      <div className="content">
        <header className="topbar">
          <button
            ref={menuBtn}
            type="button"
            className="btn btn-quiet menu-btn"
            aria-expanded={isOpen}
            aria-controls="sidebar"
            onClick={() => setOpen((o) => !o)}
          >
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" className="menu-glyph">
              <path d="M2 4.5h12M2 8h12M2 11.5h12" />
            </svg>
            Menu
          </button>
          <Link className="wordmark wordmark-top" to="/" aria-label="tracking, home">
            <Wordmark sub={false} />
          </Link>
          <Crumbs />
        </header>
        <main id="main" className="main" tabIndex={-1}>
          <div className="page-wrap">{children}</div>
        </main>
      </div>
    </div>
  );
}
