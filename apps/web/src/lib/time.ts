/** Format an ISO instant in the given IANA zone, always showing the zone so readers can trust it. */
export function formatTs(iso: string | null | undefined, tz: string): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(undefined, {
      // dateStyle/timeStyle cannot be combined with timeZoneName (Intl throws), so spell the fields out.
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: tz,
      timeZoneName: "short",
    }).format(d);
  } catch {
    return d.toISOString();
  }
}

export function ageText(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function todayIn(tz: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

export function newKey(): string {
  return crypto.randomUUID();
}
