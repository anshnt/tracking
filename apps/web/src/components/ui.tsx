import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Me } from "../api/types";
import { postureBadge } from "../lib/posture";
import type { Badge as BadgeInfo } from "../lib/posture";
import { formatTs } from "../lib/time";

export const MeContext = createContext<Me | null>(null);
export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside MeContext");
  return me;
}

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef
      .current()
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((e) => live && setState((s) => ({ data: s.data, error: errText(e), loading: false })));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** Renders loading / error / content. Keeps showing old data under a refresh error. */
export function Async<T>({
  load,
  children,
}: {
  load: Loaded<T>;
  children: (data: T) => ReactNode;
}) {
  return (
    <div aria-live="polite" aria-busy={load.loading}>
      {load.error && (
        <p className="msg err" role="alert">
          {load.error}{" "}
          <button type="button" className="link" onClick={load.reload}>
            Retry
          </button>
        </p>
      )}
      {load.data === null && load.loading && <p className="muted">Loading...</p>}
      {load.data !== null && children(load.data)}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

export function Page({ title, children, lead }: { title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h1>{title}</h1>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </section>
  );
}

export function Tag({ tone, mark, children }: { tone: BadgeInfo["tone"]; mark?: string; children: ReactNode }) {
  return (
    <span className={`badge ${tone}`}>
      {mark && <span aria-hidden="true">{mark} </span>}
      {children}
    </span>
  );
}

export function PostureBadge({ state }: { state: string }) {
  const b = postureBadge(state);
  return (
    <Tag tone={b.tone} mark={b.mark}>
      {b.label}
    </Tag>
  );
}

/** A timestamp rendered in the viewer's zone, with the raw instant on hover. */
export function Ts({ iso }: { iso: string | null | undefined }) {
  const me = useMe();
  return (
    <time dateTime={iso ?? undefined} title={iso ?? undefined}>
      {formatTs(iso, me.timezone)}
    </time>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

/** Result of a user action. Success is polite, failure is an alert. */
export function Result({ ok, err }: { ok: string | null; err: string | null }) {
  return (
    <div className="result">
      <p className="msg ok" role="status">
        {ok}
      </p>
      <p className="msg err" role="alert">
        {err}
      </p>
    </div>
  );
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setOk(null);
    setErr(null);
    try {
      await fn();
      setOk(success);
      return true;
    } catch (e) {
      setErr(errText(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, ok, err, run };
}

export function StatusTag({ status }: { status: string }) {
  const bad = ["failed", "rejected", "noncompliant", "critical", "high", "incomplete"];
  const good = ["released", "succeeded", "verified", "verified_complete", "approved", "closed", "resolved", "compliant"];
  const warn = ["manual_required", "skipped_not_configured", "requested", "reviewed", "staged", "in_progress", "running", "pending", "medium"];
  const tone: BadgeInfo["tone"] = bad.includes(status)
    ? "bad"
    : good.includes(status)
      ? "ok"
      : warn.includes(status)
        ? "warn"
        : "muted";
  return <Tag tone={tone}>{status.replace(/_/g, " ")}</Tag>;
}
