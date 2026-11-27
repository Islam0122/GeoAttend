import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { useGet } from "@/api/hooks";
import type { Plan } from "@/api/types";
import { QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

export function Pricing() {
  const q = useGet<Plan[]>("/plans/");
  return (
    <main className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <h1 className="text-center text-4xl font-extrabold tracking-tight">{t("Simple, per-workspace pricing")}</h1>
      <p className="mx-auto mt-3 max-w-xl text-center text-muted-foreground">{t("Start free. Upgrade when you add offices or people. Limits shown here are the ones the API enforces.")}</p>
      <QueryState isLoading={q.isLoading} error={q.error}>
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {q.data?.map((p) => (
            <Card key={p.code} className={cn("flex flex-col p-6", p.code === "BUSINESS" && "border-primary ring-2 ring-primary/20")}>
              <div className="text-sm font-semibold text-primary">{p.name}</div>
              <div className="mt-2 text-4xl font-extrabold">{p.monthly_price_usd == null ? t("Custom") : `$${p.monthly_price_usd}`}<span className="text-base font-medium text-muted-foreground">{p.monthly_price_usd != null && ` ${t("/mo")}`}</span></div>
              <div className="mt-1 text-sm text-muted-foreground">{p.max_employees ? t("Up to {n} employees", { n: p.max_employees }) : t("Unlimited employees")} · {p.max_offices ? (p.max_offices > 1 ? t("{n} offices", { n: p.max_offices }) : t("1 office")) : t("unlimited offices")}</div>
              <ul className="mt-5 flex-1 space-y-2 text-sm">{p.features.map((f) => <li key={f} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-primary" />{t(f)}</li>)}</ul>
              <Button className="mt-6" variant={p.code === "BUSINESS" ? "default" : "outline"} asChild><Link to="/register">{p.monthly_price_usd == null ? t("Contact sales") : t("Get started")}</Link></Button>
            </Card>
          ))}
        </div>
      </QueryState>
    </main>
  );
}
