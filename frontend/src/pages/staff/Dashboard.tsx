import { AlarmClock, CalendarX2, Clock3, Hourglass, Palmtree, UserCheck, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useGet } from "@/api/hooks";
import type { Dashboard as DashboardData, Department, DeptRow, TeamRow, TrendPoint } from "@/api/types";
import { EmptyState, PageHeader, QueryState, StatCard, StatusBadge } from "@/components/common";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { addDays, fmtHours, fmtMinutes, fmtTime, todayIn } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

const C = { primary: "var(--color-primary)", warn: "var(--color-warning)", danger: "var(--color-destructive)", sky: "#0ea5e9", muted: "#94a3b8" };
const axis = { fontSize: 12, stroke: "var(--color-muted-foreground)" };

function ChartCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle>{description && <CardDescription>{description}</CardDescription>}</CardHeader>
      <CardContent className="h-64">{children}</CardContent>
    </Card>
  );
}

export function Dashboard({ scope }: { scope: "org" | "team" }) {
  const tz = useAuthStore((s) => s.me!.organization_timezone);
  const today = todayIn(tz);
  const [day, setDay] = useState(today);
  const [dept, setDept] = useState("");
  const depts = useGet<Department[]>("/departments/");
  const k = useGet<DashboardData>("/attendance/dashboard/", { date: day, department_id: dept || undefined }, { refetchInterval: day === today ? 60_000 : false });
  const trend = useGet<{ series: TrendPoint[] }>("/reports/trends/", { start: addDays(day, -29), end: day, department_id: dept || undefined });
  const deptPerf = useGet<{ rows: DeptRow[] }>("/reports/departments/", { start: addDays(day, -29), end: day });
  const team = useGet<TeamRow[]>(day === today ? "/attendance/today/team/" : null, { department_id: dept || undefined }, { refetchInterval: 60_000 });

  const series = trend.data?.series ?? [];
  const weekly = useMemo(() => {
    const byWeek = new Map<string, { week: string; present: number; late: number; absent: number }>();
    for (const p of series) {
      const d = new Date(`${p.date}T12:00:00Z`);
      d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      const key = d.toISOString().slice(5, 10);
      const w = byWeek.get(key) ?? { week: key, present: 0, late: 0, absent: 0 };
      w.present += p.present; w.late += p.late; w.absent += p.absent;
      byWeek.set(key, w);
    }
    return [...byWeek.values()];
  }, [series]);
  const s = k.data;

  return (
    <>
      <PageHeader title={scope === "team" ? "Team dashboard" : "Dashboard"} description={`Attendance analytics · ${tz}${day === today ? " · live" : ""}`}
        actions={<>
          <Input type="date" value={day} max={today} onChange={(e) => setDay(e.target.value || today)} className="w-auto" aria-label="Date" />
          <NativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="w-auto min-w-40" aria-label="Department">
            <option value="">All departments</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </NativeSelect>
        </>} />
      <QueryState isLoading={k.isLoading} error={k.error} rows={2}>
        {s && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <StatCard label="Total employees" value={s.total_employees} hint={`${s.scheduled_today} scheduled`} icon={<Users />} />
            <StatCard label="Present" value={s.present} accent hint={s.inside_office ? `${s.inside_office} inside now` : undefined} icon={<UserCheck />} />
            <StatCard label="Late" value={s.late} icon={<AlarmClock />} />
            <StatCard label="Absent" value={s.absent} hint={s.location_unavailable ? `+${s.location_unavailable} location unavailable` : s.is_today ? "so far" : undefined} icon={<CalendarX2 />} />
            <StatCard label="On leave" value={s.on_leave} icon={<Palmtree />} />
            <StatCard label="Avg working hours" value={fmtHours(s.avg_working_minutes)} icon={<Clock3 />} />
            <StatCard label="Overtime" value={fmtHours(s.overtime_minutes)} hint={s.unconfirmed ? `${s.unconfirmed} awaiting approval` : undefined} icon={<Hourglass />} />
          </div>
        )}
      </QueryState>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <ChartCard title="Attendance trend" description="Present, late and absent — last 30 days">
          <ResponsiveContainer>
            <AreaChart data={series}>
              <defs><linearGradient id="gp" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.primary} stopOpacity={0.35} /><stop offset="100%" stopColor={C.primary} stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} {...axis} />
              <YAxis allowDecimals={false} width={28} {...axis} />
              <Tooltip contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8 }} />
              <Legend />
              <Area type="monotone" dataKey="present" name="Present" stroke={C.primary} fill="url(#gp)" strokeWidth={2} />
              <Area type="monotone" dataKey="late" name="Late" stroke={C.warn} fill="transparent" strokeWidth={2} />
              <Area type="monotone" dataKey="absent" name="Absent" stroke={C.danger} fill="transparent" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Weekly attendance" description="Totals per week (week starting)">
          <ResponsiveContainer>
            <BarChart data={weekly}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="week" {...axis} /><YAxis allowDecimals={false} width={28} {...axis} />
              <Tooltip contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8 }} /><Legend />
              <Bar dataKey="present" name="Present" fill={C.primary} radius={[4, 4, 0, 0]} />
              <Bar dataKey="late" name="Late" fill={C.warn} radius={[4, 4, 0, 0]} />
              <Bar dataKey="absent" name="Absent" fill={C.danger} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Monthly attendance rate" description="% of recorded days with attendance">
          <ResponsiveContainer>
            <AreaChart data={series.filter((p) => p.attendance_rate != null)}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} {...axis} /><YAxis domain={[0, 100]} unit="%" width={40} {...axis} />
              <Tooltip formatter={(v) => [`${v}%`, "Attendance"]} contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8 }} />
              <Area type="monotone" dataKey="attendance_rate" stroke={C.primary} fill="url(#gp)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Late arrivals" description="Total late minutes per day">
          <ResponsiveContainer>
            <BarChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} {...axis} /><YAxis width={32} {...axis} />
              <Tooltip formatter={(v) => [`${v} min`, "Late"]} contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8 }} />
              <Bar dataKey="late_minutes" fill={C.warn} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <ChartCard title="Department performance" description="Attendance and punctuality rate — last 30 days">
          <ResponsiveContainer>
            <BarChart data={deptPerf.data?.rows ?? []} layout="vertical" margin={{ left: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis type="number" domain={[0, 100]} unit="%" {...axis} /><YAxis type="category" dataKey="department" width={110} {...axis} />
              <Tooltip contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8 }} /><Legend />
              <Bar dataKey="attendance_rate" name="Attendance %" fill={C.primary} radius={[0, 4, 4, 0]} />
              <Bar dataKey="punctuality_rate" name="Punctuality %" fill={C.sky} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <Card>
          <CardHeader><CardTitle>{day === today ? "Scheduled today" : "Pick today to see the live roster"}</CardTitle></CardHeader>
          <QueryState isLoading={team.isLoading} error={team.error}>
            {team.data?.length ? (
              <Table>
                <THead><TR><TH>Employee</TH><TH>Shift</TH><TH>In</TH><TH>Worked</TH><TH>Status</TH></TR></THead>
                <TBody>{team.data.map((r) => (
                  <TR key={r.employee_id}>
                    <TD><div className="font-medium">{r.employee_name}</div><div className="text-xs text-muted-foreground">{r.department_name ?? "—"}</div></TD>
                    <TD className="whitespace-nowrap">{fmtTime(r.scheduled_start, tz)}–{fmtTime(r.scheduled_end, tz)}</TD>
                    <TD>{fmtTime(r.actual_check_in, tz)}{r.late_minutes > 0 && <div className="text-xs text-amber-600">+{r.late_minutes}m</div>}</TD>
                    <TD>{fmtMinutes(r.worked_minutes)}</TD>
                    <TD><StatusBadge status={r.status} /></TD>
                  </TR>
                ))}</TBody>
              </Table>
            ) : <EmptyState title={day === today ? "Nobody scheduled today" : "Historical day"}>{day === today ? "Assign work schedules to employees." : "Use Attendance or Reports for past days."}</EmptyState>}
          </QueryState>
        </Card>
      </div>
    </>
  );
}
