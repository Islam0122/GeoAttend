import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { AttendancePolicy, AutomaticPayload } from "@/api/types";
import { useGeolocation } from "./useGeolocation";
import { usePresenceDetection } from "./usePresenceDetection";

export type UiState =
  | "INITIALIZING" | "REQUESTING_PERMISSION" | "LOCATION_DETECTED" | "INSIDE_GEOFENCE" | "OUTSIDE_GEOFENCE" | "GPS_INACCURATE"
  | "LOCATION_UNAVAILABLE" | "AUTO_CHECKIN" | "ACTIVE_SESSION" | "TEMPORARY_EXIT" | "SESSION_RESUMED" | "SESSION_COMPLETED"
  | "UNSCHEDULED" | "STALE" | "CONNECTION_LOST" | "NO_OFFICE" | "OUTSIDE_WORKING_WINDOW" | "LOCATION_DENIED" | "UNKNOWN";

export const UI_COPY: Record<UiState, { title: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }> = {
  INITIALIZING: { title: "Initializing…", tone: "neutral" },
  REQUESTING_PERMISSION: { title: "Location permission needed", tone: "info" },
  LOCATION_DETECTED: { title: "Location detected", tone: "info" },
  INSIDE_GEOFENCE: { title: "Inside the office zone", tone: "success" },
  OUTSIDE_GEOFENCE: { title: "Outside the office zone", tone: "neutral" },
  GPS_INACCURATE: { title: "GPS accuracy too low", tone: "warning" },
  LOCATION_UNAVAILABLE: { title: "Location unavailable", tone: "danger" },
  AUTO_CHECKIN: { title: "Work started automatically", tone: "success" },
  ACTIVE_SESSION: { title: "Work session active", tone: "success" },
  TEMPORARY_EXIT: { title: "Temporary exit", tone: "warning" },
  SESSION_RESUMED: { title: "Session resumed", tone: "success" },
  SESSION_COMPLETED: { title: "Work session completed", tone: "neutral" },
  UNSCHEDULED: { title: "No scheduled shift", tone: "info" },
  STALE: { title: "Location data is out of date", tone: "warning" },
  CONNECTION_LOST: { title: "Connection lost", tone: "danger" },
  NO_OFFICE: { title: "No office assigned", tone: "danger" },
  OUTSIDE_WORKING_WINDOW: { title: "Outside working hours", tone: "neutral" },
  LOCATION_DENIED: { title: "Location blocked", tone: "danger" },
  UNKNOWN: { title: "Waiting for the first location check", tone: "neutral" },
};

/** Browser-side conditions take precedence; everything else is the server's verdict. */
export function deriveUiState(input: {
  policyLoaded: boolean; permission: string; geoError: string | null; connectionLost: boolean; hasFix: boolean;
  lastSuccessAt: number | null; staleSeconds: number; server: AutomaticPayload | null; now?: number;
}): { state: UiState; message: string | null } {
  const now = input.now ?? Date.now();
  if (!input.policyLoaded) return { state: "INITIALIZING", message: "Loading your attendance policy…" };
  if (input.permission === "denied") return { state: "LOCATION_DENIED", message: "Location is blocked for this site. Allow it in your browser's site settings to record attendance automatically." };
  if (input.permission === "unsupported") return { state: "LOCATION_UNAVAILABLE", message: "This browser or connection cannot provide location (HTTPS required)." };
  if (input.connectionLost) return { state: "CONNECTION_LOST", message: "You are offline. No attendance is recorded until the connection returns; your session is kept on the server." };
  if (!input.hasFix && (input.permission === "prompt" || input.permission === "unknown")) return { state: "REQUESTING_PERMISSION", message: "Allow location access so we can detect when you are at the office." };
  if (!input.hasFix && input.geoError) return { state: "LOCATION_UNAVAILABLE", message: input.geoError };
  if (input.server && input.lastSuccessAt && now - input.lastSuccessAt > input.staleSeconds * 1000)
    return { state: "STALE", message: "No successful location check recently. Keep this screen open and in the foreground." };
  if (input.server) return { state: input.server.ui_state as UiState, message: input.server.message };
  return { state: input.hasFix ? "LOCATION_DETECTED" : "INITIALIZING", message: input.hasFix ? "Location received — validating with the server…" : "Starting location…" };
}

export function useAttendancePolicy() {
  return useQuery({ queryKey: ["/attendance/policy/", {}], queryFn: () => api<AttendancePolicy>("/attendance/policy/") });
}

export function useAutomaticAttendance({ consentGranted, windowOpen }: { consentGranted: boolean; windowOpen: boolean }) {
  const policy = useAttendancePolicy();
  const p = policy.data;
  const detection = !!p && p.automatic_detection_enabled && consentGranted;
  const geo = useGeolocation(detection);
  const presence = usePresenceDetection(geo, { enabled: detection && windowOpen, intervalSeconds: p?.presence_interval_seconds ?? 30 });
  const today = useQuery({ queryKey: ["/attendance/automatic/today/", {}], queryFn: () => api<AutomaticPayload>("/attendance/automatic/today/"), refetchInterval: 60_000 });
  const [, tick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => tick((x) => x + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  const server = presence.last ?? today.data ?? null;
  const ui = deriveUiState({
    policyLoaded: !!p, permission: geo.permission, geoError: geo.error?.message ?? null, connectionLost: presence.connectionLost,
    hasFix: !!geo.fix, lastSuccessAt: presence.lastSuccessAt, staleSeconds: p?.presence_stale_seconds ?? 120,
    server: windowOpen || !presence.last ? server : presence.last,
  });
  return { policy: p, geo, presence, today: today.data ?? null, server, ui };
}
