import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { RecordDetail } from "@/api/types";
import { Field, QueryState, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useState } from "react";
import { fmtDate, fmtDateTime, fmtMeters, fmtMinutes, fmtTime, titleCase } from "@/lib/format";
import { isHR } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";
import { msg, t } from "@/i18n";

const schema = z.object({
  type: z.enum(["DISPUTE", "WRONG_TIME", "MISSING_CHECK_IN", "MISSING_CHECK_OUT", "OTHER"]),
  requested_check_in: z.string().optional(),
  requested_check_out: z.string().optional(),
  reason: z.string().min(3, msg("Please explain the problem (min. 3 characters)")).max(2000),
}).refine((v) => !(v.requested_check_in && v.requested_check_out) || v.requested_check_out > v.requested_check_in, { path: ["requested_check_out"], message: msg("Check-out must be after check-in") })
  .refine((v) => v.type !== "MISSING_CHECK_OUT" || !!v.requested_check_out, { path: ["requested_check_out"], message: msg("Provide the check-out time") })
  .refine((v) => !["WRONG_TIME", "MISSING_CHECK_IN"].includes(v.type) || !!(v.requested_check_in || v.requested_check_out), { path: ["requested_check_in"], message: msg("Provide the corrected time") });
type Form = z.infer<typeof schema>;

const iso = (v?: string) => (v ? new Date(v).toISOString() : null);

/** Attendance record detail with sessions. `mode` decides who can do what: employee disputes, staff file corrections / approvals. */
function SessionOverride({ sessions, tz }: { sessions: RecordDetail["sessions"]; tz: string }) {
  const [sid, setSid] = useState(sessions[0].id);
  const [v, setV] = useState({ check_in_at: "", check_out_at: "", reason: "" });
  const save = useSend<object>("PATCH", `/attendance/sessions/${sid}/`, ["/attendance"], t("Session corrected (audit logged)"));
  return (
    <form className="space-y-3 rounded-lg border border-primary/30 p-4" data-testid="session-override"
      onSubmit={(e) => { e.preventDefault(); save.mutate({ reason: v.reason, check_in_at: iso(v.check_in_at), check_out_at: iso(v.check_out_at) }); }}>
      <div className="font-semibold">{t("Admin override")}</div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t("Session")}><NativeSelect value={sid} onChange={(e) => setSid(Number(e.target.value))}>
          {sessions.map((s) => <option key={s.id} value={s.id}>{fmtTime(s.check_in_at, tz)}–{fmtTime(s.check_out_at, tz)}</option>)}</NativeSelect></Field>
        <Field label={t("New check-in")}><Input type="datetime-local" value={v.check_in_at} onChange={(e) => setV({ ...v, check_in_at: e.target.value })} /></Field>
        <Field label={t("New check-out")}><Input type="datetime-local" value={v.check_out_at} onChange={(e) => setV({ ...v, check_out_at: e.target.value })} /></Field>
      </div>
      <Field label={t("Reason (required, stored in the audit log)")}><Input value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} /></Field>
      <Button type="submit" variant="outline" disabled={v.reason.length < 3 || save.isPending}>{t("Apply override")}</Button>
    </form>
  );
}

