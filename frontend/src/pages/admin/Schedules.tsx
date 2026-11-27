import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { Assignment, Department, Employee, Page, Schedule } from "@/api/types";
import { EmptyState, Field, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { WEEKDAYS } from "@/lib/format";
import { msg, t } from "@/i18n";

const day = z.object({ weekday: z.number(), is_working_day: z.boolean(), start_time: z.string(), end_time: z.string(), break_start: z.string(), break_end: z.string() })
  .refine((d) => !d.is_working_day || (d.start_time && d.end_time && d.start_time !== d.end_time), { message: msg("Start and end required"), path: ["end_time"] })
  .refine((d) => !!d.break_start === !!d.break_end, { message: msg("Both break times or none"), path: ["break_end"] });
const schema = z.object({
  name: z.string().min(1, msg("Required")),
  grace_period_minutes: z.coerce.number().min(0).max(240),
  early_leave_grace_minutes: z.coerce.number().min(0).max(240),
  overtime_threshold_minutes: z.coerce.number().min(0).max(600),
  days: z.array(day),
});
type Form = z.input<typeof schema>;
type Out = z.output<typeof schema>;
const t5 = (v: string | null) => (v ? v.slice(0, 5) : "");

function ScheduleDialog({ s, onClose }: { s: Schedule | null; onClose(): void }) {
  const def = (wd: number) => {
    const d = s?.days.find((x) => x.weekday === wd);
    if (s) return { weekday: wd, is_working_day: !!d?.is_working_day, start_time: t5(d?.start_time ?? null), end_time: t5(d?.end_time ?? null), break_start: t5(d?.break_start ?? null), break_end: t5(d?.break_end ?? null) };
    return { weekday: wd, is_working_day: wd < 5, start_time: wd < 5 ? "09:00" : "", end_time: wd < 5 ? "18:00" : "", break_start: wd < 5 ? "13:00" : "", break_end: wd < 5 ? "14:00" : "" };
  };
  const { register, control, handleSubmit, watch, formState: { errors } } = useForm<Form, unknown, Out>({
    resolver: zodResolver(schema),
    defaultValues: { name: s?.name ?? "", grace_period_minutes: s?.grace_period_minutes ?? 5, early_leave_grace_minutes: s?.early_leave_grace_minutes ?? 0, overtime_threshold_minutes: s?.overtime_threshold_minutes ?? 0, days: [0, 1, 2, 3, 4, 5, 6].map(def) },
  });
  const { fields } = useFieldArray({ control, name: "days" });
  const save = useSend<object>(s ? "PATCH" : "POST", s ? `/schedules/${s.id}/` : "/schedules/", ["/schedules"], t("Schedule saved"));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader><DialogTitle>{s ? t("Edit {name}", { name: s.name }) : t("New work schedule")}</DialogTitle></DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((v) => save.mutate({ ...v, days: v.days.filter((d) => d.is_working_day).map((d) => ({ ...d, break_start: d.break_start || null, break_end: d.break_end || null })) }, { onSuccess: onClose }))}>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label={t("Name")} error={errors.name?.message}><Input {...register("name")} /></Field>
            <Field label={t("Grace period (min)")}><Input type="number" {...register("grace_period_minutes")} /></Field>
            <Field label={t("Early-leave grace (min)")}><Input type="number" {...register("early_leave_grace_minutes")} /></Field>
            <Field label={t("Overtime after (min)")}><Input type="number" {...register("overtime_threshold_minutes")} /></Field>
          </div>
          <Table>
            <THead><TR><TH>{t("Day")}</TH><TH>{t("Works")}</TH><TH>{t("Start")}</TH><TH>{t("End")}</TH><TH>{t("Break from")}</TH><TH>{t("Break to")}</TH></TR></THead>
            <TBody>{fields.map((f, i) => {
              const on = watch(`days.${i}.is_working_day`);
              const err = errors.days?.[i];
              return (
                <TR key={f.id}>
                  <TD className="font-medium">{WEEKDAYS[i]}</TD>
                  <TD><input type="checkbox" {...register(`days.${i}.is_working_day`)} className="size-4 accent-[var(--color-primary)]" aria-label={t("{day} is a working day", { day: WEEKDAYS[i] })} /></TD>
                  {(["start_time", "end_time", "break_start", "break_end"] as const).map((k) => (
                    <TD key={k}><Input type="time" disabled={!on} {...register(`days.${i}.${k}`)} className="h-8 w-28" aria-invalid={!!err?.[k]} /></TD>
                  ))}
                </TR>
              );
            })}</TBody>
          </Table>
          <p className="text-xs text-muted-foreground">{t("An end time earlier than the start time is an overnight shift (attributed to the start day).")}</p>
          <DialogFooter><Button type="button" variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{t("Save")}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function Schedules() {
  const q = useGet<Schedule[]>("/schedules/");
  const assignments = useGet<Assignment[]>("/schedules/assignments/");
  const emps = useGet<Page<Employee>>("/employees/", { page_size: 500, active: true });
  const depts = useGet<Department[]>("/departments/");
  const [edit, setEdit] = useState<Schedule | null | "new">(null);
  const [a, setA] = useState({ schedule_id: "", target: "employee", target_id: "", effective_from: new Date().toISOString().slice(0, 10) });
  const assign = useSend<object>("POST", "/schedules/assign/", ["/schedules"], t("Schedule assigned"));
  const unassign = useSend<{ id: number }>("DELETE", (b) => `/schedules/assignments/${b.id}/`, ["/schedules"], t("Assignment removed"));
  const name = (as: Assignment) => as.employee_id ? emps.data?.items.find((e) => e.id === as.employee_id)?.full_name : `${depts.data?.find((d) => d.id === as.department_id)?.name ?? "?"} (${t("department")})`;

  return (
    <>
      <PageHeader title={t("Work schedules")} description={t("Employee assignments override department assignments.")} actions={<Button onClick={() => setEdit("new")}><Plus />{t("New schedule")}</Button>} />
      <QueryState isLoading={q.isLoading} error={q.error}>
        <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data?.map((s) => (
            <Card key={s.id}>
              <CardHeader className="flex-row items-center justify-between"><CardTitle>{s.name}</CardTitle><Button size="icon" variant="ghost" aria-label={t("Edit {name}", { name: s.name })} onClick={() => setEdit(s)}><Pencil /></Button></CardHeader>
              <CardContent className="space-y-1 text-sm">
                {s.days.filter((d) => d.is_working_day).map((d) => <div key={d.weekday} className="flex justify-between"><span className="text-muted-foreground">{WEEKDAYS[d.weekday]}</span><span>{t5(d.start_time)}–{t5(d.end_time)}{d.break_start ? ` · ${t("break")} ${t5(d.break_start)}–${t5(d.break_end)}` : ""}</span></div>)}
                <div className="pt-2 text-xs text-muted-foreground">{t("Grace {g} min · overtime after {o} min", { g: s.grace_period_minutes, o: s.overtime_threshold_minutes })}</div>
              </CardContent>
            </Card>
          ))}
          {q.data?.length === 0 && <Card className="md:col-span-2"><EmptyState title={t("No schedules yet")} /></Card>}
        </div>
      </QueryState>
      <Card>
        <CardHeader><CardTitle>{t("Assignments")}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); assign.mutate({ schedule_id: Number(a.schedule_id), effective_from: a.effective_from, [a.target === "employee" ? "employee_id" : "department_id"]: Number(a.target_id) }); }}>
            <NativeSelect value={a.schedule_id} onChange={(e) => setA({ ...a, schedule_id: e.target.value })} className="w-auto" required aria-label={t("Schedule")}><option value="">{t("Schedule…")}</option>{q.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</NativeSelect>
            <NativeSelect value={a.target} onChange={(e) => setA({ ...a, target: e.target.value, target_id: "" })} className="w-auto" aria-label={t("Assign to")}><option value="employee">{t("Employee")}</option><option value="department">{t("Department")}</option></NativeSelect>
            <NativeSelect value={a.target_id} onChange={(e) => setA({ ...a, target_id: e.target.value })} className="w-auto" required aria-label={t("Target")}>
              <option value="">{t("Select…")}</option>{a.target === "employee" ? emps.data?.items.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>) : depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </NativeSelect>
            <Input type="date" value={a.effective_from} onChange={(e) => setA({ ...a, effective_from: e.target.value })} className="w-auto" aria-label={t("Effective from")} />
            <Button type="submit" disabled={assign.isPending}>{t("Assign")}</Button>
          </form>
          <Table>
            <THead><TR><TH>{t("Assigned to")}</TH><TH>{t("Schedule")}</TH><TH>{t("From")}</TH><TH>{t("Until")}</TH><TH /></TR></THead>
            <TBody>{assignments.data?.map((as) => (
              <TR key={as.id}><TD className="font-medium">{name(as)}</TD><TD>{q.data?.find((s) => s.id === as.schedule_id)?.name}</TD><TD>{as.effective_from}</TD><TD>{as.effective_to ?? "—"}</TD>
                <TD className="text-right"><Button size="icon" variant="ghost" aria-label={t("Remove assignment")} onClick={() => unassign.mutate({ id: as.id })}><Trash2 /></Button></TD></TR>
            ))}</TBody>
          </Table>
        </CardContent>
      </Card>
      {edit && <ScheduleDialog s={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}
