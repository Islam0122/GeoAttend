export function fmtTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
}
export function fmtDate(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: iso.length === 10 ? "UTC" : tz }).format(d);
}
export function fmtDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: tz }).format(new Date(iso));
}
export function fmtMinutes(m: number | null | undefined): string {
  if (!m) return "0m";
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h ? `${h}h ${String(r).padStart(2, "0")}m` : `${r}m`;
}
export function fmtHours(m: number): string {
  return `${(m / 60).toFixed(1)}h`;
}
export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
export function todayIn(tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export function greeting(tz?: string): string {
  const h = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: tz }).format(new Date()));
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
export function titleCase(s: string): string {
  return s.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export const STATUS_LABEL: Record<string, string> = {
  PRESENT: "Present", LATE: "Late", ABSENT: "Absent", HALF_DAY: "Half day", INCOMPLETE: "Incomplete", ON_LEAVE: "On leave",
  PENDING_CONFIRMATION: "Pending approval", LOCATION_UNAVAILABLE: "Location unavailable", NOT_CHECKED_IN: "Not checked in",
  UNSCHEDULED: "Unscheduled", NO_SHIFT: "No shift",
};
export const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  PRESENT: "success", LATE: "warning", ABSENT: "danger", HALF_DAY: "warning", INCOMPLETE: "warning", ON_LEAVE: "info",
  PENDING_CONFIRMATION: "info", LOCATION_UNAVAILABLE: "neutral", NOT_CHECKED_IN: "neutral", UNSCHEDULED: "info", NO_SHIFT: "neutral",
};
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
