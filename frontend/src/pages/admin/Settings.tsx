import { useEffect, useState } from "react";
import { useGet, useSend } from "@/api/hooks";
import type { Organization, Settings as S } from "@/api/types";
import { Field, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Switch } from "@/components/ui/misc";
import { titleCase } from "@/lib/format";
import { msg, t } from "@/i18n";

const NUM: [keyof S, string, string][] = [
  ["default_radius_m", msg("Default geofence radius (m)"), msg("Applied to new offices")],
  ["default_max_accuracy_m", msg("Default max GPS accuracy (m)"), msg("Applied to new offices")],
  ["max_reasonable_accuracy_m", msg("Reject accuracy worse than (m)"), msg("Hard sanity limit for any reading")],
  ["pre_shift_tracking_minutes", msg("Check-in opens before shift (min)"), ""],
  ["post_shift_tracking_minutes", msg("Window closes after shift (min)"), msg("Location is never accepted outside this window")],
  ["temporary_exit_max_minutes", msg("Max break / temporary exit (min)"), ""],
  ["half_day_ratio", msg("Half-day threshold (0–1)"), msg("Share of scheduled time")],
  ["missing_checkin_after_minutes", msg("Missing check-in alert after (min)"), ""],
  ["checkin_reminder_minutes", msg("Check-in reminder before shift (min)"), msg("0 disables reminders")],
  ["location_retention_days", msg("Delete raw coordinates after (days)"), msg("Data retention policy")],
  ["max_speed_mps", msg("Suspicious speed (m/s)"), msg("Impossible-jump detection")],
];
const AUTO_BOOL: [keyof S, string, string][] = [
  ["automatic_detection_enabled", msg("Automatic presence detection"), msg("Location is checked while the Attendance screen is open (also feeds Monitoring in Manual mode).")],
  ["automatic_checkin_enabled", msg("Automatic check-in"), msg("Start the work session after the entry is confirmed.")],
  ["automatic_checkout_enabled", msg("Automatic check-out / temporary exits"), msg("Confirmed exits create temporary exits; leaving after (shift end − checkout grace) completes the day.")],
  ["automatic_resume_enabled", msg("Automatic session resume"), msg("Returning within the maximum absence resumes the same session.")],
  ["allow_unscheduled_attendance", msg("Allow unscheduled attendance"), msg("Create UNSCHEDULED attendance on days without a shift (location is then checked all day while the screen is open).")],
  ["require_registered_device", msg("Require registered device"), msg("Browsers register automatically on sign-in.")],
  ["count_temporary_exit_as_work", msg("Count temporary exits as working time"), msg("Off: exits longer than the grace period are not paid time. Presence is always reported separately.")],
];
const AUTO_NUM: [keyof S, string, string][] = [
  ["presence_interval_seconds", msg("Presence refresh interval (s)"), msg("Default 30")],
  ["default_max_accuracy_m", msg("GPS accuracy threshold (m)"), msg("Default for new offices; each office can override")],
  ["entry_confirmation_count", msg("Entry confirmation readings"), msg("Default 2")],
  ["exit_confirmation_count", msg("Exit confirmation readings"), msg("Default 3")],
  ["presence_stale_seconds", msg("GPS stale threshold (s)"), msg("Default 120")],
  ["temporary_exit_grace_minutes", msg("Temporary exit grace (min)"), msg("Short exits up to this are counted as work. Default 10")],
  ["temporary_exit_max_minutes", msg("Maximum absence (min)"), msg("Not back by then: the session ends at the exit time")],
  ["checkout_grace_minutes", msg("Checkout grace before shift end (min)"), msg("Leaving after shift end − grace completes the day")],
  ["automatic_checkout_timeout_minutes", msg("Automatic closure timeout (min)"), msg("After shift end; closes at the last validated presence (to confirm)")],
  ["entry_buffer_m", msg("Entry hysteresis (m)"), msg("Must be this far inside the radius to confirm entry")],
  ["exit_buffer_m", msg("Exit hysteresis (m)"), msg("Must be this far outside the radius to confirm exit")],
];
const BOOL: [keyof S, string, string][] = [
  ["checkout_requires_geofence", msg("Check-out must be inside the geofence"), msg("Off: employees can check out anywhere (location is still recorded).")],
  ["count_temporary_exit_as_work", msg("Count temporary exits as working time"), ""],
  ["require_registered_device", msg("Require a registered device/browser"), msg("Each browser registers automatically on sign-in.")],
];

