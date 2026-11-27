import { Check } from "lucide-react";
import { useGet, useSend } from "@/api/hooks";
import type { Billing as B } from "@/api/types";
import { PageHeader, QueryState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { t } from "@/i18n";

export function Billing() {
  const me = useAuthStore((s) => s.me);
  const q = useGet<B>("/organizations/current/billing/");
  const change = useSend<{ plan: string }>("PATCH", "/organizations/current/billing/", ["/organizations", "/auth/me"], t("Plan updated"));
  const b = q.data;
  return (
    <>
      <PageHeader title={t("Billing")} description={t("Plan limits are enforced by the API.")} />
      <QueryState isLoading={q.isLoading} error={q.error}>
        {b && (
          <div className="space-y-6">
            <Card>
              <CardContent className="flex flex-wrap items-center gap-6 p-5">
                <div><div className="text-sm text-muted-foreground">{t("Current plan")}</div><div className="text-2xl font-bold">{b.plan.name}</div></div>
                <Usage label={t("Employees")} used={b.usage.employees} max={b.plan.max_employees} />
                <Usage label={t("Offices")} used={b.usage.offices} max={b.plan.max_offices} />
              </CardContent>
            </Card>
            {!b.payment_provider_connected && <Alert tone="info" title={t("No payment provider connected")}>{t("Plan changes take effect immediately and are recorded in the audit log. Connect a payment provider (e.g. Stripe) before charging customers.")}</Alert>}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {b.plans.map((p) => (
                <Card key={p.code} className={cn(p.code === b.plan.code && "border-primary ring-2 ring-primary/20")}>
                  <CardHeader><CardTitle className="flex items-center justify-between">{p.name}{p.code === b.plan.code && <Badge tone="success">{t("Current")}</Badge>}</CardTitle>
                    <div className="text-2xl font-bold">{p.monthly_price_usd == null ? t("Custom") : `$${p.monthly_price_usd}`}<span className="text-sm font-normal text-muted-foreground">{p.monthly_price_usd != null && t("/mo")}</span></div></CardHeader>
                  <CardContent className="space-y-3">
                    <ul className="space-y-1 text-sm">{p.features.map((f) => <li key={f} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-primary" />{t(f)}</li>)}</ul>
                    {p.code !== b.plan.code && <Button className="w-full" variant="outline" disabled={me?.role !== "OWNER" || change.isPending} onClick={() => change.mutate({ plan: p.code })}>{me?.role === "OWNER" ? t("Switch to {plan}", { plan: p.name }) : t("Owner only")}</Button>}
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}

function Usage({ label, used, max }: { label: string; used: number; max: number | null }) {
  const pct = max ? Math.min(100, (used / max) * 100) : 0;
  return (
    <div className="min-w-48 flex-1">
      <div className="flex justify-between text-sm"><span className="text-muted-foreground">{label}</span><span className="font-semibold">{used} / {max ?? "∞"}</span></div>
      <div className="mt-1.5 h-2 rounded-full bg-muted"><div className={cn("h-2 rounded-full", pct > 90 ? "bg-destructive" : "bg-primary")} style={{ width: `${max ? pct : 4}%` }} /></div>
    </div>
  );
}
