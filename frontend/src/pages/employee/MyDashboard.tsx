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
import { fmtMinutes, fmtTime, greeting } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { useQueueStore } from "@/stores/queue";

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
  const t = q.data;
  const tz = t?.shift?.timezone ?? me.organization_timezone;
  const r = t?.record;
  return (
    <>
      <PageHeader title={`${greeting(tz)}, ${me.full_name.split(" ")[0]}!`}
        description={t?.shift ? <>Your shift {new Date(t.shift.start) > new Date() ? "starts" : "started"} at <b>{fmtTime(t.shift.start, tz)}</b> and ends at <b>{fmtTime(t.shift.end, tz)}</b>.</> : "You have no shift scheduled today."} />
      <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
        {t && (
          <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
            <div className="space-y-4">
              {pending.length > 0 && <Alert tone="info" title={`${pending.length} offline action(s) pending`}>They'll be validated by the server automatically when you're online.</Alert>}
              {automatic ? <AutomaticAttendancePanel today={t} /> : <CheckInPanel today={t} onFix={reporter} />}
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="Status" value={r ? <StatusBadge status={r.status} /> : <span className="text-base text-muted-foreground">Not checked in</span>} icon={<Clock />} />
                <StatCard label="Worked today" value={fmtMinutes(r?.worked_minutes)} icon={<Timer />} accent />
                <StatCard label="Checked in" value={fmtTime(r?.actual_check_in, tz)} hint={r?.late_minutes ? `${r.late_minutes} min late` : r?.actual_check_in ? "On time" : undefined} icon={<CalendarClock />} />
                <StatCard label="Breaks" value={fmtMinutes(r?.break_minutes)} icon={<Coffee />} />
              </div>
              <Card>
                <CardHeader><CardTitle>Today's schedule</CardTitle></CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {t.shift ? (
                    <>
                      <Row k="Shift" v={`${fmtTime(t.shift.start, tz)} – ${fmtTime(t.shift.end, tz)}`} />
                      {t.shift.break_start && <Row k="Lunch" v={`${fmtTime(t.shift.break_start, tz)} – ${fmtTime(t.shift.break_end, tz)}`} />}
                      <Row k="Grace period" v={`${t.shift.grace_period_minutes} min`} />
                      <Row k="Check-in window" v={`${fmtTime(t.shift.tracking_window_start, tz)} – ${fmtTime(t.shift.tracking_window_end, tz)}`} />
                      <Row k="Approval policy" v={t.actions.confirmation_policy.replaceAll("_", " ").toLowerCase()} />
                    </>
                  ) : <p className="text-muted-foreground">No working shift today.</p>}
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
