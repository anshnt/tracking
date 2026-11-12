import { get, post } from "../api/client";
import type { CollectionPolicy } from "../api/types";
import { Async, Button, EmptyState, NoticeCard, Page, Result, StatusPill, Ts, useAction, useLoad, useMe } from "../components/ui";
import { collectionDefault } from "./Records";
import "../styles/employee.css";

export function Home() {
  const me = useMe();
  const load = useLoad(() => get<CollectionPolicy>("/me/collection-policy"));
  const act = useAction();

  return (
    <Page title={`Hello, ${me.display_name}`} lead="This portal records only what the notice below lists.">
      <Async
        load={load}
        skeleton="block"
        isEmpty={(d) => !d.policy}
        empty={
          <EmptyState title="No monitoring notice applies to you yet">
            Your administrator assigns the notice. Ask them for the contact person if you expected one.
          </EmptyState>
        }
      >
        {({ policy, categories }) => {
          if (!policy) return null;
          const isNever = (c: { default: string; visible_to: string }) => c.default === "off" || c.default === "excluded" || /^(not|never) collected/i.test(c.visible_to);
          const recorded = categories.filter((c) => !isNever(c));
          const never = categories.filter(isNever);
          return (
            <NoticeCard
              title="Monitoring and collection notice"
              status={
                policy.acknowledged_at ? (
                  <StatusPill tone="ok">Acknowledged</StatusPill>
                ) : (
                  <StatusPill tone="warn">Needs your acknowledgement</StatusPill>
                )
              }
              meta={
                <>
                  {policy.name}, version <span className="mono">{policy.version}</span>. In force since <Ts iso={policy.activates_at} />
                  {policy.expires_at && (
                    <>
                      , until <Ts iso={policy.expires_at} />
                    </>
                  )}
                  . {policy.is_exception && <StatusPill tone="warn">Exception for you</StatusPill>}
                </>
              }
              recorded={recorded.map((c) => (
                <span className="e-sig" key={c.signal}>
                  <strong>{c.signal}</strong>
                  <span>
                    {collectionDefault(c.default)}. Seen by {c.visible_to}.
                  </span>
                </span>
              ))}
              never={never.map((c) => (
                <span className="e-sig" key={c.signal}>
                  <strong>{c.signal}</strong>
                </span>
              ))}
              pending={!policy.acknowledged_at}
              contact={policy.contact ?? "not set, ask your administrator"}
              hash={policy.content_hash}
              action={
                policy.acknowledged_at ? (
                  <span className="e-ack">
                    You acknowledged this notice on <Ts iso={policy.acknowledged_at} />
                  </span>
                ) : (
                  <>
                    <Button
                      variant="primary"
                      disabled={act.busy}
                      onClick={async () => {
                        if (await act.run(() => post("/me/notice-acknowledgements", { policy_version_id: policy.id }), "Notice acknowledged.")) load.reload();
                      }}
                    >
                      I have read this notice
                    </Button>
                    <Result ok={act.ok} err={act.err} />
                  </>
                )
              }
            >
              {policy.notice_text ?? "No notice text was provided."}
            </NoticeCard>
          );
        }}
      </Async>
    </Page>
  );
}
