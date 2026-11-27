import { Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { downloadCsv } from "@/api/client";
import { useGet } from "@/api/hooks";
import type { Department } from "@/api/types";
import { EmptyState, PageHeader, QueryState, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { addDays, fmtDate, fmtDateTime, fmtMinutes, todayIn } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

type Kind = "daily" | "weekly" | "monthly" | "late-arrivals" | "early-leaves" | "absences" | "overtime";
const TABS: { v: Kind; label: string }[] = [
  { v: "daily", label: "Daily" }, { v: "weekly", label: "Weekly" }, { v: "monthly", label: "Monthly" }, { v: "late-arrivals", label: "Late arrivals" },
  { v: "early-leaves", label: "Early leaves" }, { v: "absences", label: "Absences" }, { v: "overtime", label: "Overtime" },
];
type Row = Record<string, string | number | null | boolean>;

export function Reports({ scope }: { scope: "org" | "team" }) {
  const tz = useAuthStore((s) => s.me!.organization_timezone);
  const today = todayIn(tz);
  const [kind, setKind] = useState<Kind>("daily");
  const [date, setDate] = useState(today);
  const [range, setRange] = useState({ start: addDays(today, -29), end: today });
  const [dept, setDept] = useState("");
  const depts = useGet<Department[]>("/departments/");
  const params: Record<string, string | undefined> =
    kind === "daily" ? { date } : kind === "weekly" ? { week_of: date } : kind === "monthly" ? { month: date } : { ...range };
  const q = useGet<{ rows: Row[]; totals?: Row; summary?: Row; count?: number; total_minutes?: number; start?: string; end?: string }>(`/reports/${kind}/`, { ...params, department_id: dept || undefined });
  const exportCsv = () => downloadCsv("/reports/export/", { report: kind, start: ["daily", "weekly", "monthly"].includes(kind) ? date : range.start, end: range.end, department_id: dept }, `${kind}-${date}.csv`).catch((e) => toast.error(e.message));
  const rows = q.data?.rows ?? [];

  return (
    <>
      <PageHeader title={scope === "team" ? "Team reports" : "Reports"} description="All figures are calculated by the server from attendance records." actions={<Button variant="outline" onClick={exportCsv}><Download />Export CSV</Button>} />
      <Tabs value={kind} onValueChange={(v) => setKind(v as Kind)} className="mb-4 overflow-x-auto"><TabsList>{TABS.map((t) => <TabsTrigger key={t.v} value={t.v}>{t.label}</TabsTrigger>)}</TabsList></Tabs>
      <div className="mb-4 flex flex-wrap gap-2">
        {["daily", "weekly", "monthly"].includes(kind) ? <Input type="date" value={date} onChange={(e) => setDate(e.target.value || today)} className="w-auto" aria-label="Date" /> : (
          <><Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="w-auto" aria-label="From" />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="w-auto" aria-label="To" /></>
        )}
        <NativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="w-auto"><option value="">All departments</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</NativeSelect>
        {q.data?.start && <span className="self-center text-sm text-muted-foreground">{fmtDate(q.data.start)} – {fmtDate(q.data.end)}</span>}
      </div>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
          {rows.length ? (
            kind === "daily" ? <Daily rows={rows} tz={tz} /> : kind === "weekly" || kind === "monthly" ? <Summary rows={rows} totals={q.data?.totals} /> : <Exceptions kind={kind} rows={rows} tz={tz} />
          ) : <EmptyState title="No data for this period" />}
        </QueryState>
      </Card>
    </>
  );
}

const t = (v: unknown, tz: string) => (v ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(String(v))) : "—");

function Daily({ rows, tz }: { rows: Row[]; tz: string }) {
  return (
    <Table>
      <THead><TR><TH>Employee</TH><TH>Department</TH><TH>Scheduled</TH><TH>In</TH><TH>Out</TH><TH>Late</TH><TH>Early leave</TH><TH>Presence</TH><TH>Temp. exits</TH><TH>Payable</TH><TH>OT</TH><TH>Status</TH></TR></THead>
      <TBody>{rows.map((r) => (
        <TR key={String(r.employee_id)}>
          <TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD>
          <TD className="whitespace-nowrap">{r.shift === "Unscheduled" ? "Unscheduled" : `${t(r.scheduled_start, tz)}–${t(r.scheduled_end, tz)}`}</TD><TD>{t(r.actual_check_in, tz)}{Number(r.early_arrival_minutes) > 0 && <div className="text-xs text-muted-foreground">{r.early_arrival_minutes}m early</div>}</TD><TD>{t(r.actual_check_out, tz)}</TD>
          <TD>{r.late_minutes}m</TD><TD>{r.early_departure_minutes}m</TD><TD>{fmtMinutes(Number(r.total_presence_minutes))}</TD><TD>{fmtMinutes(Number(r.temporary_exit_minutes))}</TD>
          <TD className="font-semibold">{fmtMinutes(Number(r.payable_minutes))}</TD><TD>{fmtMinutes(Number(r.overtime_minutes))}</TD>
          <TD><StatusBadge status={String(r.status)} /></TD>
        </TR>
      ))}</TBody>
    </Table>
  );
}

function Summary({ rows, totals }: { rows: Row[]; totals?: Row }) {
  const cols: [string, string, boolean?][] = [["total_working_days", "Working days"], ["attendance_percentage", "Attendance %"], ["present_days", "Present"], ["late_days", "Late days"], ["late_minutes", "Late min"], ["early_leave_days", "Early leaves"], ["absent_days", "Absent"],
    ["leave_days", "Leave"], ["location_unavailable_days", "No GPS"], ["worked_minutes", "Working hours", true], ["temporary_exit_minutes", "Temp. exits", true], ["overtime_minutes", "Overtime", true]];
  return (
    <Table>
      <THead><TR><TH>Employee</TH><TH>Department</TH>{cols.map(([, l]) => <TH key={l}>{l}</TH>)}</TR></THead>
      <TBody>
        {rows.map((r) => <TR key={String(r.employee_id)}><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD>{cols.map(([k, , m]) => <TD key={k}>{m ? fmtMinutes(Number(r[k])) : k === "attendance_percentage" ? (r[k] == null ? "—" : `${r[k]}%`) : r[k]}</TD>)}</TR>)}
        {totals && <TR className="bg-muted/40 font-semibold"><TD>Total</TD><TD />{cols.map(([k, , m]) => <TD key={k}>{k === "attendance_percentage" ? "" : m ? fmtMinutes(Number(totals[k] ?? 0)) : totals[k] ?? 0}</TD>)}</TR>}
      </TBody>
    </Table>
  );
}

function Exceptions({ kind, rows, tz }: { kind: Kind; rows: Row[]; tz: string }) {
  if (kind === "absences")
    return (
      <Table><THead><TR><TH>Date</TH><TH>Employee</TH><TH>Department</TH><TH>Status</TH><TH>Review</TH></TR></THead>
        <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD><StatusBadge status={String(r.status)} /></TD><TD className="text-xs text-muted-foreground">{r.needs_review ? "No GPS signal — verify manually" : ""}</TD></TR>)}</TBody></Table>
    );
  if (kind === "overtime")
    return (
      <Table><THead><TR><TH>Date</TH><TH>Employee</TH><TH>Department</TH><TH>Scheduled</TH><TH>Worked</TH><TH>Overtime</TH></TR></THead>
        <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD>{fmtMinutes(Number(r.scheduled_minutes))}</TD><TD>{fmtMinutes(Number(r.worked_minutes))}</TD><TD className="font-semibold">{fmtMinutes(Number(r.overtime_minutes))}</TD></TR>)}</TBody></Table>
    );
  return (
    <Table><THead><TR><TH>Date</TH><TH>Employee</TH><TH>Department</TH><TH>{kind === "late-arrivals" ? "Scheduled start" : "Scheduled end"}</TH><TH>{kind === "late-arrivals" ? "Arrived" : "Left"}</TH><TH>Minutes</TH></TR></THead>
      <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD>{t(r.scheduled, tz)}</TD><TD>{r.actual ? fmtDateTime(String(r.actual), tz) : "—"}</TD><TD className="font-semibold">{r.minutes}</TD></TR>)}</TBody></Table>
  );
}
