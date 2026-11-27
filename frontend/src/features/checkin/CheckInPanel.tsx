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
import { fmtMeters, fmtTime } from "@/lib/format";
import { getPosition, type Fix } from "@/lib/geo";
import { enqueue } from "@/lib/offlineQueue";
import { useQueueStore } from "@/stores/queue";
import { useLocationCheck, type CheckState } from "./useLocationCheck";
import { msg, t } from "@/i18n";

type Outcome =
  | { kind: "result"; result: GpsActionResult }
  | { kind: "queued"; action: "CHECK_IN" | "CHECK_OUT"; at: string }
  | { kind: "error"; message: string };

const STATE_COPY: Record<CheckState, { title: string; tone: "success" | "warning" | "danger" | "info" | "neutral"; text: string }> = {
  LOCATION_PERMISSION_REQUIRED: { title: msg("Location permission required"), tone: "info", text: msg("Allow location access so we can confirm you are at your office.") },
  PERMISSION_DENIED: { title: msg("Location blocked"), tone: "danger", text: msg("Location access is blocked for this site. Enable it in your browser's site settings, then retry.") },
  GETTING_LOCATION: { title: msg("Getting your location…"), tone: "info", text: msg("This can take a few seconds. Stay near a window for the best accuracy.") },
  LOCATION_FOUND: { title: msg("Location found"), tone: "neutral", text: msg("No office geofence is assigned to you yet. Ask your administrator.") },
  INSIDE_GEOFENCE: { title: msg("You're inside the office zone"), tone: "success", text: msg("You can check in now.") },
  OUTSIDE_GEOFENCE: { title: msg("You're outside the office zone"), tone: "warning", text: msg("Move inside the office geofence to check in.") },
  GPS_ACCURACY_LOW: { title: msg("GPS accuracy too low"), tone: "warning", text: msg("Your position is not precise enough to confirm. Move near a window or outdoors and retry.") },
  LOCATION_ERROR: { title: msg("Location unavailable"), tone: "danger", text: msg("Your device could not determine a location. Check that location services are on.") },
  UNSUPPORTED: { title: msg("Location not available"), tone: "danger", text: msg("This browser or connection cannot provide location. Use HTTPS and a modern browser.") },
};

