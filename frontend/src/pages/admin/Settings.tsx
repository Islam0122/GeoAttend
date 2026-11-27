import { useEffect, useState } from "react";
import { useGet, useSend } from "@/api/hooks";
import type { Organization, Settings as S } from "@/api/types";
import { Field, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Switch } from "@/components/ui/misc";
import { titleCase } from "@/lib/format";

const NUM: [keyof S, string, string][] = [
  ["default_radius_m", "Default geofence radius (m)", "Applied to new offices"],
  ["default_max_accuracy_m", "Default max GPS accuracy (m)", "Applied to new offices"],
  ["max_reasonable_accuracy_m", "Reject accuracy worse than (m)", "Hard sanity limit for any reading"],
  ["pre_shift_tracking_minutes", "Check-in opens before shift (min)", ""],
  ["post_shift_tracking_minutes", "Window closes after shift (min)", "Location is never accepted outside this window"],
  ["temporary_exit_max_minutes", "Max break / temporary exit (min)", ""],
  ["half_day_ratio", "Half-day threshold (0–1)", "Share of scheduled time"],
  ["missing_checkin_after_minutes", "Missing check-in alert after (min)", ""],
  ["checkin_reminder_minutes", "Check-in reminder before shift (min)", "0 disables reminders"],
  ["location_retention_days", "Delete raw coordinates after (days)", "Data retention policy"],
  ["max_speed_mps", "Suspicious speed (m/s)", "Impossible-jump detection"],
];
const AUTO_BOOL: [keyof S, string, string][] = [
  ["automatic_detection_enabled", "Automatic presence detection", "Location is checked while the Attendance screen is open (also feeds Monitoring in Manual mode)."],
  ["automatic_checkin_enabled", "Automatic check-in", "Start the work session after the entry is confirmed."],
  ["automatic_checkout_enabled", "Automatic check-out / temporary exits", "Confirmed exits create temporary exits; leaving after (shift end − checkout grace) completes the day."],
  ["automatic_resume_enabled", "Automatic session resume", "Returning within the maximum absence resumes the same session."],
  ["allow_unscheduled_attendance", "Allow unscheduled attendance", "Create UNSCHEDULED attendance on days without a shift (location is then checked all day while the screen is open)."],
  ["require_registered_device", "Require registered device", "Browsers register automatically on sign-in."],
  ["count_temporary_exit_as_work", "Count temporary exits as working time", "Off: exits longer than the grace period are not paid time. Presence is always reported separately."],
];
const AUTO_NUM: [keyof S, string, string][] = [
  ["presence_interval_seconds", "Presence refresh interval (s)", "Default 30"],
  ["default_max_accuracy_m", "GPS accuracy threshold (m)", "Default for new offices; each office can override"],
  ["entry_confirmation_count", "Entry confirmation readings", "Default 2"],
  ["exit_confirmation_count", "Exit confirmation readings", "Default 3"],
  ["presence_stale_seconds", "GPS stale threshold (s)", "Default 120"],
  ["temporary_exit_grace_minutes", "Temporary exit grace (min)", "Short exits up to this are counted as work. Default 10"],
  ["temporary_exit_max_minutes", "Maximum absence (min)", "Not back by then: the session ends at the exit time"],
  ["checkout_grace_minutes", "Checkout grace before shift end (min)", "Leaving after shift end − grace completes the day"],
  ["automatic_checkout_timeout_minutes", "Automatic closure timeout (min)", "After shift end; closes at the last validated presence (to confirm)"],
  ["entry_buffer_m", "Entry hysteresis (m)", "Must be this far inside the radius to confirm entry"],
  ["exit_buffer_m", "Exit hysteresis (m)", "Must be this far outside the radius to confirm exit"],
];
const BOOL: [keyof S, string, string][] = [
  ["checkout_requires_geofence", "Check-out must be inside the geofence", "Off: employees can check out anywhere (location is still recorded)."],
  ["count_temporary_exit_as_work", "Count temporary exits as working time", ""],
  ["require_registered_device", "Require a registered device/browser", "Each browser registers automatically on sign-in."],
];

