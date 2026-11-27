import { Activity, AlarmClock, Building2, DoorOpen, LogIn, MapPinOff, ShieldCheck, Users } from "lucide-react";
import { useState } from "react";
import { useGet } from "@/api/hooks";
import type { MonitoringEmployee, Office, SessionState, ZoneStatus } from "@/api/types";
import { GeoMap } from "@/components/GeoMap";
import { EmptyState, PageHeader, QueryState, StatCard, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { NativeSelect } from "@/components/ui/input";
import { Alert, Tabs, TabsList, TabsTrigger } from "@/components/ui/misc";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useAttendanceMonitoring, type MonitoringFilter } from "@/features/automatic/useAttendanceMonitoring";
import { ago, fmtDateTime, fmtMeters, fmtMinutes, fmtTime, titleCase } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { msg, t } from "@/i18n";

export const ZONE_LABEL: Record<ZoneStatus, { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" | "outline"; hint: string }> = {
  INSIDE: { label: msg("Inside"), tone: "success", hint: msg("Server-validated reading inside the assigned geofence") },
  OUTSIDE: { label: msg("Outside"), tone: "neutral", hint: msg("Server-validated reading outside every assigned geofence") },
  LOCATION_DETECTED: { label: msg("Detected"), tone: "info", hint: msg("Location received but not precise enough to confirm") },
  STALE: { label: msg("Stale"), tone: "warning", hint: msg("No location check recently (screen closed, offline or GPS off)") },
  UNKNOWN: { label: msg("Unknown"), tone: "outline", hint: msg("No location data yet") },
  LOCATION_DENIED: { label: msg("Location denied"), tone: "danger", hint: msg("GPS permission is blocked in the employee's browser") },
  NO_OFFICE: { label: msg("No office"), tone: "danger", hint: msg("No office geofence is assigned") },
};
export const SESSION_LABEL: Record<SessionState, { label: string; tone: "success" | "warning" | "info" | "neutral" }> = {
  ACTIVE: { label: msg("Active"), tone: "success" },
  TEMPORARY_EXIT: { label: msg("Temporary exit"), tone: "warning" },
  PENDING_CHECKOUT: { label: msg("Checkout to confirm"), tone: "info" },
  COMPLETED: { label: msg("Completed"), tone: "neutral" },
  NOT_STARTED: { label: msg("Not started"), tone: "neutral" },
};
const FILTERS: { v: MonitoringFilter; label: string }[] = [
  { v: "all", label: msg("All employees") }, { v: "inside", label: msg("Inside office") }, { v: "outside", label: msg("Outside office") }, { v: "active", label: msg("Active sessions") },
  { v: "late", label: msg("Late") }, { v: "temporary_exit", label: msg("Temporary exits") }, { v: "stale", label: msg("Stale locations") },
  { v: "no_permission", label: msg("No GPS permission") }, { v: "no_office", label: msg("No assigned office") },
];

export function MonitoringTable({ rows, tz }: { rows: MonitoringEmployee[]; tz: string }) {
  return (
    <Table>
      <THead><TR>
        <TH>{t("Employee")}</TH><TH>{t("Assigned office")}</TH><TH>{t("Zone")}</TH><TH>{t("Distance")}</TH><TH>{t("GPS accuracy")}</TH><TH>{t("Last update")}</TH><TH>{t("Permission")}</TH>
        <TH>{t("Attendance")}</TH><TH>{t("Session")}</TH><TH>{t("Check-in")}</TH><TH>{t("Working")}</TH><TH>{t("Last activity")}</TH>
      </TR></THead>
      <TBody>{rows.map((r) => {
        const z = ZONE_LABEL[r.zone_status];
        const s = SESSION_LABEL[r.session_status];
        return (
          <TR key={r.employee_id} data-testid={`row-${r.employee_id}`}>
            <TD><div className="font-medium">{r.employee_name}</div><div className="text-xs text-muted-foreground">{[r.position, r.department_name].filter(Boolean).join(" · ") || "—"}</div></TD>
            <TD className="text-xs">{r.assigned_offices.length ? r.assigned_offices.join(", ") : "—"}{r.office_name && r.assigned_offices.length > 1 && <div className="text-muted-foreground">{t("at {office}", { office: r.office_name })}</div>}</TD>
            <TD><Badge tone={z.tone} title={`${t(z.hint)}. ${t(r.zone_reason)}`} data-testid="zone">{t(z.label)}</Badge></TD>
            <TD>{r.distance_m != null ? fmtMeters(r.distance_m) : "—"}</TD>
            <TD>{r.accuracy_m != null ? fmtMeters(r.accuracy_m, true) : "—"}</TD>
            <TD title={r.last_update ? fmtDateTime(r.last_update, tz) : undefined}>{r.last_update ? ago(r.last_update) : "—"}</TD>
            <TD>{!r.consent_granted ? <Badge tone="danger">{t("No consent")}</Badge> : r.permission ? <Badge tone={r.permission.startsWith("GRANTED") ? "success" : r.permission === "UNKNOWN" ? "neutral" : "danger"}>{titleCase(r.permission.replace("GRANTED_", ""))}</Badge> : <Badge>{t("No device")}</Badge>}</TD>
            <TD>{["NOT_CHECKED_IN", "NO_SHIFT"].includes(r.attendance_status) ? <span className="text-xs text-muted-foreground">{titleCase(r.attendance_status)}</span> : <StatusBadge status={r.attendance_status} />}
              {r.late_minutes > 0 && <div className="text-xs text-amber-600">+{t("{n} min", { n: r.late_minutes })}</div>}</TD>
            <TD><Badge tone={s.tone} data-testid="session">{t(s.label)}</Badge>{r.temporary_exit_started_at && <div className="text-xs text-muted-foreground">{t("since {time}", { time: fmtTime(r.temporary_exit_started_at, tz) })}</div>}</TD>
            <TD>{fmtTime(r.check_in_time, tz)}</TD>
            <TD>{fmtMinutes(r.working_minutes)}</TD>
            <TD>{r.last_activity ? ago(r.last_activity) : "—"}</TD>
          </TR>
        );
      })}</TBody>
    </Table>
  );
}

