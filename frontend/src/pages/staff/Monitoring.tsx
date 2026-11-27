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
import { ago, fmtDateTime, fmtMinutes, fmtTime, titleCase } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

export const ZONE_LABEL: Record<ZoneStatus, { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" | "outline"; hint: string }> = {
  INSIDE: { label: "Inside", tone: "success", hint: "Server-validated reading inside the assigned geofence" },
  OUTSIDE: { label: "Outside", tone: "neutral", hint: "Server-validated reading outside every assigned geofence" },
  LOCATION_DETECTED: { label: "Detected", tone: "info", hint: "Location received but not precise enough to confirm" },
  STALE: { label: "Stale", tone: "warning", hint: "No location check recently (screen closed, offline or GPS off)" },
  UNKNOWN: { label: "Unknown", tone: "outline", hint: "No location data yet" },
  LOCATION_DENIED: { label: "Location denied", tone: "danger", hint: "GPS permission is blocked in the employee's browser" },
  NO_OFFICE: { label: "No office", tone: "danger", hint: "No office geofence is assigned" },
};
export const SESSION_LABEL: Record<SessionState, { label: string; tone: "success" | "warning" | "info" | "neutral" }> = {
  ACTIVE: { label: "Active", tone: "success" },
  TEMPORARY_EXIT: { label: "Temporary exit", tone: "warning" },
  PENDING_CHECKOUT: { label: "Checkout to confirm", tone: "info" },
  COMPLETED: { label: "Completed", tone: "neutral" },
  NOT_STARTED: { label: "Not started", tone: "neutral" },
};
const FILTERS: { v: MonitoringFilter; label: string }[] = [
  { v: "all", label: "All employees" }, { v: "inside", label: "Inside office" }, { v: "outside", label: "Outside office" }, { v: "active", label: "Active sessions" },
  { v: "late", label: "Late" }, { v: "temporary_exit", label: "Temporary exits" }, { v: "stale", label: "Stale locations" },
  { v: "no_permission", label: "No GPS permission" }, { v: "no_office", label: "No assigned office" },
];

export function MonitoringTable({ rows, tz }: { rows: MonitoringEmployee[]; tz: string }) {
  return (
    <Table>
      <THead><TR>
        <TH>Employee</TH><TH>Assigned office</TH><TH>Zone</TH><TH>Distance</TH><TH>GPS accuracy</TH><TH>Last update</TH><TH>Permission</TH>
        <TH>Attendance</TH><TH>Session</TH><TH>Check-in</TH><TH>Working</TH><TH>Last activity</TH>
      </TR></THead>
      <TBody>{rows.map((r) => {
        const z = ZONE_LABEL[r.zone_status];
        const s = SESSION_LABEL[r.session_status];
        return (
          <TR key={r.employee_id} data-testid={`row-${r.employee_id}`}>
            <TD><div className="font-medium">{r.employee_name}</div><div className="text-xs text-muted-foreground">{[r.position, r.department_name].filter(Boolean).join(" · ") || "—"}</div></TD>
            <TD className="text-xs">{r.assigned_offices.length ? r.assigned_offices.join(", ") : "—"}{r.office_name && r.assigned_offices.length > 1 && <div className="text-muted-foreground">at {r.office_name}</div>}</TD>
            <TD><Badge tone={z.tone} title={`${z.hint}. ${r.zone_reason}`} data-testid="zone">{z.label}</Badge></TD>
            <TD>{r.distance_m != null ? `${Math.round(r.distance_m)} m` : "—"}</TD>
            <TD>{r.accuracy_m != null ? `±${Math.round(r.accuracy_m)} m` : "—"}</TD>
            <TD title={r.last_update ? fmtDateTime(r.last_update, tz) : undefined}>{r.last_update ? ago(r.last_update) : "—"}</TD>
            <TD>{!r.consent_granted ? <Badge tone="danger">No consent</Badge> : r.permission ? <Badge tone={r.permission.startsWith("GRANTED") ? "success" : r.permission === "UNKNOWN" ? "neutral" : "danger"}>{titleCase(r.permission.replace("GRANTED_", ""))}</Badge> : <Badge>No device</Badge>}</TD>
            <TD>{["NOT_CHECKED_IN", "NO_SHIFT"].includes(r.attendance_status) ? <span className="text-xs text-muted-foreground">{titleCase(r.attendance_status)}</span> : <StatusBadge status={r.attendance_status} />}
              {r.late_minutes > 0 && <div className="text-xs text-amber-600">+{r.late_minutes} min</div>}</TD>
            <TD><Badge tone={s.tone} data-testid="session">{s.label}</Badge>{r.temporary_exit_started_at && <div className="text-xs text-muted-foreground">since {fmtTime(r.temporary_exit_started_at, tz)}</div>}</TD>
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
      <PageHeader title="Employee monitoring"
        description={<>Latest server-validated status · refreshes every 30 s while this page is open · {updatedAt ? <>updated <span data-testid="updated-at">{fmtTime(new Date(updatedAt).toISOString(), tz)}</span></> : "loading…"}</>}
        actions={<NativeSelect value={officeId ?? ""} onChange={(e) => setOfficeId(e.target.value ? Number(e.target.value) : null)} className="w-auto min-w-44" aria-label="Office">
          <option value="">All offices</option>{offices.data?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </NativeSelect>} />
      <Alert tone="success" icon={<ShieldCheck />} title="Privacy by design" className="mb-4">
        Only attendance data is shown: zone, distance to the office and GPS accuracy from the employee's last check. Coordinates, routes and movement history
        are never available here. Locations are collected only while an employee has the attendance screen open during working hours. “Stale” means the screen
        was closed or the device went offline — it is never treated as leaving the office.
      </Alert>
      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <StatCard label="Total employees" value={s.total_employees} icon={<Users />} />
          <StatCard label="Currently inside" value={s.currently_inside} icon={<Building2 />} accent />
          <StatCard label="Currently outside" value={s.currently_outside} icon={<DoorOpen />} />
          <StatCard label="Active sessions" value={s.active_sessions} icon={<Activity />} />
          <StatCard label="Late today" value={s.late_today} icon={<AlarmClock />} />
          <StatCard label="Temporary exits" value={s.temporary_exits} icon={<LogIn />} />
          <StatCard label="Location unavailable" value={s.location_unavailable} hint={`${s.stale} stale · ${s.no_permission} no permission`} icon={<MapPinOff />} />
        </div>
      )}
      <Tabs value={filter} onValueChange={(v) => setFilter(v as MonitoringFilter)} className="mb-3 overflow-x-auto">
        <TabsList>{FILTERS.map((f) => <TabsTrigger key={f.v} value={f.v}>{f.label}</TabsTrigger>)}</TabsList>
      </Tabs>
      <Card className="mb-4">
        <QueryState isLoading={rows.isLoading} error={rows.error} rows={5}>
          {rows.data?.length ? <MonitoringTable rows={rows.data} tz={tz} /> : <EmptyState title="No employees match this filter" />}
        </QueryState>
      </Card>
      <Card className="p-3">
        <GeoMap className="h-72" fences={(offices.data ?? []).map((o) => {
          const n = insideAt(o.id);
          return { id: o.id, name: o.name, lat: o.latitude, lng: o.longitude, radius: o.radius, active: o.is_active && o.geofence.enabled, label: n == null ? o.name : `${o.name} · ${n} inside` };
        })} />
        <p className="mt-2 text-xs text-muted-foreground">Offices and geofences only — employee positions are never plotted.</p>
      </Card>
    </>
  );
}
