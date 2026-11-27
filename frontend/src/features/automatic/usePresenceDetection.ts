import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/api/client";
import type { AutomaticPayload } from "@/api/types";
import { deviceId, newEventUuid } from "@/lib/device";
import type { Fix } from "@/lib/geo";
import type { GeolocationState } from "./useGeolocation";

export interface PresenceDetection {
  last: AutomaticPayload | null;
  lastSuccessAt: number | null;
  connectionLost: boolean;
  error: string | null;
  errorCode: string | null;
  sending: boolean;
  checkNow(): Promise<void>;
}

/**
 * Sends the newest GPS fix to POST /attendance/presence-check/ every `intervalSeconds` while enabled,
 * the tab is visible and the browser is online. Each fix is sent at most once and only while it is fresh:
 * old measurements are never replayed as the current position (offline checks are dropped, not queued).
 */
export function usePresenceDetection(geo: GeolocationState, { enabled, intervalSeconds }: { enabled: boolean; intervalSeconds: number }): PresenceDetection {
  const qc = useQueryClient();
  const [last, setLast] = useState<AutomaticPayload | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [connectionLost, setConnectionLost] = useState(typeof navigator !== "undefined" && !navigator.onLine);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const lastSentTs = useRef<number>(0);
  const geoRef = useRef(geo);
  geoRef.current = geo;
  const busy = useRef(false);

  const send = useCallback(async (fix: Fix) => {
    if (busy.current) return;
    busy.current = true;
    setSending(true);
    try {
      const payload = await api<AutomaticPayload>("/attendance/presence-check/", {
        body: { event_uuid: newEventUuid(), device_id: deviceId(), latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy,
                timestamp: new Date(fix.timestamp).toISOString(), permission_status: "GRANTED_WHEN_IN_USE" },
      });
      lastSentTs.current = fix.timestamp;
      setLast(payload);
      setLastSuccessAt(Date.now());
      setConnectionLost(false);
      setError(null);
      setErrorCode(null);
      void qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/attendance/") });
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) setConnectionLost(true);
      else {
        setError((e as Error).message);
        setErrorCode((e as ApiError).code ?? null);
      }
    } finally {
      busy.current = false;
      setSending(false);
    }
  }, [qc]);

  const checkNow = useCallback(async () => {
    if (!navigator.onLine) {
      setConnectionLost(true);
      return;
    }
    const maxAge = intervalSeconds * 2 * 1000;
    let fix = geoRef.current.fix;
    if (!fix || fix.timestamp <= lastSentTs.current || Date.now() - fix.timestamp > maxAge) fix = await geoRef.current.refresh();
    if (fix && fix.timestamp > lastSentTs.current && Date.now() - fix.timestamp <= maxAge) await send(fix);
  }, [intervalSeconds, send]);

  // First fix -> immediate check; then a fixed cadence.
  useEffect(() => {
    if (enabled && geo.fix && lastSentTs.current === 0 && navigator.onLine) void send(geo.fix);
  }, [enabled, geo.fix, send]);

  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      if (document.visibilityState === "visible") void checkNow();
    };
    const id = window.setInterval(tick, intervalSeconds * 1000);
    const online = () => {
      setConnectionLost(false);
      tick();
    };
    const offline = () => setConnectionLost(true);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, [enabled, intervalSeconds, checkNow]);

  return { last, lastSuccessAt, connectionLost, error, errorCode, sending, checkNow };
}
