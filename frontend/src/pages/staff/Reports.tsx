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
import { addDays, fmtDate, fmtDateTime, fmtMinutes, fmtTime, todayIn } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { msg, t } from "@/i18n";

type Kind = "daily" | "weekly" | "monthly" | "late-arrivals" | "early-leaves" | "absences" | "overtime";
const TABS: { v: Kind; label: string }[] = [
  { v: "daily", label: msg("Daily") }, { v: "weekly", label: msg("Weekly") }, { v: "monthly", label: msg("Monthly") }, { v: "late-arrivals", label: msg("Late arrivals") },
  { v: "early-leaves", label: msg("Early leaves") }, { v: "absences", label: msg("Absences") }, { v: "overtime", label: msg("Overtime") },
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
      <PageHeader title={scope === "team" ? t("Team reports") : t("Reports")} description={t("All figures are calculated by the server from attendance records.")} actions={<Button variant="outline" onClick={exportCsv}><Download />{t("Export CSV")}</Button>} />
      <Tabs value={kind} onValueChange={(v) => setKind(v as Kind)} className="mb-4 overflow-x-auto"><TabsList>{TABS.map((x) => <TabsTrigger key={x.v} value={x.v}>{t(x.label)}</TabsTrigger>)}</TabsList></Tabs>
      <div className="mb-4 flex flex-wrap gap-2">
        {["daily", "weekly", "monthly"].includes(kind) ? <Input type="date" value={date} onChange={(e) => setDate(e.target.value || today)} className="w-auto" aria-label={t("Date")} /> : (
          <><Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="w-auto" aria-label={t("From")} />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="w-auto" aria-label={t("To")} /></>
        )}
        <NativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="w-auto"><option value="">{t("All departments")}</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</NativeSelect>
        {q.data?.start && <span className="self-center text-sm text-muted-foreground">{fmtDate(q.data.start)} – {fmtDate(q.data.end)}</span>}
      </div>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
          {rows.length ? (
            kind === "daily" ? <Daily rows={rows} tz={tz} /> : kind === "weekly" || kind === "monthly" ? <Summary rows={rows} totals={q.data?.totals} /> : <Exceptions kind={kind} rows={rows} tz={tz} />
          ) : <EmptyState title={t("No data for this period")} />}
        </QueryState>
      </Card>
    </>
  );
}

const tm = (v: unknown, tz: string) => (v ? fmtTime(String(v), tz) : "—");

function Daily({ rows, tz }: { rows: Row[]; tz: string }) {
  return (
    <Table>
      <THead><TR><TH>{t("Employee")}</TH><TH>{t("Department")}</TH><TH>{t("Scheduled")}</TH><TH>{t("In")}</TH><TH>{t("Out")}</TH><TH>{t("Late")}</TH><TH>{t("Early leave")}</TH><TH>{t("Presence")}</TH><TH>{t("Temp. exits")}</TH><TH>{t("Payable")}</TH><TH>{t("OT")}</TH><TH>{t("Status")}</TH></TR></THead>
      <TBody>{rows.map((r) => (
        <TR key={String(r.employee_id)}>
          <TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD>
          <TD className="whitespace-nowrap">{r.shift === "Unscheduled" ? t("Unscheduled") : `${tm(r.scheduled_start, tz)}–${tm(r.scheduled_end, tz)}`}</TD><TD>{tm(r.actual_check_in, tz)}{Number(r.early_arrival_minutes) > 0 && <div className="text-xs text-muted-foreground">{t("{m}m early", { m: String(r.early_arrival_minutes) })}</div>}</TD><TD>{tm(r.actual_check_out, tz)}</TD>
          <TD>{t("{m}m", { m: String(r.late_minutes) })}</TD><TD>{t("{m}m", { m: String(r.early_departure_minutes) })}</TD><TD>{fmtMinutes(Number(r.total_presence_minutes))}</TD><TD>{fmtMinutes(Number(r.temporary_exit_minutes))}</TD>
          <TD className="font-semibold">{fmtMinutes(Number(r.payable_minutes))}</TD><TD>{fmtMinutes(Number(r.overtime_minutes))}</TD>
          <TD><StatusBadge status={String(r.status)} /></TD>
        </TR>
      ))}</TBody>
    </Table>
  );
}