export function Settings() {
  const org = useGet<Organization>("/organizations/current/");
  const st = useGet<S>("/organizations/current/settings/");
  const [o, setO] = useState<Partial<Organization>>({});
  const [v, setV] = useState<Partial<S>>({});
  useEffect(() => { if (org.data) setO(org.data); }, [org.data]);
  useEffect(() => { if (st.data) setV(st.data); }, [st.data]);
  const saveOrg = useSend<object>("PATCH", "/organizations/current/", ["/organizations", "/auth/me"], t("Organization saved"));
  const saveSt = useSend<object>("PATCH", "/organizations/current/settings/", ["/organizations", "/attendance/policy"], t("Policy saved"));

  return (
    <>
      <PageHeader title={t("Organization settings")} />
      <QueryState isLoading={org.isLoading || st.isLoading} error={org.error || st.error}>
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>{t("Organization")}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Field label={t("Name")}><Input value={o.name ?? ""} onChange={(e) => setO({ ...o, name: e.target.value })} /></Field>
              <Field label={t("Timezone (IANA)")} hint={t("Used for schedules, reports and automation unless an office overrides it.")}><Input value={o.timezone ?? ""} onChange={(e) => setO({ ...o, timezone: e.target.value })} /></Field>
              <Field label={t("Company type")}><NativeSelect value={o.company_type ?? "OTHER"} onChange={(e) => setO({ ...o, company_type: e.target.value })}>
                {["IT", "EDUCATION", "SMALL_BUSINESS", "MEDIUM_BUSINESS", "ENTERPRISE", "OTHER"].map((x) => <option key={x} value={x}>{titleCase(x)}</option>)}</NativeSelect></Field>
              <Button onClick={() => saveOrg.mutate({ name: o.name, timezone: o.timezone, company_type: o.company_type })} disabled={saveOrg.isPending}>{t("Save")}</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>{t("Attendance policy")}</CardTitle><CardDescription>{t("How validated check-ins become attendance.")}</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              <Field label={t("Confirmation policy")} hint={t("Automatic: confirmed after server validation (employees can dispute). Manager approval: each check-in waits for a manager.")}>
                <NativeSelect value={v.confirmation_policy} onChange={(e) => setV({ ...v, confirmation_policy: e.target.value as S["confirmation_policy"] })}>
                  <option value="AUTOMATIC">{t("Automatic (recommended)")}</option><option value="EMPLOYEE_CONFIRMATION">{t("Employee confirmation")}</option><option value="MANAGER_APPROVAL">{t("Manager approval")}</option>
                </NativeSelect></Field>
              {BOOL.map(([k, l, h]) => (
                <div key={k} className="flex items-start justify-between gap-4 rounded-lg border p-3">
                  <div><div className="text-sm font-medium">{t(l)}</div>{h && <div className="text-xs text-muted-foreground">{t(h)}</div>}</div>
                  <Switch checked={!!v[k]} onCheckedChange={(c) => setV({ ...v, [k]: c })} aria-label={t(l)} />
                </div>
              ))}
            </CardContent>
          </Card>
          <Card className="lg:col-span-2" data-testid="attendance-policy">
            <CardHeader><CardTitle>{t("Attendance mode")}</CardTitle>
              <CardDescription>{t("Manual: employees press Check in / Check out. Automatic: the server records work time from confirmed office entries and exits while the Attendance screen is open. Hybrid: automatic detection plus manual actions.")}</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label={t("Attendance mode")}>
                {(["MANUAL", "AUTOMATIC", "HYBRID"] as const).map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={v.attendance_mode === m} onClick={() => setV({ ...v, attendance_mode: m })}
                    className={`rounded-lg border p-3 text-left text-sm cursor-pointer ${v.attendance_mode === m ? "border-primary bg-primary/8 ring-2 ring-primary/20" : "hover:bg-muted"}`}>
                    <div className="font-semibold">{m === "MANUAL" ? t("Manual attendance") : m === "AUTOMATIC" ? t("Automatic attendance") : t("Hybrid attendance")}</div>
                    <div className="text-xs text-muted-foreground">{m === "MANUAL" ? t("Check-in / Check-out buttons") : m === "AUTOMATIC" ? t("No buttons; fully automatic") : t("Automatic + manual buttons")}</div>
                  </button>
                ))}
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {AUTO_BOOL.map(([k, l, h]) => (
                  <div key={k} className="flex items-start justify-between gap-4 rounded-lg border p-3">
                    <div><div className="text-sm font-medium">{t(l)}</div><div className="text-xs text-muted-foreground">{t(h)}</div></div>
                    <Switch checked={!!v[k]} onCheckedChange={(c) => setV({ ...v, [k]: c })} aria-label={t(l)} />
                  </div>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {AUTO_NUM.map(([k, l, h]) => <Field key={k} label={t(l)} hint={h && t(h)}><Input type="number" step="any" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} aria-label={t(l)} /></Field>)}
              </div>
              <p className="text-xs text-muted-foreground">{t("Geofence radius is configured per office under Offices & geofences. Browsers cannot track a closed tab: automatic attendance works while employees keep the Attendance screen open.")}</p>
              <Button onClick={() => saveSt.mutate(v)} disabled={saveSt.isPending}>{t("Save attendance policy")}</Button>
            </CardContent>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>{t("GPS & privacy thresholds")}</CardTitle></CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {NUM.map(([k, l, h]) => <Field key={k} label={t(l)} hint={h && t(h)}><Input type="number" step="any" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} /></Field>)}
              </div>
              <Button className="mt-4" onClick={() => { const { ...body } = v; saveSt.mutate(body); }} disabled={saveSt.isPending}>{t("Save policy")}</Button>
            </CardContent>
          </Card>
        </div>
      </QueryState>
    </>
  );
}
