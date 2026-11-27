import { zodResolver } from "@hookform/resolvers/zod";
import { Copy, Pencil, Plus, Search, UserMinus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { Department, Employee, Office, Page, Role } from "@/api/types";
import { EmptyState, Field, PageHeader, QueryState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { titleCase } from "@/lib/format";
import { isAdmin, ROLE_LABEL } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";
import { msg, t } from "@/i18n";

const schema = z.object({
  full_name: z.string().min(2, msg("Name is required")),
  email: z.string().email(msg("Valid email required")),
  employee_code: z.string().min(1, msg("Required")).max(40),
  position: z.string().max(120).optional(),
  department_id: z.string().optional(),
  role: z.enum(["EMPLOYEE", "MANAGER", "HR", "ACCOUNTANT", "ADMIN"]),
  employment_status: z.enum(["ACTIVE", "PROBATION", "ON_LEAVE", "SUSPENDED"]),
  hired_at: z.string().optional(),
  office_ids: z.array(z.string()),
  managed_department_ids: z.array(z.string()),
});
type Form = z.infer<typeof schema>;

function EmployeeDialog({ emp, onClose }: { emp: Employee | null; onClose(): void }) {
  const me = useAuthStore((s) => s.me);
  const depts = useGet<Department[]>("/departments/");
  const offices = useGet<Office[]>("/offices/");
  const [invite, setInvite] = useState<string | null>(null);
  const { register, handleSubmit, watch, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: emp ? {
      full_name: emp.full_name, email: emp.email, employee_code: emp.employee_code, position: emp.position ?? "", department_id: emp.department_id?.toString() ?? "",
      role: emp.role === "OWNER" ? "ADMIN" : emp.role, employment_status: (emp.employment_status === "TERMINATED" ? "ACTIVE" : emp.employment_status) as Form["employment_status"],
      hired_at: emp.hired_at ?? "", office_ids: emp.office_ids.map(String), managed_department_ids: emp.managed_department_ids.map(String),
    } : { role: "EMPLOYEE", employment_status: "ACTIVE", office_ids: offices.data?.length === 1 ? [String(offices.data[0].id)] : [], managed_department_ids: [] },
  });
  const save = useSend<object, Employee>(emp ? "PATCH" : "POST", emp ? `/employees/${emp.id}/` : "/employees/", ["/employees"], emp ? t("Employee updated") : t("Invitation created"));
  const role = watch("role");
  const submit = (v: Form) => {
    const body = {
      ...v, position: v.position || null, hired_at: v.hired_at || null, department_id: v.department_id ? Number(v.department_id) : null,
      office_ids: v.office_ids.map(Number), managed_department_ids: v.managed_department_ids.map(Number),
      primary_office_id: v.office_ids.length ? Number(v.office_ids[0]) : null,
    };
    if (emp) delete (body as Partial<typeof body>).email;
    save.mutate(body, { onSuccess: (res) => (res.invite_url ? setInvite(res.invite_url) : onClose()) });
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>{emp ? t("Edit employee") : t("Invite employee")}</DialogTitle>
          <DialogDescription>{emp ? emp.email : t("They'll receive an invitation link to set a password (or sign in with Google).")}</DialogDescription></DialogHeader>
        {invite ? (
          <div className="space-y-3">
            <p className="text-sm">{t("Invitation created. If email isn't configured, share this one-time link securely:")}</p>
            <div className="flex gap-2"><Input readOnly value={invite} className="font-mono text-xs" /><Button variant="outline" onClick={() => { void navigator.clipboard.writeText(invite); toast.success(t("Copied")); }}><Copy /></Button></div>
            <DialogFooter><Button onClick={onClose}>{t("Done")}</Button></DialogFooter>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={handleSubmit(submit)}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Full name")} error={errors.full_name?.message}><Input {...register("full_name")} /></Field>
              <Field label={t("Email")} error={errors.email?.message}><Input type="email" disabled={!!emp} {...register("email")} /></Field>
              <Field label={t("Employee code")} error={errors.employee_code?.message}><Input disabled={!!emp} {...register("employee_code")} /></Field>
              <Field label={t("Position")}><Input {...register("position")} /></Field>
              <Field label={t("Department")}><NativeSelect {...register("department_id")}><option value="">—</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</NativeSelect></Field>
              <Field label={t("Role")}><NativeSelect {...register("role")} disabled={emp?.role === "OWNER"}>
                {(["EMPLOYEE", "MANAGER", "HR", "ACCOUNTANT", ...(isAdmin(me) ? ["ADMIN"] : [])] as const).map((r) => <option key={r} value={r}>{ROLE_LABEL[r as Role]}</option>)}
              </NativeSelect></Field>
              <Field label={t("Employment status")}><NativeSelect {...register("employment_status")}>{["ACTIVE", "PROBATION", "ON_LEAVE", "SUSPENDED"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</NativeSelect></Field>
              <Field label={t("Hired on")}><Input type="date" {...register("hired_at")} /></Field>
            </div>
            <fieldset className="space-y-1.5"><legend className="text-sm font-medium">{t("Assigned offices (geofences used for check-in)")}</legend>
              <div className="flex flex-wrap gap-3">{offices.data?.map((o) => <label key={o.id} className="flex items-center gap-1.5 text-sm"><input type="checkbox" value={o.id} {...register("office_ids")} className="accent-[var(--color-primary)]" />{o.name}</label>)}</div>
            </fieldset>
            {role === "MANAGER" && (
              <fieldset className="space-y-1.5"><legend className="text-sm font-medium">{t("Manages departments")}</legend>
                <div className="flex flex-wrap gap-3">{depts.data?.map((d) => <label key={d.id} className="flex items-center gap-1.5 text-sm"><input type="checkbox" value={d.id} {...register("managed_department_ids")} className="accent-[var(--color-primary)]" />{d.name}</label>)}</div>
              </fieldset>
            )}
            <DialogFooter><Button type="button" variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{emp ? t("Save") : t("Send invitation")}</Button></DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function Employees() {
  const [search, setSearch] = useState("");
  const [dept, setDept] = useState("");
  const [active, setActive] = useState("true");
  const [edit, setEdit] = useState<Employee | null | "new">(null);
  const q = useGet<Page<Employee>>("/employees/", { q: search, department_id: dept || undefined, active: active || undefined, page_size: 200 });
  const depts = useGet<Department[]>("/departments/");
  const remove = useSend<{ id: number }>("DELETE", (b) => `/employees/${b.id}/`, ["/employees"], t("Employee deactivated"));
  const resend = useSend<{ id: number }, Employee>("POST", (b) => `/employees/${b.id}/resend-invite/`, [], t("New invitation link created"));
  return (
    <>
      <PageHeader title={t("Employees")} description={t("Invite people, assign offices and roles. Deactivated employees keep their attendance history.")} actions={<Button onClick={() => setEdit("new")}><Plus />{t("Invite employee")}</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative"><Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" /><Input placeholder={t("Search name or code")} className="w-64 pl-8" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <NativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="w-auto"><option value="">{t("All departments")}</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</NativeSelect>
        <NativeSelect value={active} onChange={(e) => setActive(e.target.value)} className="w-auto"><option value="true">{t("Active")}</option><option value="false">{t("Inactive")}</option><option value="">{t("All")}</option></NativeSelect>
      </div>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error} rows={6}>
          {q.data?.items.length ? (
            <Table>
              <THead><TR><TH>{t("Name")}</TH><TH>{t("Code")}</TH><TH>{t("Department")}</TH><TH>{t("Role")}</TH><TH>{t("Status")}</TH><TH>{t("Location")}</TH><TH /></TR></THead>
              <TBody>{q.data.items.map((e) => (
                <TR key={e.id}>
                  <TD><div className="font-medium">{e.full_name}</div><div className="text-xs text-muted-foreground">{e.email}{e.position ? ` · ${e.position}` : ""}</div></TD>
                  <TD className="font-mono text-xs">{e.employee_code}</TD>
                  <TD>{e.department_name ?? "—"}</TD>
                  <TD>{ROLE_LABEL[e.role]}</TD>
                  <TD>{!e.is_active ? <Badge>{t("Inactive")}</Badge> : e.invite_pending ? <Badge tone="warning">{t("Invited")}</Badge> : <Badge tone="success">{titleCase(e.employment_status)}</Badge>}</TD>
                  <TD>{e.consent_granted ? <Badge tone="success">{t("Consent given")}</Badge> : <Badge>{t("No consent")}</Badge>}</TD>
                  <TD className="text-right"><div className="flex justify-end gap-1">
                    {e.invite_pending && e.is_active && <Button size="sm" variant="ghost" onClick={() => resend.mutate({ id: e.id }, { onSuccess: (r) => r.invite_url && navigator.clipboard?.writeText(r.invite_url) })}>{t("Resend")}</Button>}
                    <Button size="icon" variant="ghost" aria-label={t("Edit {name}", { name: e.full_name })} onClick={() => setEdit(e)}><Pencil /></Button>
                    {e.is_active && e.role !== "OWNER" && <Button size="icon" variant="ghost" aria-label={t("Deactivate {name}", { name: e.full_name })} onClick={() => confirm(t("Deactivate {name}? Their login is revoked; history is kept.", { name: e.full_name })) && remove.mutate({ id: e.id })}><UserMinus /></Button>}
                  </div></TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("No employees found")}>{t("Invite your first employee to start tracking attendance.")}</EmptyState>}
        </QueryState>
      </Card>
      {edit && <EmployeeDialog emp={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}