function Summary({ rows, totals }: { rows: Row[]; totals?: Row }) {
  const cols: [string, string, boolean?][] = [["total_working_days", t("Working days")], ["attendance_percentage", t("Attendance %")], ["present_days", t("Present")], ["late_days", t("Late days")], ["late_minutes", t("Late min")], ["early_leave_days", t("Early leaves")], ["absent_days", t("Absent")],
    ["leave_days", t("Leave")], ["location_unavailable_days", t("No GPS")], ["worked_minutes", t("Working hours"), true], ["temporary_exit_minutes", t("Temp. exits"), true], ["overtime_minutes", t("Overtime"), true]];
  return (
    <Table>
      <THead><TR><TH>{t("Employee")}</TH><TH>{t("Department")}</TH>{cols.map(([, l]) => <TH key={l}>{l}</TH>)}</TR></THead>
      <TBody>
        {rows.map((r) => <TR key={String(r.employee_id)}><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD>{cols.map(([k, , m]) => <TD key={k}>{m ? fmtMinutes(Number(r[k])) : k === "attendance_percentage" ? (r[k] == null ? "—" : `${r[k]}%`) : r[k]}</TD>)}</TR>)}
        {totals && <TR className="bg-muted/40 font-semibold"><TD>{t("Total")}</TD><TD />{cols.map(([k, , m]) => <TD key={k}>{k === "attendance_percentage" ? "" : m ? fmtMinutes(Number(totals[k] ?? 0)) : totals[k] ?? 0}</TD>)}</TR>}
      </TBody>
    </Table>
  );
}

function Exceptions({ kind, rows, tz }: { kind: Kind; rows: Row[]; tz: string }) {
  if (kind === "absences")
    return (
      <Table><THead><TR><TH>{t("Date")}</TH><TH>{t("Employee")}</TH><TH>{t("Department")}</TH><TH>{t("Status")}</TH><TH>{t("Review")}</TH></TR></THead>
        <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD><StatusBadge status={String(r.status)} /></TD><TD className="text-xs text-muted-foreground">{r.needs_review ? t("No GPS signal — verify manually") : ""}</TD></TR>)}</TBody></Table>
    );
  if (kind === "overtime")
    return (
      <Table><THead><TR><TH>{t("Date")}</TH><TH>{t("Employee")}</TH><TH>{t("Department")}</TH><TH>{t("Scheduled")}</TH><TH>{t("Worked")}</TH><TH>{t("Overtime")}</TH></TR></THead>
        <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD>{fmtMinutes(Number(r.scheduled_minutes))}</TD><TD>{fmtMinutes(Number(r.worked_minutes))}</TD><TD className="font-semibold">{fmtMinutes(Number(r.overtime_minutes))}</TD></TR>)}</TBody></Table>
    );
  return (
    <Table><THead><TR><TH>{t("Date")}</TH><TH>{t("Employee")}</TH><TH>{t("Department")}</TH><TH>{kind === "late-arrivals" ? t("Scheduled start") : t("Scheduled end")}</TH><TH>{kind === "late-arrivals" ? t("Arrived") : t("Left")}</TH><TH>{t("Minutes")}</TH></TR></THead>
      <TBody>{rows.map((r) => <TR key={String(r.record_id)}><TD>{fmtDate(String(r.work_date))}</TD><TD className="font-medium">{r.employee_name}</TD><TD>{r.department ?? "—"}</TD><TD>{tm(r.scheduled, tz)}</TD><TD>{r.actual ? fmtDateTime(String(r.actual), tz) : "—"}</TD><TD className="font-semibold">{r.minutes}</TD></TR>)}</TBody></Table>
  );
}
