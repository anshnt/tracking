/** "1 blocker", "3 devices": a count with its noun. */
export function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Joins the non-empty parts into one sentence: "3 devices unknown, 1 failing check". Falls back when all are empty. */
export function headline(parts: (string | null | false)[], none: string): string {
  const kept = parts.filter((p): p is string => Boolean(p));
  return kept.length ? kept.join(", ") : none;
}
