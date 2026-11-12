import { useId } from "react";
import type { ReactNode } from "react";
import { IdCell } from "./IdCell";

/**
 * The monitoring notice: the object this portal is known by. It leads with what is never recorded
 * (a dark panel), then what is, then the full text on request. Version, contact, hash and the
 * acknowledgement sit in one quiet footer row. Presentational only; the page owns the data.
 */
export function NoticeCard({
  title,
  status,
  meta,
  recorded,
  never,
  children,
  contact,
  hash,
  action,
  pending,
}: {
  title: string;
  status?: ReactNode;
  meta?: ReactNode;
  recorded?: ReactNode[];
  never?: ReactNode[];
  children?: ReactNode;
  contact?: ReactNode;
  hash?: string;
  action?: ReactNode;
  /** True while the acknowledgement is still owed: the footer becomes a visible bar. */
  pending?: boolean;
}) {
  const id = useId();
  return (
    <article className="notice" aria-labelledby={`${id}-t`}>
      <header className="notice-head">
        <h2 id={`${id}-t`}>{title}</h2>
        {status}
      </header>

      {never !== undefined && (
        <section className="notice-never" aria-labelledby={`${id}-never`}>
          <h3 id={`${id}-never`}>What is never recorded</h3>
          {never.length > 0 ? (
            <ul>
              {never.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          ) : (
            <p>Nothing is listed.</p>
          )}
        </section>
      )}

      {recorded !== undefined && (
        <section className="notice-rec" aria-labelledby={`${id}-rec`}>
          <h3 id={`${id}-rec`}>What is recorded</h3>
          {recorded.length > 0 ? (
            <ul>
              {recorded.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          ) : (
            <p className="meta">Nothing is listed.</p>
          )}
        </section>
      )}

      {children && (
        <details className="notice-full">
          <summary>Read the full notice text</summary>
          <div className="notice-text">{children}</div>
        </details>
      )}

      <footer className={`notice-foot${pending ? " is-pending" : ""}`}>
        {meta && <p className="notice-meta">{meta}</p>}
        <dl className="notice-facts">
          {contact !== undefined && (
            <div>
              <dt>Questions or objections</dt>
              <dd>{contact}</dd>
            </div>
          )}
          {hash && (
            <div>
              <dt>Content hash</dt>
              <dd>
                <IdCell id={hash} head={12} />
              </dd>
            </div>
          )}
        </dl>
        {action && <div className="notice-ack">{action}</div>}
      </footer>
    </article>
  );
}
