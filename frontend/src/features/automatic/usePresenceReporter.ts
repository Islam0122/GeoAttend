import { useCallback, useRef } from "react";
import { api } from "@/api/client";
import { reportPermission } from "@/features/session";
import { deviceId, newEventUuid } from "@/lib/device";
import type { Fix } from "@/lib/geo";

/**
 * Manual mode: forwards fixes the check-in screen already obtained to the server as presence checks
 * (at most one per interval, only fresh fixes, only during the working window with consent), so monitoring
 * shows a server-validated zone instead of "unknown". No additional GPS requests are made.
 */
export function usePresenceReporter({ enabled, intervalSeconds }: { enabled: boolean; intervalSeconds: number }) {
  const lastSent = useRef(0);
  const permissionReported = useRef(false);
  return useCallback((fix: Fix) => {
    if (!permissionReported.current) {
      permissionReported.current = true;
      void reportPermission("GRANTED_WHEN_IN_USE");
    }
    if (!enabled || !navigator.onLine || document.visibilityState === "hidden") return;
    if (Date.now() - fix.timestamp > intervalSeconds * 2000 || fix.timestamp - lastSent.current < (intervalSeconds - 2) * 1000) return;
    lastSent.current = fix.timestamp;
    void api("/attendance/presence-check/", { body: {
      event_uuid: newEventUuid(), device_id: deviceId(), latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy,
      timestamp: new Date(fix.timestamp).toISOString(), permission_status: "GRANTED_WHEN_IN_USE" } }).catch(() => undefined);
  }, [enabled, intervalSeconds]);
}
