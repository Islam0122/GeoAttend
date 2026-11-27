import { CalendarClock, Clock, Coffee, Timer } from "lucide-react";
import { useGet } from "@/api/hooks";
import type { Today } from "@/api/types";
import { PageHeader, QueryState, StatCard, StatusBadge } from "@/components/common";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { AutomaticAttendancePanel } from "@/features/automatic/AutomaticAttendancePanel";
import { useAttendancePolicy } from "@/features/automatic/useAutomaticAttendance";
import { usePresenceReporter } from "@/features/automatic/usePresenceReporter";
import { CheckInPanel } from "@/features/checkin/CheckInPanel";
import { fmtMinutes, fmtTime, greeting, titleCase } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useQueueStore } from "@/stores/queue";
import { msg, t } from "@/i18n";

export function MyDashboard() {
  const me = useAuthStore((s) => s.me)!;
  const q = useGet<Today>("/attendance/today/", undefined, { refetchInterval: 60_000 });
  const pending = useQueueStore((s) => s.pending);
  const policy = useAttendancePolicy().data;
  const reporter = usePresenceReporter({
    enabled: !!policy?.automatic_detection_enabled && !!q.data?.actions.consent_granted && !!q.data?.actions.window_open,
    intervalSeconds: policy?.presence_interval_seconds ?? 30,
  });
  const automatic = policy && policy.attendance_mode !== "MANUAL";
  const td = q.data;
  const tz = td?.shift?.timezone ?? me.organization_timezone;
  const r = td?.record;
  return (
    <>
      <PageHeader title={`${greeting(tz)}, ${me.full_name.split(" ")[0]}!`}
        description={td?.shift ? t(new Date(td.shift.start) > new Date() ? msg("Your shift starts at {start} and ends at {end}.") : msg("Your shift started at {start} and ends at {end}."), { start: fmtTime(td.shift.start, tz), end: fmtTime(td.shift.end, tz) }) : t("You have no shift scheduled today.")} />
      <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
        {td && (
          <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
            <div className="space-y-4">
              {pending.length > 0 && <Alert tone="info" title={t("{n} offline action(s) pending", { n: pending.length })}>{t("They'll be validated by the server automatically when you're online.")}</Alert>}
              {automatic ? <AutomaticAttendancePanel today={td} /> : <CheckInPanel today={td} onFix={reporter} />}
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <StatCard label={t("Status")} value={r ? <StatusBadge status={r.status} /> : <span className="text-base text-muted-foreground">{t("Not checked in")}</span>} icon={<Clock />} />
                <StatCard label={t("Worked today")} value={fmtMinutes(r?.worked_minutes)} icon={<Timer />} accent />
                <StatCard label={t("Checked in")} value={fmtTime(r?.actual_check_in, tz)} hint={r?.late_minutes ? t("{n} min late", { n: r.late_minutes }) : r?.actual_check_in ? t("On time") : undefined} icon={<CalendarClock />} />
                <StatCard label={t("Breaks")} value={fmtMinutes(r?.break_minutes)} icon={<Coffee />} />
              </div>
              <Card>
                <CardHeader><CardTitle>{t("Today's schedule")}</CardTitle></CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {td.shift ? (
                    <>
                      <Row k={t("Shift")} v={`${fmtTime(td.shift.start, tz)} – ${fmtTime(td.shift.end, tz)}`} />
                      {td.shift.break_start && <Row k={t("Lunch")} v={`${fmtTime(td.shift.break_start, tz)} – ${fmtTime(td.shift.break_end, tz)}`} />}
                      <Row k={t("Grace period")} v={t("{n} min", { n: td.shift.grace_period_minutes })} />
                      <Row k={t("Check-in window")} v={`${fmtTime(td.shift.tracking_window_start, tz)} – ${fmtTime(td.shift.tracking_window_end, tz)}`} />
                      <Row k={t("Approval policy")} v={titleCase(td.actions.confirmation_policy)} />
                    </>
                  ) : <p className="text-muted-foreground">{t("No working shift today.")}</p>}
                </CardContent>
              </Card>
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between gap-4"><span className="text-muted-foreground">{k}</span><span className="font-medium">{v}</span></div>;
}
