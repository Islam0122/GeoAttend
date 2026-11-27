import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useGet, useSend } from "@/api/hooks";
import type { Employee, LeaveRequest, Page } from "@/api/types";
import { EmptyState, Field, PageHeader, QueryState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime, titleCase } from "@/lib/format";
import { isHR } from "@/lib/roles";
import { useAuthStore } from "@/stores/auth";

const schema = z.object({
  employee_id: z.string().optional(),
  type: z.enum(["LEAVE", "SICK", "BUSINESS_TRIP"]),
  starts_at: z.string().min(1, "Required"),
  ends_at: z.string().min(1, "Required"),
  reason: z.string().max(2000).optional(),
}).refine((v) => v.ends_at > v.starts_at, { path: ["ends_at"], message: "End must be after start" });
type Form = z.infer<typeof schema>;

const TONE = { PENDING: "warning", APPROVED: "success", REJECTED: "neutral" } as const;

/** mode="mine": employee's own requests. mode="review": manager/HR approval queue. */
export function LeaveRequests({ mode }: { mode: "mine" | "review" }) {
  const me = useAuthStore((s) => s.me);
  const [tab, setTab] = useState(mode === "review" ? "PENDING" : "");
  const [open, setOpen] = useState(false);
  const q = useGet<LeaveRequest[]>("/leave-requests/", { mine: mode === "mine", status: tab || undefined });
  const emps = useGet<Page<Employee>>(mode === "review" && isHR(me) ? "/employees/" : null, { page_size: 500, active: true });
  const review = useSend<{ id: number; approve: boolean }>("POST", (b) => `/leave-requests/${b.id}/review/`, ["/leave-requests"], "Request updated");
  const cancel = useSend<{ id: number }>("POST", (b) => `/leave-requests/${b.id}/cancel/`, ["/leave-requests"], "Request cancelled");
  const create = useSend<object>("POST", "/leave-requests/", ["/leave-requests"], mode === "review" ? "Leave registered" : "Request submitted");
  const { register, handleSubmit, formState: { errors }, reset } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { type: "LEAVE" } });

  return (
    <>
      <PageHeader title={mode === "mine" ? "Leave requests" : "Leave management"}
        description={mode === "mine" ? "Request leave, sick days or business trips. Approved leave is never counted as an absence." : "Approve requests. Leave created by HR is approved immediately."}
        actions={<Button onClick={() => setOpen(true)}><Plus />{mode === "mine" ? "New request" : "Register leave"}</Button>} />
      <Tabs value={tab} onValueChange={setTab} className="mb-4">
        <TabsList>
          <TabsTrigger value="">All</TabsTrigger><TabsTrigger value="PENDING">Pending</TabsTrigger><TabsTrigger value="APPROVED">Approved</TabsTrigger><TabsTrigger value="REJECTED">Rejected</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? (
            <Table>
              <THead><TR>{mode === "review" && <TH>Employee</TH>}<TH>Type</TH><TH>From</TH><TH>To</TH><TH>Reason</TH><TH>Status</TH><TH /></TR></THead>
              <TBody>
                {q.data.map((l) => (
                  <TR key={l.id}>
                    {mode === "review" && <TD className="font-medium">{l.employee_name}</TD>}
                    <TD>{titleCase(l.type)}</TD><TD>{fmtDateTime(l.starts_at)}</TD><TD>{fmtDateTime(l.ends_at)}</TD>
                    <TD className="max-w-56 truncate text-muted-foreground">{l.reason}</TD>
                    <TD><Badge tone={TONE[l.status as keyof typeof TONE]}>{titleCase(l.status)}</Badge></TD>
                    <TD className="text-right">
                      {l.status === "PENDING" && mode === "review" && l.employee_id !== me?.employee_id && (
                        <div className="flex justify-end gap-1">
                          <Button size="sm" onClick={() => review.mutate({ id: l.id, approve: true })}>Approve</Button>
                          <Button size="sm" variant="outline" onClick={() => review.mutate({ id: l.id, approve: false })}>Reject</Button>
                        </div>
                      )}
                      {l.status === "PENDING" && mode === "mine" && <Button size="sm" variant="ghost" onClick={() => cancel.mutate({ id: l.id })}>Cancel</Button>}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : <EmptyState title="No requests" />}
        </QueryState>
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{mode === "mine" ? "Request time off" : "Register leave / business trip"}</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={handleSubmit((v) => create.mutate({ ...v, employee_id: v.employee_id ? Number(v.employee_id) : null, starts_at: new Date(v.starts_at).toISOString(), ends_at: new Date(v.ends_at).toISOString() },
            { onSuccess: () => { reset(); setOpen(false); } }))}>
            {mode === "review" && emps.data && (
              <Field label="Employee"><NativeSelect {...register("employee_id")}><option value="">Myself</option>{emps.data.items.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}</NativeSelect></Field>
            )}
            <Field label="Type"><NativeSelect {...register("type")}><option value="LEAVE">Leave / vacation</option><option value="SICK">Sick leave</option><option value="BUSINESS_TRIP">Business trip (counts as work)</option></NativeSelect></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Starts" error={errors.starts_at?.message}><Input type="datetime-local" {...register("starts_at")} /></Field>
              <Field label="Ends" error={errors.ends_at?.message}><Input type="datetime-local" {...register("ends_at")} /></Field>
            </div>
            <Field label="Reason (optional)"><Textarea rows={2} {...register("reason")} /></Field>
            <DialogFooter><Button type="submit" disabled={create.isPending}>Submit</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