export function ConsentCard({ onDone }: { onDone(): void }) {
  const { data } = useGet<Consent>("/consent/me/");
  const [busy, setBusy] = useState(false);
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5 text-primary" />{t("How your location is used")}</CardTitle>
        <CardDescription>{t("Required once before your first GPS check-in.")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{data?.policy_text && t(data.policy_text)}</p>
        <ul className="space-y-1.5 text-sm">
          <li>• {t("Location is read only when you press Check in / Check out, and while this screen is open during an active work session.")}</li>
          <li>• {t("There is no hidden or background tracking; closing this page stops all location access.")}</li>
          <li>• {t("Managers see your status and distance to the office, never a movement trail.")}</li>
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
        }}>{t("I agree — enable GPS attendance")}</Button>
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
        setOutcome({ kind: "error", message: (e as Error).message || t("Could not get your location.") });
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
      toast.success(a.can_end_break ? t("Welcome back — break ended") : t("Break started"));
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
          <CardTitle className="flex items-center gap-2"><LocateFixed className="size-5 text-primary" />{t("GPS attendance")}</CardTitle>
          <CardDescription>{office ? t("Assigned office: {name}", { name: office.name }) : today.offices.length ? t("{n} assigned offices", { n: today.offices.length }) : t("No office assigned")}</CardDescription>
        </div>
        <Badge tone={loc.permission === "granted" ? "success" : loc.permission === "denied" ? "danger" : "neutral"} data-testid="permission-badge">
          {loc.permission === "granted" ? t("Location allowed") : loc.permission === "denied" ? t("Location blocked") : loc.permission === "unsupported" ? t("Unsupported") : t("Permission needed")}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div data-testid="check-state" data-state={loc.state}>
          <Alert tone={copy.tone} title={t(copy.title)} icon={loc.state === "GETTING_LOCATION" ? <Spinner /> : loc.state === "INSIDE_GEOFENCE" ? <CheckCircle2 /> : loc.state === "PERMISSION_DENIED" || loc.state === "UNSUPPORTED" ? <MapPinOff /> : <Crosshair />}>
            {loc.state === "OUTSIDE_GEOFENCE" && loc.distance != null && office ? t("You are about {d} m from {office} (zone radius {r} m).", { d: Math.round(loc.distance), office: office.name, r: Math.round(office.radius_m) }) : loc.error && loc.state !== "GETTING_LOCATION" ? loc.error : t(copy.text)}
          </Alert>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <Metric label={t("GPS accuracy")} value={loc.fix ? fmtMeters(loc.fix.accuracy, true) : "—"} warn={!!(loc.fix && office && loc.fix.accuracy > office.max_accuracy_m)} />
          <Metric label={t("Distance")} value={loc.distance != null ? fmtMeters(loc.distance) : "—"} />
          <Metric label={t("Geofence radius")} value={office ? fmtMeters(office.radius_m) : "—"} />
        </div>

        {(loc.fix || fence.length > 0) && (
          <GeoMap className="h-56" fences={fence} me={loc.fix ? { lat: loc.fix.latitude, lng: loc.fix.longitude, accuracy: loc.fix.accuracy } : null} />
        )}

        {outcome && <OutcomeView outcome={outcome} tz={tz} onRetry={() => act(outcome.kind === "queued" ? outcome.action : checkedIn ? "CHECK_OUT" : "CHECK_IN")} />}

        <div className="flex flex-col gap-2 sm:flex-row">
          {(!checkedIn || onBreak) && (
            <Button size="xl" className="flex-1" disabled={!!busy || !a.window_open || loc.state === "UNSUPPORTED"} onClick={() => (onBreak ? toggleBreak() : act("CHECK_IN"))} data-testid="check-in-button">
              {busy === "CHECK_IN" ? <Spinner /> : <LogIn />} {onBreak ? t("End break") : t("Check in")}
            </Button>
          )}
          {checkedIn && !onBreak && (
            <>
              <Button size="xl" className="flex-1" variant="default" disabled={!!busy} onClick={() => act("CHECK_OUT")} data-testid="check-out-button">
                {busy === "CHECK_OUT" ? <Spinner /> : <LogOut />} {t("Check out")}
              </Button>
              <Button size="xl" variant="outline" disabled={!!busy || !a.can_start_break} onClick={toggleBreak}><Coffee />{t("Break")}</Button>
            </>
          )}
          {loc.state !== "GETTING_LOCATION" && loc.state !== "UNSUPPORTED" && (
            <Button size="xl" variant="outline" disabled={!!busy} onClick={() => loc.locate()} aria-label={t("Refresh location")}>
              <RefreshCw />{loc.state === "LOCATION_PERMISSION_REQUIRED" ? t("Allow location") : t("Refresh")}
            </Button>
          )}
        </div>
        {!a.window_open && <p className="text-sm text-muted-foreground">{t("Check-in opens shortly before your scheduled shift")}{today.shift ? ` (${fmtTime(today.shift.tracking_window_start, tz)}–${fmtTime(today.shift.tracking_window_end, tz)})` : ""}.</p>}
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" /> {checkedIn ? t("Location is read only while this screen is open during your work session.") : t("Location is read only while this screen is open.")} {t("The server verifies every check-in.")}
        </p>
      </CardContent>
    </Card>
  );
}

function OutcomeView({ outcome, tz, onRetry }: { outcome: Outcome; tz?: string; onRetry(): void }) {
  if (outcome.kind === "queued")
    return (
      <Alert tone="info" icon={<WifiOff />} title={outcome.action === "CHECK_IN" ? t("Check-in saved offline — pending") : t("Check-out saved offline — pending")} >
        {t("Recorded at {time} on this device. It is not yet accepted: the server will validate it automatically when you are back online.", { time: fmtTime(outcome.at, tz) })}
      </Alert>
    );
  if (outcome.kind === "error") return <Alert tone="danger" icon={<XCircle />} title={t("Something went wrong")}>{outcome.message}</Alert>;
  const r = outcome.result;
  if (r.state === "CHECK_IN_SUCCESS" || r.state === "CHECK_OUT_SUCCESS") {
    return (
      <Alert tone="success" icon={<CheckCircle2 />} title={r.pending_approval ? t("Recorded — awaiting manager approval") : (r.state === "CHECK_IN_SUCCESS" ? t("You checked in successfully at {time}.", { time: fmtTime(r.recorded_at, tz) }) : t("You checked out successfully at {time}.", { time: fmtTime(r.recorded_at, tz) }))}>
        {r.office_name && `${r.office_name} · ${r.distance_m != null ? t("{n} m from office", { n: Math.round(r.distance_m) }) : ""} · GPS ${fmtMeters(r.accuracy_m ?? 0, true)}`}
      </Alert>
    );
  }
  return (
    <div data-testid="outcome-failed" data-state={r.state}>
      <Alert tone={r.state === "OUTSIDE_GEOFENCE" || r.state === "GPS_ACCURACY_LOW" ? "warning" : "danger"} icon={<ShieldAlert />}
             title={r.state === "GPS_ACCURACY_LOW" ? t("GPS accuracy too low — please retry") : r.state === "OUTSIDE_GEOFENCE" ? t("Outside the office geofence") : t("Check-in failed")}>
        <div>{t(r.message)}</div>
        <Button size="sm" variant="outline" className="mt-2" onClick={onRetry}><RefreshCw />{t("Retry")}</Button>
      </Alert>
    </div>
  );
}
