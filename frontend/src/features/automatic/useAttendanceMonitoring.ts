import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { MonitoringEmployee, MonitoringSummary } from "@/api/types";

export type MonitoringFilter = "all" | "inside" | "outside" | "active" | "late" | "temporary_exit" | "stale" | "no_permission" | "no_office";

/** Manager/HR monitoring: server-validated data only (never the manager's own GPS). Polls every 30 s while the
 *  page is open and visible (TanStack Query pauses interval refetching in background tabs and stops on unmount). */
export function useAttendanceMonitoring(filter: MonitoringFilter, officeId?: number | null) {
  const params = { filter, office_id: officeId ?? undefined };
  const rows = useQuery({
    queryKey: ["/monitoring/employees/", params],
    queryFn: () => api<MonitoringEmployee[]>("/monitoring/employees/", { params }),
    refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
  const summary = useQuery({
    queryKey: ["/monitoring/summary/", { office_id: officeId ?? undefined }],
    queryFn: () => api<MonitoringSummary>("/monitoring/summary/", { params: { office_id: officeId ?? undefined } }),
    refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
  return { rows, summary, updatedAt: Math.max(rows.dataUpdatedAt, summary.dataUpdatedAt) || null };
}