export function Monitoring() {
  const tz = useAuthStore((s) => s.me!.organization_timezone);
  const [filter, setFilter] = useState<MonitoringFilter>("all");
  const [officeId, setOfficeId] = useState<number | null>(null);
  const offices = useGet<Office[]>("/offices/");
  const { rows, summary, updatedAt } = useAttendanceMonitoring(filter, officeId);
  const s = summary.data;
  const insideAt = (id: number) => (filter === "all" ? rows.data?.filter((r) => r.office_id === id && r.zone_status === "INSIDE").length ?? 0 : null);
  return (
    <>
      <PageHeader title={t("Employee monitoring")}
        description={<>{t("Latest server-validated status · refreshes every 30 s while this page is open")} · {updatedAt ? <>{t("updated")} <span data-testid="updated-at">{fmtTime(new Date(updatedAt).toISOString(), tz)}</span></> : t("loading…")}</>}
        actions={<NativeSelect value={officeId ?? ""} onChange={(e) => setOfficeId(e.target.value ? Number(e.target.value) : null)} className="w-auto min-w-44" aria-label={t("Office")}>
          <option value="">{t("All offices")}</option>{offices.data?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </NativeSelect>} />
      <Alert tone="success" icon={<ShieldCheck />} title={t("Privacy by design")} className="mb-4">
        {t("Only attendance data is shown: zone, distance to the office and GPS accuracy from the employee's last check. Coordinates, routes and movement history are never available here. Locations are collected only while an employee has the attendance screen open during working hours. “Stale” means the screen was closed or the device went offline — it is never treated as leaving the office.")}
      </Alert>
      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <StatCard label={t("Total employees")} value={s.total_employees} icon={<Users />} />
          <StatCard label={t("Currently inside")} value={s.currently_inside} icon={<Building2 />} accent />
          <StatCard label={t("Currently outside")} value={s.currently_outside} icon={<DoorOpen />} />
          <StatCard label={t("Active sessions")} value={s.active_sessions} icon={<Activity />} />
          <StatCard label={t("Late today")} value={s.late_today} icon={<AlarmClock />} />
          <StatCard label={t("Temporary exits")} value={s.temporary_exits} icon={<LogIn />} />
          <StatCard label={t("Location unavailable")} value={s.location_unavailable} hint={t("{stale} stale · {np} no permission", { stale: s.stale, np: s.no_permission })} icon={<MapPinOff />} />
        </div>
      )}
      <Tabs value={filter} onValueChange={(v) => setFilter(v as MonitoringFilter)} className="mb-3 overflow-x-auto">
        <TabsList>{FILTERS.map((f) => <TabsTrigger key={f.v} value={f.v}>{t(f.label)}</TabsTrigger>)}</TabsList>
      </Tabs>
      <Card className="mb-4">
        <QueryState isLoading={rows.isLoading} error={rows.error} rows={5}>
          {rows.data?.length ? <MonitoringTable rows={rows.data} tz={tz} /> : <EmptyState title={t("No employees match this filter")} />}
        </QueryState>
      </Card>
      <Card className="p-3">
        <GeoMap className="h-72" fences={(offices.data ?? []).map((o) => {
          const n = insideAt(o.id);
          return { id: o.id, name: o.name, lat: o.latitude, lng: o.longitude, radius: o.radius, active: o.is_active && o.geofence.enabled, label: n == null ? o.name : `${o.name} · ${t("{n} inside", { n })}` };
        })} />
        <p className="mt-2 text-xs text-muted-foreground">{t("Offices and geofences only — employee positions are never plotted.")}</p>
      </Card>
    </>
  );
}
