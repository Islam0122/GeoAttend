import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { useAuthStore } from "@/stores/auth";
import { useQueueStore } from "@/stores/queue";
import { useUiStore } from "@/stores/ui";

/** Tracks connectivity and retries queued offline check-ins (on reconnect, on focus and every 30 s). */
export function OfflineSync() {
  const setOnline = useUiStore((s) => s.setOnline);
  const authed = useAuthStore((s) => !!s.accessToken);
  const { refresh, sync } = useQueueStore();
  const qc = useQueryClient();

  useEffect(() => {
    const run = async () => {
      if (!navigator.onLine || !useAuthStore.getState().accessToken) return;
      const res = await sync();
      for (const r of res) {
        if (r.ok) toast.success(`Offline ${r.kind === "CHECK_IN" ? "check-in" : "check-out"} synced`, { description: r.message });
        else toast.error(`Offline ${r.kind === "CHECK_IN" ? "check-in" : "check-out"} was rejected`, { description: r.message });
      }
      if (res.length) qc.invalidateQueries();
    };
    const on = () => {
      setOnline(true);
      void run();
    };
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    document.addEventListener("visibilitychange", run);
    void refresh().then(run);
    const id = window.setInterval(run, 30_000);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
      document.removeEventListener("visibilitychange", run);
      window.clearInterval(id);
    };
  }, [authed, qc, refresh, setOnline, sync]);
  return null;
}
