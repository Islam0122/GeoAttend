import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useState } from "react";
import { useGet } from "@/api/hooks";
import type { TrendPoint } from "@/api/types";
import { PageHeader, QueryState, StatCard } from "@/components/common";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fmtHours, fmtMinutes, todayIn } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

interface MyReport { start: string; end: string; rows: Record<string, number>[]; trend: TrendPoint[] }

export function MyReports() {
  const tz = useAuthStore((s) => s.me!.organization_timezone);
  const today = todayIn(tz);
  const [range, setRange] = useState({ start: `${today.slice(0, 8)}01`, end: today });
  const q = useGet<MyReport>("/reports/me/", range);
  const s = q.data?.rows[0];
  return (
    <>
      <PageHeader title="My reports" actions={<>
        <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} aria-label="From" className="w-auto" />
        <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} aria-label="To" className="w-auto" />
      </>} />
      <QueryState isLoading={q.isLoading} error={q.error}>
        {s && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard label="Days present" value={s.present_days} accent />
              <StatCard label="Late arrivals" value={s.late_days} hint={`${s.late_minutes} min total`} />
              <StatCard label="Worked" value={fmtHours(s.worked_minutes)} hint={`Overtime ${fmtMinutes(s.overtime_minutes)}`} />
              <StatCard label="Absences / leave" value={`${s.absent_days} / ${s.leave_days}`} />
            </div>
            <Card>
              <CardHeader><CardTitle>Hours per day</CardTitle></CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer>
                  <BarChart data={q.data!.trend.map((p) => ({ ...p, hours: +(p.avg_worked_minutes / 60).toFixed(2) }))}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(8)} fontSize={12} />
                    <YAxis fontSize={12} width={32} />
                    <Tooltip formatter={(v) => [`${v} h`, "Worked"]} />
                    <Bar dataKey="hours" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>
    </>
  );
}
