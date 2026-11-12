import { get, post } from "../api/client";
import type { CollectionPolicy } from "../api/types";
import { Async, Empty, Page, Result, Tag, Ts, useAction, useLoad, useMe } from "../components/ui";

export function Home() {
  const me = useMe();
  const load = useLoad(() => get<CollectionPolicy>("/me/collection-policy"));
  const act = useAction();

  return (
    <Page title={`Hello, ${me.display_name}`} lead="This portal records only what the notice below lists.">
      <Async load={load}>
        {({ policy }) =>
          !policy ? (
            <Empty>No monitoring notice applies to you yet. Ask your administrator for the contact person.</Empty>
          ) : (
            <article className="card" aria-labelledby="notice-h">
              <h2 id="notice-h">Monitoring and collection notice</h2>
              <p className="meta">
                {policy.name}, version {policy.version}. In force since <Ts iso={policy.activates_at} />
                {policy.expires_at && (
                  <>
                    , until <Ts iso={policy.expires_at} />
                  </>
                )}
                . {policy.is_exception && <Tag tone="warn">Exception for you</Tag>}
              </p>
              <p className="prose">{policy.notice_text ?? "No notice text was provided."}</p>
              <p>
                Questions or objections: <strong>{policy.contact ?? "not set, ask your administrator"}</strong>
              </p>
              <p className="meta mono">Content hash {policy.content_hash.slice(0, 16)}</p>
              {policy.acknowledged_at ? (
                <p>
                  <Tag tone="ok" mark={"✓"}>
                    Acknowledged
                  </Tag>{" "}
                  <Ts iso={policy.acknowledged_at} />
                </p>
              ) : (
                <>
                  <button
                    type="button"
                    className="primary"
                    disabled={act.busy}
                    onClick={async () => {
                      if (await act.run(() => post("/me/notice-acknowledgements", { policy_version_id: policy.id }), "Notice acknowledged.")) load.reload();
                    }}
                  >
                    I have read this notice
                  </button>
                  <Result ok={act.ok} err={act.err} />
                </>
              )}
            </article>
          )
        }
      </Async>
    </Page>
  );
}
