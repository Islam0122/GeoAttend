import { useState } from "react";
import { useGet, useSend } from "@/api/hooks";
import type { Anomaly, Approval, Correction } from "@/api/types";
import { EmptyState, PageHeader, QueryState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RecordDialog } from "@/features/RecordDialog";
import { fmtDate, fmtDateTime, fmtTime, titleCase } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import { t } from "@/i18n";

export function Approvals() {
  const q = useGet<Approval[]>("/attendance/approvals/", undefined, { refetchInterval: 60_000 });
  const act = useSend<{ record_id: number; session_id: number; approve: boolean }>("POST", (b) => `/attendance/${b.record_id}/approve/`, ["/attendance"], t("Saved"));
  return (
    <>
      <PageHeader title={t("Approval requests")} description={t("Check-ins awaiting approval (Manager approval policy). You can't approve your own attendance.")} />
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? (
            <Table>
              <THead><TR><TH>{t("Employee")}</TH><TH>{t("Date")}</TH><TH>{t("Check-in")}</TH><TH>{t("Check-out")}</TH><TH>{t("Office")}</TH><TH /></TR></THead>
              <TBody>{q.data.map((a) => (
                <TR key={a.session_id}>
                  <TD><div className="font-medium">{a.employee_name}</div><div className="text-xs text-muted-foreground">{a.department_name}</div></TD>
                  <TD>{fmtDate(a.work_date)}</TD><TD>{fmtTime(a.check_in_at, a.timezone)}</TD><TD>{fmtTime(a.check_out_at, a.timezone)}</TD><TD>{a.office_name ?? "—"}</TD>
                  <TD className="text-right"><div className="flex justify-end gap-1">
                    <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ record_id: a.record_id, session_id: a.session_id, approve: true })}>{t("Approve")}</Button>
                    <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate({ record_id: a.record_id, session_id: a.session_id, approve: false })}>{t("Reject")}</Button>
                  </div></TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("Nothing to approve")} />}
        </QueryState>
      </Card>
    </>
  );
}

export function Corrections() {
  const me = useAuthStore((s) => s.me);
  const [tab, setTab] = useState("PENDING");
  const [open, setOpen] = useState<number | null>(null);
  const q = useGet<Correction[]>("/attendance/corrections/", { status: tab || undefined });
  const review = useSend<{ id: number; approve: boolean; comment?: string }>("POST", (b) => `/attendance/corrections/${b.id}/review/`, ["/attendance"], t("Correction reviewed"));
  return (
    <>
      <PageHeader title={t("Attendance corrections")} description={t("Disputes and correction requests. Approved changes are applied and audit-logged.")} />
      <Tabs value={tab} onValueChange={setTab} className="mb-4"><TabsList><TabsTrigger value="PENDING">{t("Pending")}</TabsTrigger><TabsTrigger value="APPROVED">{t("Approved")}</TabsTrigger><TabsTrigger value="REJECTED">{t("Rejected")}</TabsTrigger><TabsTrigger value="">{t("All")}</TabsTrigger></TabsList></Tabs>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? (
            <Table>
              <THead><TR><TH>{t("Employee")}</TH><TH>{t("Day")}</TH><TH>{t("Type")}</TH><TH>{t("Requested")}</TH><TH>{t("Reason")}</TH><TH>{t("Status")}</TH><TH /></TR></THead>
              <TBody>{q.data.map((c) => (
                <TR key={c.id}>
                  <TD className="font-medium">{c.employee_name}</TD>
                  <TD><button className="text-primary underline-offset-2 hover:underline cursor-pointer" onClick={() => setOpen(c.record_id)}>{fmtDate(c.work_date)}</button></TD>
                  <TD>{titleCase(c.type)}</TD>
                  <TD className="text-xs">{c.requested_check_in && <div>{t("In")} {fmtDateTime(c.requested_check_in)}</div>}{c.requested_check_out && <div>{t("Out")} {fmtDateTime(c.requested_check_out)}</div>}</TD>
                  <TD className="max-w-64 text-muted-foreground">{c.reason}</TD>
                  <TD><Badge tone={c.status === "PENDING" ? "warning" : c.status === "APPROVED" ? "success" : "neutral"}>{titleCase(c.status)}</Badge></TD>
                  <TD className="text-right">{c.status === "PENDING" && c.employee_id !== me?.employee_id && (
                    <div className="flex justify-end gap-1">
                      <Button size="sm" onClick={() => review.mutate({ id: c.id, approve: true })}>{t("Approve")}</Button>
                      <Button size="sm" variant="outline" onClick={() => review.mutate({ id: c.id, approve: false })}>{t("Reject")}</Button>
                    </div>)}
                  </TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("No corrections")} />}
        </QueryState>
      </Card>
      {open && <RecordDialog id={open} mode="staff" onClose={() => setOpen(null)} />}
    </>
  );
}

export function Anomalies() {
  const [tab, setTab] = useState("OPEN");
  const q = useGet<Anomaly[]>("/anomalies/", { status: tab });
  const review = useSend<{ id: number; status: string }>("POST", (b) => `/anomalies/${b.id}/review/`, ["/anomalies"], t("Anomaly updated"));
  return (
    <>
      <PageHeader title={t("Anomalies")} description={t("Signals for human review (suspicious GPS, permission changes, missing data). They never change attendance automatically.")} />
      <Tabs value={tab} onValueChange={setTab} className="mb-4"><TabsList><TabsTrigger value="OPEN">{t("Open")}</TabsTrigger><TabsTrigger value="REVIEWED">{t("Reviewed")}</TabsTrigger><TabsTrigger value="DISMISSED">{t("Dismissed")}</TabsTrigger></TabsList></Tabs>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? (
            <Table>
              <THead><TR><TH>{t("Detected")}</TH><TH>{t("Employee")}</TH><TH>{t("Type")}</TH><TH>{t("Severity")}</TH><TH>{t("Details")}</TH><TH /></TR></THead>
              <TBody>{q.data.map((a) => (
                <TR key={a.id}>
                  <TD className="whitespace-nowrap">{fmtDateTime(a.detected_at)}</TD><TD className="font-medium">{a.employee_name}</TD><TD>{titleCase(a.type)}</TD>
                  <TD><Badge tone={a.severity === "HIGH" ? "danger" : a.severity === "WARNING" ? "warning" : "info"}>{titleCase(a.severity)}</Badge></TD>
                  <TD className="max-w-72 truncate font-mono text-xs text-muted-foreground">{a.details ? JSON.stringify(a.details) : ""}</TD>
                  <TD className="text-right">{a.status === "OPEN" && <div className="flex justify-end gap-1">
                    <Button size="sm" variant="outline" onClick={() => review.mutate({ id: a.id, status: "REVIEWED" })}>{t("Mark reviewed")}</Button>
                    <Button size="sm" variant="ghost" onClick={() => review.mutate({ id: a.id, status: "DISMISSED" })}>{t("Dismiss")}</Button>
                  </div>}</TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("No anomalies")} />}
        </QueryState>
      </Card>
    </>
  );
}
