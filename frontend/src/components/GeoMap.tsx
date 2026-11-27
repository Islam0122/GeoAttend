import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect } from "react";
import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { t } from "@/i18n";

export interface Fence {
  id: number | string;
  name: string;
  lat: number;
  lng: number;
  radius: number;
  active?: boolean;
  label?: string;
}

// OpenStreetMap tiles: free, no API key. Override with VITE_MAP_TILES for a self-hosted/commercial tile server.
const TILE = (import.meta.env.VITE_MAP_TILES as string | undefined) ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

function Picker({ onPick }: { onPick?: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onPick?.(Number(e.latlng.lat.toFixed(6)), Number(e.latlng.lng.toFixed(6))) });
  return null;
}

function Fit({ fences, me }: { fences: Fence[]; me?: { lat: number; lng: number; accuracy: number } | null }) {
  const map = useMap();
  const key = fences.map((f) => `${f.lat},${f.lng},${f.radius}`).join("|") + (me ? `|${me.lat.toFixed(4)},${me.lng.toFixed(4)}` : "");
  useEffect(() => {
    const pts = fences.flatMap((f) => {
      const b = L.latLng(f.lat, f.lng).toBounds(f.radius * 2.6);
      return [b.getNorthWest(), b.getSouthEast()];
    });
    if (me) pts.push(L.latLng(me.lat, me.lng));
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [24, 24], maxZoom: 18 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

/**
 * Office geofence map. `me` is only used on the employee's own check-in screen (their current fix);
 * admin views never receive or render employee coordinates.
 */
export function GeoMap({ fences, onPick, me, className = "h-80" }: { fences: Fence[]; onPick?: (lat: number, lng: number) => void; me?: { lat: number; lng: number; accuracy: number } | null; className?: string }) {
  const center: [number, number] = fences.length ? [fences[0].lat, fences[0].lng] : me ? [me.lat, me.lng] : [42.8746, 74.5698];
  return (
    <div className={`overflow-hidden rounded-lg border ${className}`}>
      <MapContainer center={center} zoom={16} style={{ height: "100%", width: "100%" }} scrollWheelZoom={!!onPick}>
        <TileLayer url={TILE} attribution={`&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ${t("contributors")}`} />
        <Fit fences={fences} me={me} />
        <Picker onPick={onPick} />
        {fences.map((f) => (
          <Circle key={`c${f.id}`} center={[f.lat, f.lng]} radius={f.radius} pathOptions={{ color: f.active === false ? "#94a3b8" : "#16a34a", fillOpacity: 0.12, weight: 2 }} />
        ))}
        {fences.map((f) => (
          <CircleMarker key={`m${f.id}`} center={[f.lat, f.lng]} radius={5} pathOptions={{ color: "#15803d", fillColor: "#16a34a", fillOpacity: 1 }}>
            <Tooltip direction="top" offset={[0, -6]} permanent>{f.label ?? f.name}</Tooltip>
          </CircleMarker>
        ))}
        {me && (
          <>
            <Circle center={[me.lat, me.lng]} radius={me.accuracy} pathOptions={{ color: "#0284c7", fillOpacity: 0.1, weight: 1, dashArray: "4 4" }} />
            <CircleMarker center={[me.lat, me.lng]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#0284c7", fillOpacity: 1 }}>
              <Tooltip direction="bottom">{t("You (±{n} m)", { n: Math.round(me.accuracy) })}</Tooltip>
            </CircleMarker>
          </>
        )}
      </MapContainer>
    </div>
  );
}
