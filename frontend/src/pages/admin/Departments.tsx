import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useGet, useSend } from "@/api/hooks";
import type { Department } from "@/api/types";
import { EmptyState, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { t } from "@/i18n";

export function Departments() {
  const q = useGet<Department[]>("/departments/");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  const create = useSend<{ name: string }>("POST", "/departments/", ["/departments"], t("Department created"));
  const rename = useSend<{ id: number; name: string }>("PATCH", (b) => `/departments/${b.id}/`, ["/departments"], t("Department renamed"));
  const del = useSend<{ id: number }>("DELETE", (b) => `/departments/${b.id}/`, ["/departments"], t("Department deleted"));
  return (
    <>
      <PageHeader title={t("Departments")} description={t("Departments scope managers' access and power department reports.")} />
      <Card className="mb-4 p-4">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate({ name: name.trim() }, { onSuccess: () => setName("") }); }}>
          <Input placeholder={t("New department name")} value={name} onChange={(e) => setName(e.target.value)} className="max-w-sm" />
          <Button type="submit" disabled={!name.trim() || create.isPending}><Plus />{t("Add")}</Button>
        </form>
      </Card>
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? (
            <Table>
              <THead><TR><TH>{t("Name")}</TH><TH>{t("Active employees")}</TH><TH /></TR></THead>
              <TBody>{q.data.map((d) => (
                <TR key={d.id}>
                  <TD>{editing?.id === d.id ? (
                    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); rename.mutate(editing, { onSuccess: () => setEditing(null) }); }}>
                      <Input autoFocus value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className="h-8 max-w-xs" /><Button size="sm" type="submit">{t("Save")}</Button>
                    </form>) : <span className="font-medium">{d.name}</span>}</TD>
                  <TD>{d.employee_count}</TD>
                  <TD className="text-right">
                    <Button size="icon" variant="ghost" aria-label={t("Rename {name}", { name: d.name })} onClick={() => setEditing({ id: d.id, name: d.name })}><Pencil /></Button>
                    <Button size="icon" variant="ghost" aria-label={t("Delete {name}", { name: d.name })} disabled={d.employee_count > 0} title={d.employee_count ? t("Move employees first") : undefined} onClick={() => del.mutate({ id: d.id })}><Trash2 /></Button>
                  </TD>
                </TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title={t("No departments yet")} />}
        </QueryState>
      </Card>
    </>
  );
}
