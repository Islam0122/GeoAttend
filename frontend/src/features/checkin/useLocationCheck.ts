import { useCallback, useEffect, useRef, useState } from "react";
import type { OfficeFence } from "@/api/types";
import { GeoError, getPosition, nearestOffice, previewZone, queryPermission, watchPermission, type Fix, type PermissionState, type ZonePreview } from "@/lib/geo";

export type CheckState =
  | "LOCATION_PERMISSION_REQUIRED" | "PERMISSION_DENIED" | "GETTING_LOCATION" | "LOCATION_FOUND"
  | "INSIDE_GEOFENCE" | "OUTSIDE_GEOFENCE" | "GPS_ACCURACY_LOW" | "LOCATION_ERROR" | "UNSUPPORTED";

export interface LocationCheck {
  permission: PermissionState;
  state: CheckState;
  fix: Fix | null;
  office: OfficeFence | null;
  distance: number | null;
  preview: ZonePreview | null;
  error: string | null;
  locate(): Promise<Fix | null>;
}

/**
 * Foreground-only location checks. Runs once on demand and, while this screen is visible and permission is granted,
 * refreshes every `refreshMs`. Nothing runs when the tab is hidden or closed — browsers do not allow reliable background GPS.
 */
export function useLocationCheck(offices: OfficeFence[], { refreshMs = 60_000, auto = true, onFix }: { refreshMs?: number; auto?: boolean; onFix?: (f: Fix) => void } = {}): LocationCheck {
  const [permission, setPermission] = useState<PermissionState>("unknown");
  const [state, setState] = useState<CheckState>("LOCATION_PERMISSION_REQUIRED");
  const [fix, setFix] = useState<Fix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const officesRef = useRef(offices);
  officesRef.current = offices;
  const onFixRef = useRef(onFix);
  onFixRef.current = onFix;

  const evaluate = useCallback((f: Fix) => {
    const near = nearestOffice(f, officesRef.current);
    if (!near) return setState("LOCATION_FOUND");
    setState(previewZone(near.distance, f.accuracy, near.office.radius_m, near.office.max_accuracy_m));
  }, []);

  const locate = useCallback(async () => {
    setState("GETTING_LOCATION");
    setError(null);
    try {
      const f = await getPosition();
      setFix(f);
      onFixRef.current?.(f);
      setPermission("granted");
      evaluate(f);
      return f;
    } catch (e) {
      const err = e as GeoError;
      setError(err.message);
      if (err.kind === "PERMISSION_DENIED") {
        setPermission("denied");
        setState("PERMISSION_DENIED");
      } else if (err.kind === "UNSUPPORTED" || err.kind === "INSECURE_CONTEXT") setState("UNSUPPORTED");
      else setState("LOCATION_ERROR");
      return null;
    }
  }, [evaluate]);

  useEffect(() => {
    let cancelled = false;
    void queryPermission().then((p) => {
      if (cancelled) return;
      setPermission(p);
      if (p === "unsupported") setState("UNSUPPORTED");
      else if (p === "denied") setState("PERMISSION_DENIED");
      else if (p === "granted" && auto) void locate();
    });
    const off = watchPermission((p) => {
      setPermission(p);
      if (p === "denied") setState("PERMISSION_DENIED");
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [auto, locate]);

  useEffect(() => {
    if (fix) evaluate(fix);
  }, [offices, fix, evaluate]);

  useEffect(() => {
    if (permission !== "granted" || !refreshMs) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void locate();
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [permission, refreshMs, locate]);

  const near = fix ? nearestOffice(fix, offices) : null;
  return {
    permission, state, fix, error, locate,
    office: near?.office ?? null,
    distance: near ? near.distance : null,
    preview: near && fix ? previewZone(near.distance, fix.accuracy, near.office.radius_m, near.office.max_accuracy_m) : null,
  };
}
