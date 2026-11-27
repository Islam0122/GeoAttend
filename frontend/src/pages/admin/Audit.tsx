import { useState } from "react";
import { useGet } from "@/api/hooks";
import type { AuditEntry, Page } from "@/api/types";
import { EmptyState, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/format";

export function Audit() {
  const [page, setPage] = useState(1);
  const q = useGet<Page<AuditEntry>>("/audit-logs/", { page, page_size: 50 });
  return (
    <>
      <PageHeader title="Audit log" description="Security-relevant and configuration changes in this workspace." />
      <Card>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.items.length ? (
            <Table>
              <THead><TR><TH>When</TH><TH>Action</TH><TH>Entity</TH><TH>Actor</TH><TH>Changes</TH></TR></THead>
              <TBody>{q.data.items.map((a) => (
                <TR key={a.id}><TD className="whitespace-nowrap">{fmtDateTime(a.created_at)}</TD><TD className="font-medium">{a.action}</TD><TD>{a.entity_type} #{a.entity_id}</TD><TD>{a.actor_user_id ?? "system"}</TD>
                  <TD className="max-w-md truncate font-mono text-xs text-muted-foreground">{a.changes ? JSON.stringify(a.changes) : ""}</TD></TR>
              ))}</TBody>
            </Table>
          ) : <EmptyState title="No audit entries" />}
        </QueryState>
        <div className="flex justify-end gap-2 border-t p-3">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <Button size="sm" variant="outline" disabled={!q.data || page * 50 >= q.data.total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      </Card>
    </>
  );
}
