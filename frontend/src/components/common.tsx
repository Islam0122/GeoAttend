import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { STATUS_LABEL, STATUS_TONE, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_LABEL[status] ?? titleCase(status)}</Badge>;
}

export function StatCard({ label, value, hint, icon, accent }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; accent?: boolean }) {
  return (
    <Card className={cn("p-4", accent && "border-primary/30 bg-gradient-to-br from-primary/10 to-transparent")}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium text-muted-foreground">{label}</div>
        {icon && <div className={cn("rounded-lg p-1.5 [&_svg]:size-4", accent ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground")}>{icon}</div>}
      </div>
      <div className="mt-2 text-2xl font-bold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center">
      <div className="rounded-full bg-muted p-3 text-muted-foreground [&_svg]:size-5">{icon ?? <Inbox />}</div>
      <div className="font-semibold">{title}</div>
      {children && <div className="max-w-sm text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function QueryState({ isLoading, error, children, rows = 3 }: { isLoading: boolean; error: unknown; children: ReactNode; rows?: number }) {
  if (isLoading)
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
      </div>
    );
  if (error)
    return (
      <div role="alert" className="flex items-center gap-2 p-4 text-sm text-destructive">
        <AlertCircle className="size-4" /> {(error as Error).message}
      </div>
    );
  return <>{children}</>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin", className)} aria-hidden />;
}

export function Field({ label, error, children, hint }: { label: string; error?: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-muted-foreground">{hint}</span>}
      {error && <span className="block text-xs font-medium text-destructive">{t(error)}</span>}
    </label>
  );
}
