/**
 * Display helpers. The UI renders backend state faithfully: values the backend
 * intentionally leaves null render as an explicit unknown dash ("—").
 */

export function unknown(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return DATE_TIME_FORMAT.format(date);
}

export function shortId(uuid: string): string {
  return uuid.slice(0, 8);
}