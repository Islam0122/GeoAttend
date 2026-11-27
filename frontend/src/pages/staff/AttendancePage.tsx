import { Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { downloadCsv } from "@/api/client";
import { useGet } from "@/api/hooks";
import type { AttendanceRecord, Department, Office, Page } from "@/api/types";
import { EmptyState, PageHeader, QueryState, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RecordDialog } from "@/features/RecordDialog";
import { fmtDate, fmtMinutes, fmtTime, STATUS_LABEL, todayIn } from "@/lib/format";
import { isStaff } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";
import { t } from "@/i18n";

export function AttendancePage({ scope }: { scope: "org" | "team" }) {
  const me = useAuthStore((s) => s.me)!;
  const today = todayIn(me.organization_timezone);
  const [f, setF] = useState({ date_from: today, date_to: today, department_id: "", office_id: "", status: "", page: 1 });
  const q = useGet<Page<AttendanceRecord>>("/attendance/", { ...f, page_size: 50 });
  const depts = useGet<Department[]>("/departments/");
  const offices = useGet<Office[]>("/offices/");
  const [open, setOpen] = useState<number | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value, page: 1 });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / 50)) : 1;

  return (
    <>
      <PageHeader title={scope === "team" ? t("Team attendance") : t("Attendance")} description={t("Click a row for sessions, breaks, approvals and corrections.")}
        actions={<Button variant="outline" onClick={() => downloadCsv("/reports/export/", { report: "daily", start: f.date_from }, `attendance-${f.date_from}.csv`).catch((e) => toast.error(e.message))}><Download />{t("Export CSV")}</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input type="date" value={f.date_from} onChange={set("date_from")} className="w-auto" aria-label={t("From")} />
        <Input type="date" value={f.date_to} onChange={set("date_to")} className="w-auto" aria-label={t("To")} />
        <NativeSelect value={f.department_id} onChange={set("department_id")} className="w-auto"><option value="">{t("All departments")}</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</NativeSelect>
        <NativeSelect value={f.office_id} onChange={set("office_id")} className="w-auto"><option value="">{t("All offices")}</option>{offices.data?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</NativeSelect>
        <NativeSelect value={f.status} onChange={set("status")} className="w-auto"><option value="">{t("All statuses")}</option>{Object.entries(STATUS_LABEL).filter(([k]) => k !== "NOT_CHECKED_IN").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</NativeSelect>
      </div>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
          {q.data?.items.length ? (
            <Table>
              <THead><TR><TH>{t("Date")}</TH><TH>{t("Employee")}</TH><TH>{t("Department")}</TH><TH>{t("Office")}</TH><TH>{t("Scheduled")}</TH><TH>{t("Check-in")}</TH><TH>{t("Check-out")}</TH><TH>{t("Worked")}</TH><TH>{t("Late")}</TH><TH>{t("Status")}</TH></TR></THead>
              <TBody>{q.data.items.map((r) => (
                <TR key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                  <TD className="whitespace-nowrap">{fmtDate(r.work_date)}</TD>
                  <TD className="font-medium">{r.employee_name}</TD>
                  <TD>{r.department_name ?? "—"}</TD>
                  <TD>{r.office_name ?? "—"}</TD>
                  <TD className="whitespace-nowrap">{fmtTime(r.scheduled_start, r.timezone)}–{fmtTime(r.scheduled_end, r.timezone)}</TD>
                  <TD>{fmtTime(r.actual_check_in, r.timezone)}</TD>
                  <TD>{fmtTime(r.actual_check_out, r.timezone)}{r.early_departure_minutes > 0 && <div className="text-xs text-muted-foreground">{t("−{m}m early", { m: r.early_departure_minutes })}</div>}</TD>
                  <TD>{fmtMinutes(r.worked_minutes)}{r.overtime_minutes > 0 && <div className="text-xs text-muted-foreground">{t("+{time} OT", { time: fmtMinutes(r.overtime_minutes) })}</div>}</TD>
                  <TD>{r.late_minutes ? t("{m}m", { m: r.late_minutes }) : "—"}</TD>
                  <TD><StatusBadge status={r.status} /></TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("No records for this filter")} />}
        </QueryState>
        <div className="flex items-center justify-between border-t p-3 text-sm">
          <span className="text-muted-foreground">{t("{n} records", { n: q.data?.total ?? 0 })}</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>{t("Previous")}</Button>
            <span className="text-muted-foreground">{f.page} / {pages}</span>
            <Button size="sm" variant="outline" disabled={f.page >= pages} onClick={() => setF({ ...f, page: f.page + 1 })}>{t("Next")}</Button>
          </div>
        </div>
      </Card>
      {open && <RecordDialog id={open} mode={isStaff(me) ? "staff" : "employee"} onClose={() => setOpen(null)} />}
    </>
  );
}
