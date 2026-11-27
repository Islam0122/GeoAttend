import { intlLocale, msg, t, translated } from "@/i18n";

export function fmtTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(intlLocale(), { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
}
export function fmtDate(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat(intlLocale(), { weekday: "short", month: "short", day: "numeric", timeZone: iso.length === 10 ? "UTC" : tz }).format(d);
}
export function fmtDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(intlLocale(), { dateStyle: "medium", timeStyle: "short", timeZone: tz }).format(new Date(iso));
}
export function fmtMinutes(m: number | null | undefined): string {
  if (!m) return t("{m}m", { m: 0 });
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h ? t("{h}h {m}m", { h, m: String(r).padStart(2, "0") }) : t("{m}m", { m: r });
}
export function fmtHours(m: number): string {
  return t("{h}h", { h: (m / 60).toFixed(1) });
}
export function ago(iso: string | null | undefined): string {
  if (!iso) return t("never");
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return t("just now");
  if (s < 3600) return t("{n} min ago", { n: Math.floor(s / 60) });
  if (s < 86400) return t("{n} h ago", { n: Math.floor(s / 3600) });
  return t("{n} d ago", { n: Math.floor(s / 86400) });
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
  return h < 12 ? t("Good morning") : h < 18 ? t("Good afternoon") : t("Good evening");
}
/** Human label for an API enum value (e.g. "MISSING_CHECK_IN" → "Missing check in"), translated. */
export function titleCase(s: string): string {
  return t(s.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()));
}

/** Distance / accuracy in metres. */
export function fmtMeters(n: number, plusMinus = false): string {
  return t(plusMinus ? "±{n} m" : "{n} m", { n: Math.round(n) });
}

export const STATUS_LABEL: Record<string, string> = translated({
  PRESENT: msg("Present"), LATE: msg("Late"), ABSENT: msg("Absent"), HALF_DAY: msg("Half day"), INCOMPLETE: msg("Incomplete"), ON_LEAVE: msg("On leave"),
  PENDING_CONFIRMATION: msg("Pending approval"), LOCATION_UNAVAILABLE: msg("Location unavailable"), NOT_CHECKED_IN: msg("Not checked in"),
  UNSCHEDULED: msg("Unscheduled"), NO_SHIFT: msg("No shift"),
} as Record<string, string>);
export const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  PRESENT: "success", LATE: "warning", ABSENT: "danger", HALF_DAY: "warning", INCOMPLETE: "warning", ON_LEAVE: "info",
  PENDING_CONFIRMATION: "info", LOCATION_UNAVAILABLE: "neutral", NOT_CHECKED_IN: "neutral", UNSCHEDULED: "info", NO_SHIFT: "neutral",
};
export const WEEKDAYS: string[] = translated([msg("Mon"), msg("Tue"), msg("Wed"), msg("Thu"), msg("Fri"), msg("Sat"), msg("Sun")]);
