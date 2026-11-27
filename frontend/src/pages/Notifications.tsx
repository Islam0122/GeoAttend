import { useGet, useSend } from "@/api/hooks";
import type { AppNotification } from "@/api/types";
import { EmptyState, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Notifications() {
  const q = useGet<AppNotification[]>("/notifications/");
  const read = useSend<{ id: number }>("POST", (b) => `/notifications/${b.id}/read/`, ["/notifications"]);
  return (
    <>
      <PageHeader title="Notifications" />
      <Card className="divide-y">
        <QueryState isLoading={q.isLoading} error={q.error}>
          {q.data?.length ? q.data.map((n) => (
            <div key={n.id} className={cn("flex items-start gap-3 p-4", !n.read_at && "bg-primary/5")}>
              <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-primary")} />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{n.title}</div>
                <div className="text-sm text-muted-foreground">{n.body}</div>
                <div className="mt-1 text-xs text-muted-foreground">{ago(n.created_at)}</div>
              </div>
              {!n.read_at && <Button size="sm" variant="ghost" onClick={() => read.mutate({ id: n.id })}>Mark read</Button>}
            </div>
          )) : <EmptyState title="You're all caught up" />}
        </QueryState>
      </Card>
    </>
  );
}
