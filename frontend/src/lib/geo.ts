/** Browser Geolocation API helpers. The server is the final authority; anything computed here is a preview. */

export interface Fix {
  latitude: number;
  longitude: number;
  accuracy: number;
  timestamp: number;
}

export type PermissionState = "granted" | "denied" | "prompt" | "unsupported" | "unknown";

export const GEO_OPTIONS: PositionOptions = { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 };

export class GeoError extends Error {
  constructor(public kind: "PERMISSION_DENIED" | "POSITION_UNAVAILABLE" | "TIMEOUT" | "UNSUPPORTED" | "INSECURE_CONTEXT", message: string) {
    super(message);
  }
}

export function geolocationSupported(): boolean {
  return typeof navigator !== "undefined" && "geolocation" in navigator;
}

export async function queryPermission(): Promise<PermissionState> {
  if (!geolocationSupported()) return "unsupported";
  try {
    const status = await navigator.permissions?.query({ name: "geolocation" as PermissionName });
    return (status?.state as PermissionState) ?? "unknown";
  } catch {
    return "unknown"; // Safari < 16 has no Permissions API for geolocation
  }
}

export function watchPermission(cb: (s: PermissionState) => void): () => void {
  let status: PermissionStatus | null = null;
  const handler = () => status && cb(status.state as PermissionState);
  navigator.permissions?.query({ name: "geolocation" as PermissionName }).then((s) => {
    status = s;
    s.addEventListener("change", handler);
  }).catch(() => undefined);
  return () => status?.removeEventListener("change", handler);
}

export function getPosition(options: PositionOptions = GEO_OPTIONS): Promise<Fix> {
  return new Promise((resolve, reject) => {
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      reject(new GeoError("INSECURE_CONTEXT", "Location requires HTTPS (or localhost)."));
      return;
    }
    if (!geolocationSupported()) {
      reject(new GeoError("UNSUPPORTED", "This browser does not support location services."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy, timestamp: p.timestamp }),
      (err) => {
        if (err.code === err.PERMISSION_DENIED) reject(new GeoError("PERMISSION_DENIED", "Location permission was denied."));
        else if (err.code === err.TIMEOUT) reject(new GeoError("TIMEOUT", "Getting your location took too long. Try again near a window."));
        else reject(new GeoError("POSITION_UNAVAILABLE", "Your location is currently unavailable. Check that location services are on."));
      },
      options,
    );
  });
}

const R = 6_371_008.8;
export function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dphi = toRad(lat2 - lat1);
  const dl = toRad(lon2 - lon1);
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

export type ZonePreview = "INSIDE_GEOFENCE" | "OUTSIDE_GEOFENCE" | "GPS_ACCURACY_LOW";

/** Same conservative rule the server applies — used only to guide the user before they press the button. */
export function previewZone(distance: number, accuracy: number, radius: number, maxAccuracy: number): ZonePreview {
  if (accuracy > maxAccuracy) return "GPS_ACCURACY_LOW";
  if (distance + accuracy <= radius) return "INSIDE_GEOFENCE";
  if (distance - accuracy > radius) return "OUTSIDE_GEOFENCE";
  return "GPS_ACCURACY_LOW";
}

export function nearestOffice<T extends { latitude: number; longitude: number }>(fix: Fix, offices: T[]): { office: T; distance: number } | null {
  let best: { office: T; distance: number } | null = null;
  for (const o of offices) {
    const d = haversine(fix.latitude, fix.longitude, o.latitude, o.longitude);
    if (!best || d < best.distance) best = { office: o, distance: d };
  }
  return best;
}