export function RecordDialog({ id, onClose, mode }: { id: number; onClose(): void; mode: "employee" | "staff" }) {
  const me = useAuthStore((s) => s.me);
  const q = useGet<RecordDetail>(`/attendance/${id}/`);
  const r = q.data;
  const { register, handleSubmit, formState: { errors }, reset } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { type: mode === "employee" ? "DISPUTE" : "WRONG_TIME", reason: "" } });
  const send = useSend<Form>("POST", () => (mode === "employee" ? `/attendance/${id}/dispute/` : `/attendance/${id}/correction/`), ["/attendance"], t("Request submitted for review"));
  const approve = useSend<{ approve: boolean }>("POST", `/attendance/${id}/approve/`, ["/attendance"], t("Saved"));
  const confirm = useSend<{ action: string }>("POST", `/attendance/${id}/confirm/`, ["/attendance"], t("Confirmed"));

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{r ? `${r.employee_name} · ${fmtDate(r.work_date)}` : t("Attendance")}</DialogTitle>
          <DialogDescription>{t("Calculated by the server from validated GPS events, approvals and corrections.")}</DialogDescription>
        </DialogHeader>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {r && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div><div className="text-muted-foreground">{t("Status")}</div><StatusBadge status={r.status} /></div>
                <div><div className="text-muted-foreground">{t("Scheduled")}</div>{fmtTime(r.scheduled_start, r.timezone)}–{fmtTime(r.scheduled_end, r.timezone)}</div>
                <div><div className="text-muted-foreground">{t("Check-in / out")}</div>{fmtTime(r.actual_check_in, r.timezone)} – {fmtTime(r.actual_check_out, r.timezone)}</div>
                <div><div className="text-muted-foreground">{t("Worked")}</div>{fmtMinutes(r.worked_minutes)}</div>
                <div><div className="text-muted-foreground">{t("Late")}</div>{t("{n} min", { n: r.late_minutes })}</div>
                <div><div className="text-muted-foreground">{t("Early leave")}</div>{t("{n} min", { n: r.early_departure_minutes })}</div>
                <div><div className="text-muted-foreground">{t("Breaks")}</div>{fmtMinutes(r.break_minutes)}</div>
                <div><div className="text-muted-foreground">{t("Overtime")}</div>{fmtMinutes(r.overtime_minutes)}</div>
                <div><div className="text-muted-foreground">{t("Early arrival")}</div>{t("{n} min", { n: r.early_arrival_minutes })}</div>
                <div><div className="text-muted-foreground">{t("Presence")}</div>{fmtMinutes(r.presence_minutes)}</div>
                <div><div className="text-muted-foreground">{t("Temporary exits")}</div>{fmtMinutes(r.temporary_exit_minutes)}</div>
                <div><div className="text-muted-foreground">{t("Payable")}</div>{fmtMinutes(r.worked_minutes)}</div>
              </div>
              <Table>
                <THead><TR><TH>{t("In")}</TH><TH>{t("Out")}</TH><TH>{t("Duration")}</TH><TH>{t("State")}</TH><TH>{t("Breaks")}</TH></TR></THead>
                <TBody>
                  {r.sessions.map((s) => (
                    <TR key={s.id}>
                      <TD>{fmtTime(s.check_in_at, r.timezone)}<div className="text-xs text-muted-foreground">{titleCase(s.detection_method)} · {titleCase(s.confirmation)}{s.check_in_accuracy_m != null ? ` · ${fmtMeters(s.check_in_accuracy_m, true)}` : ""}</div></TD>
                      <TD>{fmtTime(s.check_out_at, r.timezone)}{s.close_reason && <div className="text-xs text-muted-foreground">{titleCase(s.close_reason)}</div>}</TD>
                      <TD>{s.duration_minutes != null ? fmtMinutes(s.duration_minutes) : "—"}</TD>
                      <TD><Badge tone={s.status === "OPEN" ? "success" : s.status === "AWAY" ? "info" : s.status === "PENDING_CHECKOUT" ? "warning" : "neutral"}>{titleCase(s.status)}</Badge></TD>
                      <TD className="text-xs text-muted-foreground">{s.breaks.map((b) => <div key={b.id}>{titleCase(b.type)} {fmtTime(b.started_at, r.timezone)}–{b.outcome === "RETURNED" ? fmtTime(b.ended_at, r.timezone) : titleCase(b.outcome)}{b.is_paid ? ` · ${t("counted")}` : ""}</div>)}</TD>
                    </TR>
                  ))}
                  {r.sessions.length === 0 && <TR><TD colSpan={5} className="text-muted-foreground">{t("No sessions recorded.")}</TD></TR>}
                </TBody>
              </Table>

              {mode === "staff" && isHR(me) && r.sessions.length > 0 && <SessionOverride sessions={r.sessions} tz={r.timezone} />}
              {mode === "staff" && r.pending_confirmation && (
                <div className="flex gap-2">
                  <Button onClick={() => approve.mutate({ approve: true })} disabled={approve.isPending}>{t("Approve attendance")}</Button>
                  <Button variant="outline" onClick={() => approve.mutate({ approve: false })} disabled={approve.isPending}>{t("Reject")}</Button>
                </div>
              )}
              {mode === "employee" && r.pending_checkout && (
                <Button onClick={() => confirm.mutate({ action: "CONFIRM" })} disabled={confirm.isPending}>{t("Confirm suggested check-out")}</Button>
              )}

              {send.isSuccess ? (
                <p className="rounded-lg bg-primary/10 p-3 text-sm text-accent-foreground dark:text-primary">{t("Submitted. A reviewer will approve or reject it; you'll get a notification.")}</p>
              ) : (
                <form className="space-y-3 rounded-lg border p-4" onSubmit={handleSubmit((v) => send.mutate({ ...v, requested_check_in: iso(v.requested_check_in), requested_check_out: iso(v.requested_check_out) } as never, { onSuccess: () => reset() }))}>
                  <div className="font-semibold">{mode === "employee" ? t("Dispute or correct this day") : t("Manual correction")}</div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label={t("Type")}><NativeSelect {...register("type")}>
                      {(mode === "employee" ? ["DISPUTE", "WRONG_TIME", "MISSING_CHECK_IN", "MISSING_CHECK_OUT", "OTHER"] : ["WRONG_TIME", "MISSING_CHECK_IN", "MISSING_CHECK_OUT", "DISPUTE", "OTHER"]).map((x) => <option key={x} value={x}>{titleCase(x)}</option>)}
                    </NativeSelect></Field>
                    <Field label={t("Correct check-in")} error={errors.requested_check_in?.message}><Input type="datetime-local" {...register("requested_check_in")} /></Field>
                    <Field label={t("Correct check-out")} error={errors.requested_check_out?.message}><Input type="datetime-local" {...register("requested_check_out")} /></Field>
                  </div>
                  <Field label={t("Reason")} error={errors.reason?.message}><Textarea rows={2} {...register("reason")} /></Field>
                  <Button type="submit" disabled={send.isPending}>{t("Submit for review")}</Button>
                  <p className="text-xs text-muted-foreground">{t("Times are in your browser's timezone. Totals only change after approval (audit logged). Last updated {date}.", { date: fmtDateTime(new Date().toISOString()) })}</p>
                </form>
              )}
            </div>
          )}
        </QueryState>
      </DialogContent>
    </Dialog>
  );
}
