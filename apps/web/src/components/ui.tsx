import { cloneElement, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactElement, ReactNode } from "react";
import type { Me } from "../api/types";
import { formatTs } from "../lib/time";
import { EmptyState, ErrorState, Skeleton, useDelayed } from "./states";
import type { SkeletonShape } from "./states";

export { EmptyState, ErrorState, Skeleton } from "./states";
export { PostureBadge, StatusPill, StatusTag, Tag, statusTone } from "./pills";
export { NoticeCard } from "./NoticeCard";
export { IdCell } from "./IdCell";

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

/**
 * One wrapper for every region that loads data: skeleton (after 150ms), error with retry,
 * optional empty state, then the content. A refresh error keeps the old data on screen.
 */
export function Async<T>({
  load,
  children,
  skeleton = "rows",
  rows,
  isEmpty,
  empty,
  label,
}: {
  load: Loaded<T>;
  children: (data: T) => ReactNode;
  skeleton?: SkeletonShape;
  rows?: number;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  /** Screen-reader name for the loading state, e.g. "Loading tasks". */
  label?: string;
}) {
  const showSkeleton = useDelayed(load.loading && load.data === null);
  const data = load.data;
  return (
    <div className="async" aria-live="polite" aria-busy={load.loading}>
      {load.error && data === null && <ErrorState message={load.error} onRetry={load.reload} />}
      {load.error && data !== null && (
        <p className="msg err" role="alert">
          {load.error}{" "}
          <button type="button" className="link" onClick={load.reload}>
            Try again
          </button>
        </p>
      )}
      {data === null && load.loading && showSkeleton && <Skeleton shape={skeleton} rows={rows} label={label} />}
      {data !== null && (isEmpty?.(data) ? (empty ?? <EmptyState>Nothing here yet.</EmptyState>) : children(data))}
    </div>
  );
}

/** Plain empty line for existing callers; prefer EmptyState with a title and an action. */
export function Empty({ children }: { children: ReactNode }) {
  return <EmptyState>{children}</EmptyState>;
}

/** Page title, one line of description, and an optional actions slot (the page's one primary action). */
export function Page({ title, lead, actions, children }: { title: string; lead?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="page">
      <header className="page-head">
        <div className="page-titles">
          <h1>{title}</h1>
          {lead && <p className="lead">{lead}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

interface SectionProps {
  title: string;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

function SectionBody({ title, hint, actions, children, className }: SectionProps & { className: string }) {
  return (
    <section className={className}>
      <header className="section-head">
        <div>
          <h2>{title}</h2>
          {hint && <p className="meta">{hint}</p>}
        </div>
        {actions && <div className="section-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

/** A headed region on the page ground. Tables go here, with no surface behind them. */
export function Section(props: SectionProps) {
  return <SectionBody {...props} className="section" />;
}

/** A headed region on a paper-2 surface: forms, notes, grouped facts. Never nest a Panel in a Panel. */
export function Panel(props: SectionProps) {
  return <SectionBody {...props} className="panel" />;
}

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

/** One filled primary per page; secondary is the default. Anchors can use className="btn btn-primary". */
export function Button({ variant = "secondary", className, type = "button", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button type={type} className={`btn btn-${variant}${className ? ` ${className}` : ""}`} {...rest} />;
}

/** Sentence-case column heads, hairline rows, tabular numerals. Put thead/tbody inside. */
export function DataTable({ label, sticky, children }: { label: string; sticky?: boolean; children: ReactNode }) {
  return (
    <div className={`tablewrap${sticky ? " is-sticky" : ""}`} role="region" aria-label={label} tabIndex={0}>
      <table className="data">{children}</table>
    </div>
  );
}

/** A filter row above a table: inputs, selects, chips, then the count. */
export function Toolbar({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="toolbar" role="group" aria-label={label}>
      {children}
    </div>
  );
}

/** Label and value pairs as a description list. */
export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="kv">
      {items.map((i) => (
        <div key={i.label}>
          <dt>{i.label}</dt>
          <dd>{i.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A timestamp rendered in the viewer's zone, with the raw instant on hover. */
export function Ts({ iso }: { iso: string | null | undefined }) {
  const me = useMe();
  return (
    <time className="num" dateTime={iso ?? undefined} title={iso ?? undefined}>
      {formatTs(iso, me.timezone)}
    </time>
  );
}

/** Label above, optional hint, and an error that replaces the hint. The control is the single child element. */
export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  const helpId = `${id}-help`;
  const help = error || hint;
  let control = children;
  let controlId = id;
  if (isValidElement<Record<string, unknown>>(children)) {
    controlId = (children.props.id as string | undefined) ?? id;
    control = cloneElement(children as ReactElement<Record<string, unknown>>, {
      id: controlId,
      ...(help ? { "aria-describedby": helpId } : {}),
      ...(error ? { "aria-invalid": true } : {}),
      ...(required ? { "aria-required": true } : {}),
    });
  }
  return (
    <div className="field">
      <label htmlFor={controlId}>
        {label}
        {required && <span className="field-req"> (required)</span>}
      </label>
      {control}
      {help && (
        <small id={helpId} className={`field-help${error ? " is-error" : ""}`} role={error ? "alert" : undefined}>
          {help}
        </small>
      )}
    </div>
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

export interface Stat {
  label: string;
  value: number | string;
  /** Marks a count that needs someone to act. Zero never carries a tone. */
  tone?: "bad" | "warn";
}

/** The page's focal point: a few real counts as large Geist Mono numerals. `headline` is the same facts in one sentence. */
export function StatStrip({ label, headline, items }: { label: string; headline?: ReactNode; items: Stat[] }) {
  return (
    <section className="stats" aria-label={label}>
      {headline && <p className="stats-headline">{headline}</p>}
      <dl className="stats-row">
        {items.map((i) => {
          const live = typeof i.value === "number" ? i.value > 0 : true;
          return (
            <div key={i.label} className={`stat${i.tone && live ? ` stat-${i.tone}` : ""}${typeof i.value === "number" && i.value === 0 ? " stat-zero" : ""}`}>
              <dd className="stat-n">{i.value}</dd>
              <dt className="stat-l">{i.label}</dt>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