export function Settings() {
  const org = useGet<Organization>("/organizations/current/");
  const st = useGet<S>("/organizations/current/settings/");
  const [o, setO] = useState<Partial<Organization>>({});
  const [v, setV] = useState<Partial<S>>({});
  useEffect(() => { if (org.data) setO(org.data); }, [org.data]);
  useEffect(() => { if (st.data) setV(st.data); }, [st.data]);
  const saveOrg = useSend<object>("PATCH", "/organizations/current/", ["/organizations", "/auth/me"], "Organization saved");
  const saveSt = useSend<object>("PATCH", "/organizations/current/settings/", ["/organizations", "/attendance/policy"], "Policy saved");

  return (
    <>
      <PageHeader title="Organization settings" />
      <QueryState isLoading={org.isLoading || st.isLoading} error={org.error || st.error}>
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Organization</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Field label="Name"><Input value={o.name ?? ""} onChange={(e) => setO({ ...o, name: e.target.value })} /></Field>
              <Field label="Timezone (IANA)" hint="Used for schedules, reports and automation unless an office overrides it."><Input value={o.timezone ?? ""} onChange={(e) => setO({ ...o, timezone: e.target.value })} /></Field>
              <Field label="Company type"><NativeSelect value={o.company_type ?? "OTHER"} onChange={(e) => setO({ ...o, company_type: e.target.value })}>
                {["IT", "EDUCATION", "SMALL_BUSINESS", "MEDIUM_BUSINESS", "ENTERPRISE", "OTHER"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}</NativeSelect></Field>
              <Button onClick={() => saveOrg.mutate({ name: o.name, timezone: o.timezone, company_type: o.company_type })} disabled={saveOrg.isPending}>Save</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Attendance policy</CardTitle><CardDescription>How validated check-ins become attendance.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              <Field label="Confirmation policy" hint="Automatic: confirmed after server validation (employees can dispute). Manager approval: each check-in waits for a manager.">
                <NativeSelect value={v.confirmation_policy} onChange={(e) => setV({ ...v, confirmation_policy: e.target.value as S["confirmation_policy"] })}>
                  <option value="AUTOMATIC">Automatic (recommended)</option><option value="EMPLOYEE_CONFIRMATION">Employee confirmation</option><option value="MANAGER_APPROVAL">Manager approval</option>
                </NativeSelect></Field>
              {BOOL.map(([k, l, h]) => (
                <div key={k} className="flex items-start justify-between gap-4 rounded-lg border p-3">
                  <div><div className="text-sm font-medium">{l}</div>{h && <div className="text-xs text-muted-foreground">{h}</div>}</div>
                  <Switch checked={!!v[k]} onCheckedChange={(c) => setV({ ...v, [k]: c })} aria-label={l} />
                </div>
              ))}
            </CardContent>
          </Card>
          <Card className="lg:col-span-2" data-testid="attendance-policy">
            <CardHeader><CardTitle>Attendance mode</CardTitle>
              <CardDescription>Manual: employees press Check in / Check out. Automatic: the server records work time from confirmed office entries and exits while the Attendance screen is open. Hybrid: automatic detection plus manual actions.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Attendance mode">
                {(["MANUAL", "AUTOMATIC", "HYBRID"] as const).map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={v.attendance_mode === m} onClick={() => setV({ ...v, attendance_mode: m })}
                    className={`rounded-lg border p-3 text-left text-sm cursor-pointer ${v.attendance_mode === m ? "border-primary bg-primary/8 ring-2 ring-primary/20" : "hover:bg-muted"}`}>
                    <div className="font-semibold">{titleCase(m)} attendance</div>
                    <div className="text-xs text-muted-foreground">{m === "MANUAL" ? "Check-in / Check-out buttons" : m === "AUTOMATIC" ? "No buttons; fully automatic" : "Automatic + manual buttons"}</div>
                  </button>
                ))}
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {AUTO_BOOL.map(([k, l, h]) => (
                  <div key={k} className="flex items-start justify-between gap-4 rounded-lg border p-3">
                    <div><div className="text-sm font-medium">{l}</div><div className="text-xs text-muted-foreground">{h}</div></div>
                    <Switch checked={!!v[k]} onCheckedChange={(c) => setV({ ...v, [k]: c })} aria-label={l} />
                  </div>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {AUTO_NUM.map(([k, l, h]) => <Field key={k} label={l} hint={h}><Input type="number" step="any" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} aria-label={l} /></Field>)}
              </div>
              <p className="text-xs text-muted-foreground">Geofence radius is configured per office under Offices & geofences. Browsers cannot track a closed tab: automatic attendance works while employees keep the Attendance screen open.</p>
              <Button onClick={() => saveSt.mutate(v)} disabled={saveSt.isPending}>Save attendance policy</Button>
            </CardContent>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>GPS & privacy thresholds</CardTitle></CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {NUM.map(([k, l, h]) => <Field key={k} label={l} hint={h}><Input type="number" step="any" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} /></Field>)}
              </div>
              <Button className="mt-4" onClick={() => { const { ...body } = v; saveSt.mutate(body); }} disabled={saveSt.isPending}>Save policy</Button>
            </CardContent>
          </Card>
        </div>
      </QueryState>
    </>
  );
}
