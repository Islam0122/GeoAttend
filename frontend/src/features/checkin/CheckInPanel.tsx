import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Coffee, Crosshair, LocateFixed, LogIn, LogOut, MapPinOff, RefreshCw, ShieldAlert, ShieldCheck, WifiOff, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/api/client";
import { useGet } from "@/api/hooks";
import type { Consent, GpsActionResult, Today } from "@/api/types";
import { GeoMap } from "@/components/GeoMap";
import { Spinner } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/misc";
import { registerDevice } from "@/features/session";
import { deviceId, newEventUuid } from "@/lib/device";
import { fmtTime } from "@/lib/format";
import { getPosition, type Fix } from "@/lib/geo";
import { enqueue } from "@/lib/offlineQueue";
import { useQueueStore } from "@/stores/queue";
import { useLocationCheck, type CheckState } from "./useLocationCheck";

type Outcome =
  | { kind: "result"; result: GpsActionResult }
  | { kind: "queued"; action: "CHECK_IN" | "CHECK_OUT"; at: string }
  | { kind: "error"; message: string };

const STATE_COPY: Record<CheckState, { title: string; tone: "success" | "warning" | "danger" | "info" | "neutral"; text: string }> = {
  LOCATION_PERMISSION_REQUIRED: { title: "Location permission required", tone: "info", text: "Allow location access so we can confirm you are at your office." },
  PERMISSION_DENIED: { title: "Location blocked", tone: "danger", text: "Location access is blocked for this site. Enable it in your browser's site settings, then retry." },
  GETTING_LOCATION: { title: "Getting your location…", tone: "info", text: "This can take a few seconds. Stay near a window for the best accuracy." },
  LOCATION_FOUND: { title: "Location found", tone: "neutral", text: "No office geofence is assigned to you yet. Ask your administrator." },
  INSIDE_GEOFENCE: { title: "You're inside the office zone", tone: "success", text: "You can check in now." },
  OUTSIDE_GEOFENCE: { title: "You're outside the office zone", tone: "warning", text: "Move inside the office geofence to check in." },
  GPS_ACCURACY_LOW: { title: "GPS accuracy too low", tone: "warning", text: "Your position is not precise enough to confirm. Move near a window or outdoors and retry." },
  LOCATION_ERROR: { title: "Location unavailable", tone: "danger", text: "Your device could not determine a location. Check that location services are on." },
  UNSUPPORTED: { title: "Location not available", tone: "danger", text: "This browser or connection cannot provide location. Use HTTPS and a modern browser." },
};

