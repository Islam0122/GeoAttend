import { useCallback, useEffect, useRef, useState } from "react";
import { GEO_OPTIONS, GeoError, getPosition, queryPermission, watchPermission, type Fix, type PermissionState } from "@/lib/geo";
import { reportPermission } from "@/features/session";
import { t } from "@/i18n";

export interface GeolocationState {
  permission: PermissionState;
  fix: Fix | null;
  error: GeoError | null;
  watching: boolean;
  /** One-off fresh fix (getCurrentPosition); used when watchPosition has not delivered recently. */
  refresh(): Promise<Fix | null>;
}

const toServer = (p: PermissionState) => (p === "granted" ? "GRANTED_WHEN_IN_USE" : p === "denied" ? "DENIED" : "UNKNOWN");

/**
 * Foreground GPS. Primary source: navigator.geolocation.watchPosition(); fallback: getCurrentPosition().
 * The watch is cleared when the tab is hidden and on unmount (clearWatch) — no background collection.
 * Permission changes are reported to the server (no coordinates) so managers see LOCATION_DENIED.
 */
export function useGeolocation(enabled: boolean): GeolocationState {
  const [permission, setPermission] = useState<PermissionState>("unknown");
  const [fix, setFix] = useState<Fix | null>(null);
  const [error, setError] = useState<GeoError | null>(null);
  const [watching, setWatching] = useState(false);
  const watchId = useRef<number | null>(null);
  const reported = useRef<string | null>(null);

  const report = useCallback((p: PermissionState) => {
    const s = toServer(p);
    if (reported.current !== s && (p === "granted" || p === "denied")) {
      reported.current = s;
      void reportPermission(s);
    }
  }, []);

  const onError = useCallback((err: GeolocationPositionError) => {
    const e = err.code === err.PERMISSION_DENIED ? new GeoError("PERMISSION_DENIED", t("Location permission was denied."))
      : err.code === err.TIMEOUT ? new GeoError("TIMEOUT", t("Getting your location took too long."))
      : new GeoError("POSITION_UNAVAILABLE", t("Your location is currently unavailable."));
    setError(e);
    if (e.kind === "PERMISSION_DENIED") {
      setPermission("denied");
      report("denied");
    }
  }, [report]);

  const stop = useCallback(() => {
    if (watchId.current !== null && typeof navigator !== "undefined" && navigator.geolocation) navigator.geolocation.clearWatch(watchId.current);
    watchId.current = null;
    setWatching(false);
  }, []);

  const start = useCallback(() => {
    if (watchId.current !== null) return;
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      setError(new GeoError("INSECURE_CONTEXT", t("Location requires HTTPS (or localhost).")));
      return;
    }
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError(new GeoError("UNSUPPORTED", t("This browser does not support location services.")));
      setPermission("unsupported");
      return;
    }
    watchId.current = navigator.geolocation.watchPosition((p) => {
      setFix({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy, timestamp: p.timestamp });
      setError(null);
      setPermission("granted");
      report("granted");
    }, onError, GEO_OPTIONS);
    setWatching(true);
  }, [onError, report]);

  const refresh = useCallback(async () => {
    try {
      const f = await getPosition();
      setFix(f);
      setError(null);
      setPermission("granted");
      report("granted");
      return f;
    } catch (e) {
      const err = e as GeoError;
      setError(err);
      if (err.kind === "PERMISSION_DENIED") {
        setPermission("denied");
        report("denied");
      }
      return null;
    }
  }, [report]);

  useEffect(() => {
    let cancelled = false;
    void queryPermission().then((p) => {
      if (cancelled) return;
      setPermission(p);
      report(p);
    });
    const off = watchPermission((p) => {
      setPermission(p);
      report(p);
      if (p === "denied") stop();
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [report, stop]);

  useEffect(() => {
    if (!enabled) {
      stop();
      return;
    }
    const onVisibility = () => (document.visibilityState === "visible" ? start() : stop());
    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [enabled, start, stop]);

  return { permission, fix, error, watching, refresh };
}
