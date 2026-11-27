import { useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, Clock, Crosshair, LogIn, LogOut, MapPinOff, Radar, RefreshCw, ShieldCheck, TimerReset, WifiOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { GpsActionResult, Today } from "@/api/types";
import { GeoMap } from "@/components/GeoMap";
import { Spinner, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { ConsentCard } from "@/features/checkin/CheckInPanel";
import { deviceId, newEventUuid } from "@/lib/device";
import { ago, fmtMinutes, fmtTime, titleCase } from "@/lib/format";
import { UI_COPY, useAutomaticAttendance, type UiState } from "./useAutomaticAttendance";

const ICON: Partial<Record<UiState, React.ReactNode>> = {
  AUTO_CHECKIN: <CheckCircle2 />, ACTIVE_SESSION: <Activity />, SESSION_RESUMED: <CheckCircle2 />, TEMPORARY_EXIT: <TimerReset />,
  CONNECTION_LOST: <WifiOff />, LOCATION_DENIED: <MapPinOff />, LOCATION_UNAVAILABLE: <MapPinOff />, STALE: <Clock />,
};
const ZONE_TONE: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  INSIDE: "success", OUTSIDE: "neutral", STALE: "warning", LOCATION_DETECTED: "info", UNKNOWN: "neutral", LOCATION_DENIED: "danger", NO_OFFICE: "danger",
};

function Metric({ label, value, hint, testId }: { label: string; value: React.ReactNode; hint?: string; testId?: string }) {
  return (
    <div className="rounded-lg border bg-surface p-3" data-testid={testId}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** Minutes elapsed since `iso` added to a server value captured at `serverTime` (live counter without guessing). */
function live(base: number, serverTime: string | undefined, running: boolean): number {
  if (!running || !serverTime) return base;
  return base + Math.max(0, Math.floor((Date.now() - new Date(serverTime).getTime()) / 60000));
}

export function AutomaticAttendancePanel({ today }: { today: Today }) {
  const qc = useQueryClient();
  const consent = today.actions.consent_granted;
  const { policy, geo, presence, server, ui } = useAutomaticAttendance({ consentGranted: consent, windowOpen: today.actions.window_open || !today.shift });
  const [busy, setBusy] = useState<string | null>(null);
  if (!consent) return <ConsentCard onDone={() => qc.invalidateQueries({ queryKey: ["/attendance/today/"] })} />;

  const tz = today.shift?.timezone;
  const p = server?.presence;
  const office = server?.office ?? (today.offices[0] ? { id: today.offices[0].id, name: today.offices[0].name, radius_m: today.offices[0].radius_m, max_accuracy_m: today.offices[0].max_accuracy_m } : null);
  const fence = today.offices.map((o) => ({ id: o.id, name: o.name, lat: o.latitude, lng: o.longitude, radius: o.radius_m }));
  const copy = UI_COPY[ui.state] ?? UI_COPY.UNKNOWN;
  const sessionActive = p?.session_status === "ACTIVE";
  const away = p?.session_status === "TEMPORARY_EXIT";
  const working = live(p?.working_minutes ?? 0, server?.server_time, sessionActive && !presence.connectionLost);
  const awayMinutes = p?.temporary_exit_started_at ? Math.max(0, Math.floor((Date.now() - new Date(p.temporary_exit_started_at).getTime()) / 60000)) : 0;
  const hybrid = policy?.attendance_mode === "HYBRID";
  const accuracy = server?.reading?.accuracy_m ?? p?.accuracy_m ?? null;
  const distance = server?.reading?.distance_m ?? p?.distance_m ?? null;

  async function manual(kind: "in" | "out") {
    setBusy(kind);
    try {
      const fix = (geo.fix && Date.now() - geo.fix.timestamp < 60_000 ? geo.fix : null) ?? (await geo.refresh());
      if (!fix) throw new Error(geo.error?.message ?? "Could not get your location.");
      const r = await api<GpsActionResult>(`/attendance/manual-check-${kind}/`, { raw: true, body: {
        event_uuid: newEventUuid(), device_id: deviceId(), latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy,
        recorded_at: new Date(fix.timestamp).toISOString(), permission_status: "GRANTED_WHEN_IN_USE" } });
      if (r.state.endsWith("SUCCESS")) toast.success(r.message);
      else toast.error(r.message);
      await presence.checkNow();
      qc.invalidateQueries();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2"><Radar className="size-5 text-primary" />Automatic attendance</CardTitle>
          <CardDescription>{office ? `Assigned office: ${office.name}` : "No office assigned"} · {titleCase(policy?.attendance_mode ?? "…")} mode</CardDescription>
        </div>
        <Badge tone={geo.permission === "granted" ? "success" : geo.permission === "denied" ? "danger" : "neutral"} data-testid="gps-permission">
          {geo.permission === "granted" ? "GPS allowed" : geo.permission === "denied" ? "GPS blocked" : geo.permission === "unsupported" ? "GPS unsupported" : "GPS permission needed"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div data-testid="auto-state" data-state={ui.state}>
          <Alert tone={copy.tone} title={copy.title} icon={presence.sending && ui.state === "INITIALIZING" ? <Spinner /> : ICON[ui.state] ?? <Crosshair />}>{ui.message}</Alert>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric testId="m-zone" label="Current zone" value={p ? <Badge tone={ZONE_TONE[p.zone_status]}>{titleCase(p.zone_status)}</Badge> : "—"} />
          <Metric label="Distance to office" value={distance != null ? `${Math.round(distance)} m` : "—"} hint="calculated by the server" />
          <Metric label="GPS accuracy" value={accuracy != null ? `±${Math.round(accuracy)} m` : geo.fix ? `±${Math.round(geo.fix.accuracy)} m (local)` : "—"} hint={office ? `required ≤ ${Math.round(office.max_accuracy_m)} m` : undefined} />
          <Metric label="Geofence radius" value={office ? `${Math.round(office.radius_m)} m` : "—"} />
          <Metric testId="m-status" label="Attendance status" value={p?.record_id ? <StatusBadge status={p.attendance_status} /> : <span className="text-sm text-muted-foreground">{titleCase(p?.attendance_status ?? "—")}</span>} />
          <Metric testId="m-working" label="Working session" value={fmtMinutes(working)} hint={p?.check_in_time ? `since ${fmtTime(p.check_in_time, tz)}` : "not started"} />
          <Metric testId="m-away" label="Temporary exit" value={away ? fmtMinutes(awayMinutes) : fmtMinutes(p?.temporary_exit_minutes ?? 0)} hint={away ? "away now" : policy?.count_temporary_exit_as_work ? "counted as work" : "not paid time"} />
          <Metric label="Last validation" value={p?.last_validated_at ? ago(p.last_validated_at) : "never"} hint={presence.lastSuccessAt ? `last check ${ago(new Date(presence.lastSuccessAt).toISOString())}` : undefined} />
        </div>

        {fence.length > 0 && <GeoMap className="h-52" fences={fence} me={geo.fix ? { lat: geo.fix.latitude, lng: geo.fix.longitude, accuracy: geo.fix.accuracy } : null} />}

        {server?.events && server.events.length > 0 && (
          <div className="space-y-1.5" aria-label="Today's timeline">
            <div className="text-sm font-semibold">Today</div>
            {server.events.filter((e) => e.effect && !e.effect.startsWith("IGNORED") && e.effect !== "PRESENCE_ONLY").map((e, i) => (
              <div key={i} className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-1.5 text-sm">
                <span>{titleCase(e.effect!)}</span><span className="tabular-nums text-muted-foreground">{fmtTime(e.occurred_at, tz)}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {hybrid && (p?.session_status === "ACTIVE" || p?.session_status === "TEMPORARY_EXIT"
            ? <Button variant="outline" disabled={!!busy || !policy?.manual_actions_allowed} onClick={() => manual("out")} data-testid="manual-out">{busy === "out" ? <Spinner /> : <LogOut />}Check out manually</Button>
            : <Button variant="outline" disabled={!!busy || !policy?.manual_actions_allowed} onClick={() => manual("in")} data-testid="manual-in">{busy === "in" ? <Spinner /> : <LogIn />}Check in manually</Button>)}
          <Button variant="ghost" disabled={presence.sending} onClick={() => presence.checkNow()}><RefreshCw />Check location now</Button>
        </div>

        <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="tracking-indicator">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {geo.watching ? <b className="text-foreground">Location active</b> : "Location paused"} — checked every {policy?.presence_interval_seconds ?? 30} s only while this screen is open.
            Closing or hiding it stops location immediately; your session is kept and your manager sees “stale”, not “left”.
            The server confirms arrivals ({policy?.entry_confirmation_count ?? 2} readings) and exits ({policy?.exit_confirmation_count ?? 3} readings).
          </span>
        </p>
      </CardContent>
    </Card>
  );
}
