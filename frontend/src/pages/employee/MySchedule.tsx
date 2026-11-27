import { useGet } from "@/api/hooks";
import type { Shift } from "@/api/types";
import { EmptyState, PageHeader, QueryState } from "@/components/common";
import { Card } from "@/components/ui/card";
import { fmtDate, fmtTime } from "@/lib/format";
import { t } from "@/i18n";

export function MySchedule() {
  const q = useGet<Shift[]>("/schedules/me/", { days: 21 });
  return (
    <>
      <PageHeader title={t("My schedule")} description={t("Upcoming shifts for the next three weeks. Times are shown in your office timezone.")} />
      <QueryState isLoading={q.isLoading} error={q.error}>
        {q.data?.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {q.data.map((s) => (
              <Card key={s.work_date} className="p-4">
                <div className="text-sm font-semibold">{fmtDate(s.work_date)}</div>
                <div className="mt-1 text-2xl font-bold tabular-nums">{fmtTime(s.start, s.timezone)} – {fmtTime(s.end, s.timezone)}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {s.break_start ? `${t("Break")} ${fmtTime(s.break_start, s.timezone)}–${fmtTime(s.break_end, s.timezone)} · ` : ""}{s.timezone}
                </div>
              </Card>
            ))}
          </div>
        ) : <Card><EmptyState title={t("No upcoming shifts")}>{t("Ask HR to assign you a work schedule.")}</EmptyState></Card>}
      </QueryState>
    </>
  );
}
