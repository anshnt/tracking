import { useEffect, useState } from "react";
import type { ReactNode } from "react";

/** True only once `active` has held for `ms`, so fast responses never flash a skeleton. */
export function useDelayed(active: boolean, ms = 150): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!active) {
      setOn(false);
      return;
    }
    const t = setTimeout(() => setOn(true), ms);
    return () => clearTimeout(t);
  }, [active, ms]);
  return on;
}

export type SkeletonShape = "rows" | "lines" | "block";

/** Placeholder in the shape of what is loading: table rows, text lines, or one panel. */
export function Skeleton({ shape = "rows", rows = 4, label = "Loading" }: { shape?: SkeletonShape; rows?: number; label?: string }) {
  const n = shape === "block" ? 1 : rows;
  return (
    <div className={`skeleton sk-${shape}`} role="status">
      <span className="visually-hidden">{label}</span>
      <div aria-hidden="true" className="sk-body">
        {Array.from({ length: n }, (_, i) =>
          shape === "rows" ? (
            <div className="sk-row" key={i}>
              <i />
              <i />
              <i />
              <i />
            </div>
          ) : (
            <i className="sk-line" key={i} />
          ),
        )}
      </div>
    </div>
  );
}

/** What belongs here, and the one action that fills it. */
export function EmptyState({ title, children, action }: { title?: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state">
      {title && <p className="state-title">{title}</p>}
      {children && <p className="state-body">{children}</p>}
      {action}
    </div>
  );
}

/** What broke and what to do about it. */
export function ErrorState({ title = "This could not be loaded", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">{title}</p>
      <p className="state-body">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
