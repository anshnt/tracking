import { useState } from "react";

/** An ID that stays one short line; click copies the whole value. */
export function IdCell({ id, head = 8 }: { id: string; head?: number }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="idcell mono"
      title={id}
      aria-label={`Copy ID ${id}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(id);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked: the full value is in the title */
        }
      }}
    >
      {id.length > head + 1 ? `${id.slice(0, head)}...` : id}
      <span className="idcell-note" aria-live="polite">
        {done ? "Copied" : ""}
      </span>
    </button>
  );
}
