import { useState } from "react";
import { useGet } from "@/api/hooks";
import type { AttendanceRecord, Page } from "@/api/types";
import { EmptyState, PageHeader, QueryState, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RecordDialog } from "@/features/RecordDialog";
import { fmtDate, fmtMinutes, fmtTime } from "@/lib/format";
import { t } from "@/i18n";

export function MyAttendance() {
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const q = useGet<Page<AttendanceRecord>>("/attendance/", { page, page_size: 20 });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / 20)) : 1;
  return (
    <>
      <PageHeader title={t("My attendance")} description={t("Tap a day for details, to confirm a check-out, or to dispute it.")} />
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.items.length ? (
            <Table>
              <THead><TR><TH>{t("Date")}</TH><TH>{t("In")}</TH><TH>{t("Out")}</TH><TH>{t("Worked")}</TH><TH>{t("Late")}</TH><TH>{t("Status")}</TH></TR></THead>
              <TBody>
                {q.data.items.map((r) => (
                  <TR key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                    <TD className="font-medium">{fmtDate(r.work_date)}</TD>
                    <TD>{fmtTime(r.actual_check_in, r.timezone)}</TD>
                    <TD>{fmtTime(r.actual_check_out, r.timezone)}</TD>
                    <TD>{fmtMinutes(r.worked_minutes)}</TD>
                    <TD>{r.late_minutes ? t("{m}m", { m: r.late_minutes }) : "—"}</TD>
                    <TD><StatusBadge status={r.status} /></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : <EmptyState title={t("No attendance yet")}>{t("Your check-ins will appear here.")}</EmptyState>}
        </QueryState>
        <div className="flex items-center justify-end gap-2 border-t p-3">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("Previous")}</Button>
          <span className="text-sm text-muted-foreground">{page} / {pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("Next")}</Button>
        </div>
      </Card>
      {open && <RecordDialog id={open} mode="employee" onClose={() => setOpen(null)} />}
    </>
  );
}