export function ConsentCard({ onDone }: { onDone(): void }) {
  const { data } = useGet<Consent>("/consent/me/");
  const [busy, setBusy] = useState(false);
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5 text-primary" />How your location is used</CardTitle>
        <CardDescription>Required once before your first GPS check-in.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{data?.policy_text}</p>
        <ul className="space-y-1.5 text-sm">
          <li>• Location is read only when you press Check in / Check out, and while this screen is open during an active work session.</li>
          <li>• There is no hidden or background tracking; closing this page stops all location access.</li>
          <li>• Managers see your status and distance to the office, never a movement trail.</li>
        </ul>
        <Button disabled={busy || !data} onClick={async () => {
          setBusy(true);
          try {
            await api("/consent/", { body: { granted: true, consent_version: data!.required_version } });
            onDone();
          } catch (e) {
            toast.error((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}>I agree — enable GPS attendance</Button>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-lg border bg-surface p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-semibold tabular-nums ${warn ? "text-amber-600 dark:text-warning" : ""}`}>{value}</div>
    </div>
  );
}

export function CheckInPanel({ today, onFix }: { today: Today; onFix?: (f: Fix) => void }) {
  const qc = useQueryClient();
  const loc = useLocationCheck(today.offices, { refreshMs: 30_000, onFix });
  const [busy, setBusy] = useState<"CHECK_IN" | "CHECK_OUT" | "BREAK" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const refreshQueue = useQueueStore((s) => s.refresh);
  const tz = today.shift?.timezone;
  const a = today.actions;

  if (!a.consent_granted) return <ConsentCard onDone={() => qc.invalidateQueries({ queryKey: ["/attendance/today/"] })} />;

  async function act(kind: "CHECK_IN" | "CHECK_OUT") {
    setBusy(kind);
    setOutcome(null);
    let fix: Fix | null = null;
    try {
      fix = await getPosition(); // fresh fix (enableHighAccuracy, timeout 15 s, maximumAge 0)
    } catch (e) {
      // Indoors a fresh fix can time out: fall back to a reading from the last minute (its original
      // timestamp is sent; the server re-validates age and accuracy).
      if (loc.fix && Date.now() - loc.fix.timestamp < 60_000) fix = loc.fix;
      else {
        setBusy(null);
        setOutcome({ kind: "error", message: (e as Error).message || "Could not get your location." });
        return;
      }
    }
    void loc.locate();
    const payload = {
      event_uuid: newEventUuid(), device_id: deviceId(), latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy,
      recorded_at: new Date(fix.timestamp).toISOString(), permission_status: "GRANTED_WHEN_IN_USE", offline: !navigator.onLine,
    };
    const queue = async () => {
      await enqueue({ event_uuid: payload.event_uuid, kind, payload: { ...payload, offline: true }, queued_at: new Date().toISOString(), attempts: 0 });
      await refreshQueue();
      setOutcome({ kind: "queued", action: kind, at: payload.recorded_at });
    };
    try {
      if (!navigator.onLine) {
        await queue();
        return;
      }
      await registerDevice("GRANTED_WHEN_IN_USE");
      const res = await api<GpsActionResult>(kind === "CHECK_IN" ? "/attendance/check-in/" : "/attendance/check-out/", { body: payload, raw: true });
      setOutcome({ kind: "result", result: res });
      if (res.state === "CHECK_IN_SUCCESS" || res.state === "CHECK_OUT_SUCCESS") {
        qc.invalidateQueries();
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) await queue();
      else setOutcome({ kind: "error", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function toggleBreak() {
    setBusy("BREAK");
    try {
      await api(a.can_end_break ? "/attendance/break/end/" : "/attendance/break/start/", { body: a.can_end_break ? {} : { type: "LUNCH" } });
      toast.success(a.can_end_break ? "Welcome back — break ended" : "Break started");
      qc.invalidateQueries({ queryKey: ["/attendance/today/"] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const copy = STATE_COPY[loc.state];
  const office = loc.office;
  const fence = office ? [{ id: office.id, name: office.name, lat: office.latitude, lng: office.longitude, radius: office.radius_m }] : today.offices.map((o) => ({ id: o.id, name: o.name, lat: o.latitude, lng: o.longitude, radius: o.radius_m }));
  const checkedIn = !!a.live_session_id;
  const onBreak = a.live_status === "AWAY";

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2"><LocateFixed className="size-5 text-primary" />GPS attendance</CardTitle>
          <CardDescription>{office ? `Assigned office: ${office.name}` : today.offices.length ? `${today.offices.length} assigned offices` : "No office assigned"}</CardDescription>
        </div>
        <Badge tone={loc.permission === "granted" ? "success" : loc.permission === "denied" ? "danger" : "neutral"} data-testid="permission-badge">
          {loc.permission === "granted" ? "Location allowed" : loc.permission === "denied" ? "Location blocked" : loc.permission === "unsupported" ? "Unsupported" : "Permission needed"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div data-testid="check-state" data-state={loc.state}>
          <Alert tone={copy.tone} title={copy.title} icon={loc.state === "GETTING_LOCATION" ? <Spinner /> : loc.state === "INSIDE_GEOFENCE" ? <CheckCircle2 /> : loc.state === "PERMISSION_DENIED" || loc.state === "UNSUPPORTED" ? <MapPinOff /> : <Crosshair />}>
            {loc.state === "OUTSIDE_GEOFENCE" && loc.distance != null && office ? `You are about ${Math.round(loc.distance)} m from ${office.name} (zone radius ${Math.round(office.radius_m)} m).` : loc.error && loc.state !== "GETTING_LOCATION" ? loc.error : copy.text}
          </Alert>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <Metric label="GPS accuracy" value={loc.fix ? `±${Math.round(loc.fix.accuracy)} m` : "—"} warn={!!(loc.fix && office && loc.fix.accuracy > office.max_accuracy_m)} />
          <Metric label="Distance" value={loc.distance != null ? `${Math.round(loc.distance)} m` : "—"} />
          <Metric label="Geofence radius" value={office ? `${Math.round(office.radius_m)} m` : "—"} />
        </div>

        {(loc.fix || fence.length > 0) && (
          <GeoMap className="h-56" fences={fence} me={loc.fix ? { lat: loc.fix.latitude, lng: loc.fix.longitude, accuracy: loc.fix.accuracy } : null} />
        )}

        {outcome && <OutcomeView outcome={outcome} tz={tz} onRetry={() => act(outcome.kind === "queued" ? outcome.action : checkedIn ? "CHECK_OUT" : "CHECK_IN")} />}

        <div className="flex flex-col gap-2 sm:flex-row">
          {(!checkedIn || onBreak) && (
            <Button size="xl" className="flex-1" disabled={!!busy || !a.window_open || loc.state === "UNSUPPORTED"} onClick={() => (onBreak ? toggleBreak() : act("CHECK_IN"))} data-testid="check-in-button">
              {busy === "CHECK_IN" ? <Spinner /> : <LogIn />} {onBreak ? "End break" : "Check in"}
            </Button>
          )}
          {checkedIn && !onBreak && (
            <>
              <Button size="xl" className="flex-1" variant="default" disabled={!!busy} onClick={() => act("CHECK_OUT")} data-testid="check-out-button">
                {busy === "CHECK_OUT" ? <Spinner /> : <LogOut />} Check out
              </Button>
              <Button size="xl" variant="outline" disabled={!!busy || !a.can_start_break} onClick={toggleBreak}><Coffee />Break</Button>
            </>
          )}
          {loc.state !== "GETTING_LOCATION" && loc.state !== "UNSUPPORTED" && (
            <Button size="xl" variant="outline" disabled={!!busy} onClick={() => loc.locate()} aria-label="Refresh location">
              <RefreshCw />{loc.state === "LOCATION_PERMISSION_REQUIRED" ? "Allow location" : "Refresh"}
            </Button>
          )}
        </div>
        {!a.window_open && <p className="text-sm text-muted-foreground">Check-in opens shortly before your scheduled shift{today.shift ? ` (${fmtTime(today.shift.tracking_window_start, tz)}–${fmtTime(today.shift.tracking_window_end, tz)})` : ""}.</p>}
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" /> Location is read only while this screen is open{checkedIn ? " during your work session" : ""}. The server verifies every check-in.
        </p>
      </CardContent>
    </Card>
  );
}

function OutcomeView({ outcome, tz, onRetry }: { outcome: Outcome; tz?: string; onRetry(): void }) {
  if (outcome.kind === "queued")
    return (
      <Alert tone="info" icon={<WifiOff />} title={`${outcome.action === "CHECK_IN" ? "Check-in" : "Check-out"} saved offline — pending`} >
        Recorded at {fmtTime(outcome.at, tz)} on this device. It is <b>not yet accepted</b>: the server will validate it automatically when you are back online.
      </Alert>
    );
  if (outcome.kind === "error") return <Alert tone="danger" icon={<XCircle />} title="Something went wrong">{outcome.message}</Alert>;
  const r = outcome.result;
  if (r.state === "CHECK_IN_SUCCESS" || r.state === "CHECK_OUT_SUCCESS") {
    const verb = r.state === "CHECK_IN_SUCCESS" ? "checked in" : "checked out";
    return (
      <Alert tone="success" icon={<CheckCircle2 />} title={r.pending_approval ? "Recorded — awaiting manager approval" : `You ${verb} successfully at ${fmtTime(r.recorded_at, tz)}.`}>
        {r.office_name && `${r.office_name} · ${r.distance_m != null ? `${Math.round(r.distance_m)} m from office` : ""} · GPS ±${Math.round(r.accuracy_m ?? 0)} m`}
      </Alert>
    );
  }
  return (
    <div data-testid="outcome-failed" data-state={r.state}>
      <Alert tone={r.state === "OUTSIDE_GEOFENCE" || r.state === "GPS_ACCURACY_LOW" ? "warning" : "danger"} icon={<ShieldAlert />}
             title={r.state === "GPS_ACCURACY_LOW" ? "GPS accuracy too low — please retry" : r.state === "OUTSIDE_GEOFENCE" ? "Outside the office geofence" : "Check-in failed"}>
        <div>{r.message}</div>
        <Button size="sm" variant="outline" className="mt-2" onClick={onRetry}><RefreshCw />Retry</Button>
      </Alert>
    </div>
  );
}
