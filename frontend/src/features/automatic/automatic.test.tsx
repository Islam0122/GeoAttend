import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AutomaticPayload, PresenceView, Today } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { mockFetch, renderWithProviders, setOnline } from "@/test/utils";
import { AutomaticAttendancePanel } from "./AutomaticAttendancePanel";
import { deriveUiState } from "./useAutomaticAttendance";
import { useGeolocation } from "./useGeolocation";
import { usePresenceDetection } from "./usePresenceDetection";

vi.mock("@/components/GeoMap", () => ({ GeoMap: () => <div data-testid="map" /> }));

/** Controllable Geolocation mock with watchPosition/clearWatch. */
function installGeo(permission: "granted" | "denied" | "prompt" = "granted") {
  let cb: PositionCallback | null = null;
  let err: PositionErrorCallback | null | undefined = null;
  const watchPosition = vi.fn((ok: PositionCallback, fail?: PositionErrorCallback | null) => { cb = ok; err = fail; return 7; });
  const clearWatch = vi.fn();
  const getCurrentPosition = vi.fn((ok: PositionCallback) => ok(pos(42.8746, 74.5698, 10)));
  Object.defineProperty(navigator, "geolocation", { value: { watchPosition, clearWatch, getCurrentPosition }, configurable: true });
  Object.defineProperty(navigator, "permissions", { value: { query: vi.fn(async () => ({ state: permission, addEventListener: vi.fn(), removeEventListener: vi.fn() })) }, configurable: true });
  return {
    watchPosition, clearWatch, getCurrentPosition,
    emit: (lat: number, lng: number, acc: number, ts = Date.now()) => act(() => cb?.(pos(lat, lng, acc, ts))),
    deny: () => act(() => err?.({ code: 1, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3, message: "denied" } as GeolocationPositionError)),
  };
}
function pos(latitude: number, longitude: number, accuracy: number, timestamp = Date.now()) {
  return { coords: { latitude, longitude, accuracy, altitude: null, altitudeAccuracy: null, heading: null, speed: null }, timestamp } as unknown as GeolocationPosition;
}
function makeWrapper() {
  const client = new QueryClient();
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function setVisibility(v: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: v, configurable: true });
  act(() => document.dispatchEvent(new Event("visibilitychange")));
}

const presence = (over: Partial<PresenceView> = {}): PresenceView => ({
  zone_status: "INSIDE", reason: "", office_id: 1, assigned_office_ids: [1], distance_m: 12, accuracy_m: 9, last_update: new Date().toISOString(),
  last_validated_at: new Date().toISOString(), validated_zone: "INSIDE", last_activity: new Date().toISOString(), permission: "GRANTED_WHEN_IN_USE",
  consent_granted: true, session_status: "ACTIVE", session_id: 3, record_id: 5, attendance_status: "PRESENT", check_in_time: new Date(Date.now() - 3600e3).toISOString(),
  check_out_time: null, working_minutes: 60, late_minutes: 0, temporary_exit_started_at: null, temporary_exit_minutes: 0, is_unscheduled: false, ...over,
});
const policy = (mode = "AUTOMATIC") => ({ attendance_mode: mode, automatic_detection_enabled: true, automatic_checkin_enabled: true, automatic_checkout_enabled: true,
  automatic_resume_enabled: true, presence_interval_seconds: 30, default_max_accuracy_m: 50, entry_confirmation_count: 2, exit_confirmation_count: 3,
  presence_stale_seconds: 120, temporary_exit_grace_minutes: 10, temporary_exit_max_minutes: 30, checkout_grace_minutes: 15, automatic_checkout_timeout_minutes: 120,
  allow_unscheduled_attendance: false, require_registered_device: true, count_temporary_exit_as_work: false, confirmation_policy: "AUTOMATIC",
  automatic_attendance: mode !== "MANUAL", manual_actions_allowed: mode !== "AUTOMATIC" });
const payload = (ui_state: string, over: Partial<PresenceView> = {}, mode = "AUTOMATIC"): AutomaticPayload => ({
  ui_state, message: `server says ${ui_state}`, server_time: new Date().toISOString(), policy: policy(mode) as never, presence: presence(over),
  office: { id: 1, name: "Bishkek HQ", radius_m: 100, max_accuracy_m: 50 }, reading: { result: "ACCEPTED", reason: null, zone: "INSIDE", distance_m: 12, accuracy_m: 9 }, events: [],
});
const today = (over: Partial<Today["actions"]> = {}): Today => ({
  work_date: "2026-11-23", shift: { start: "2026-11-23T03:00:00Z", end: "2026-11-23T12:00:00Z", break_start: null, break_end: null, timezone: "Asia/Bishkek", grace_period_minutes: 0, tracking_window_start: "2026-11-23T02:00:00Z", tracking_window_end: "2026-11-23T14:00:00Z" },
  record: null, location: { presence: "UNKNOWN", office_id: null, distance_m: null, accuracy_m: null, last_update: null, session_status: null },
  offices: [{ id: 1, name: "Bishkek HQ", latitude: 42.8746, longitude: 74.5698, radius_m: 100, max_accuracy_m: 50, timezone: "Asia/Bishkek" }],
  actions: { window_open: true, can_check_in: true, can_check_out: false, can_start_break: false, can_end_break: false, live_session_id: null, live_status: null, confirmation_policy: "AUTOMATIC", checkout_requires_geofence: false, consent_granted: true, ...over },
  server_time: new Date().toISOString(),
});

beforeEach(() => {
  setOnline(true);
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  useAuthStore.setState({ accessToken: "t" });
});

describe("deriveUiState — every UI state", () => {
  const base = { policyLoaded: true, permission: "granted", geoError: null, connectionLost: false, hasFix: true, lastSuccessAt: Date.now(), staleSeconds: 120, server: null };
  it.each([
    [{ ...base, policyLoaded: false }, "INITIALIZING"],
    [{ ...base, permission: "prompt", hasFix: false }, "REQUESTING_PERMISSION"],
    [{ ...base, permission: "denied" }, "LOCATION_DENIED"],
    [{ ...base, permission: "unsupported" }, "LOCATION_UNAVAILABLE"],
    [{ ...base, hasFix: false, geoError: "timeout" }, "LOCATION_UNAVAILABLE"],
    [{ ...base, connectionLost: true, server: payload("ACTIVE_SESSION") }, "CONNECTION_LOST"],
    [{ ...base, server: payload("ACTIVE_SESSION"), lastSuccessAt: Date.now() - 200_000 }, "STALE"],
    [base, "LOCATION_DETECTED"],
  ])("%#", (input, expected) => expect(deriveUiState(input as never).state).toBe(expected));
  it.each(["INSIDE_GEOFENCE", "OUTSIDE_GEOFENCE", "GPS_INACCURATE", "AUTO_CHECKIN", "ACTIVE_SESSION", "TEMPORARY_EXIT", "SESSION_RESUMED", "SESSION_COMPLETED", "UNSCHEDULED", "NO_OFFICE"])(
    "passes server state %s through", (s) => expect(deriveUiState({ ...base, server: payload(s) } as never).state).toBe(s));
});

describe("useGeolocation", () => {
  it("starts watchPosition, clears it when hidden and on unmount, restarts when visible", async () => {
    const g = installGeo();
    mockFetch(() => ({ body: {} }));
    const { result, unmount } = renderHook(() => useGeolocation(true));
    expect(g.watchPosition).toHaveBeenCalledTimes(1);
    expect((g.watchPosition.mock.calls[0] as unknown[])[2]).toMatchObject({ enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
    g.emit(42.87, 74.56, 12);
    expect(result.current.fix?.accuracy).toBe(12);
    setVisibility("hidden");
    expect(g.clearWatch).toHaveBeenCalledWith(7);
    expect(result.current.watching).toBe(false);
    setVisibility("visible");
    expect(g.watchPosition).toHaveBeenCalledTimes(2);
    unmount();
    expect(g.clearWatch).toHaveBeenCalledTimes(2);
  });

  it("reports a denied permission to the server (no coordinates)", async () => {
    const g = installGeo("prompt");
    const f = mockFetch(() => ({ body: {} }));
    renderHook(() => useGeolocation(true));
    g.deny();
    await waitFor(() => expect(f.mock.calls.some(([u]) => String(u).includes("/devices/heartbeat/"))).toBe(true));
    const body = JSON.parse(String((f.mock.calls.find(([u]) => String(u).includes("/devices/heartbeat/"))![1] as RequestInit).body));
    expect(body).toMatchObject({ location_permission: "DENIED" });
    expect(body).not.toHaveProperty("latitude");
  });
});

describe("usePresenceDetection", () => {
  it("sends the first fresh fix and never resends the same measurement", async () => {
    const g = installGeo();
    const f = mockFetch((u) => (u.includes("presence-check") ? { body: payload("INSIDE_GEOFENCE") } : { body: {} }));
    const { result } = renderHook(() => { const geo = useGeolocation(true); return usePresenceDetection(geo, { enabled: true, intervalSeconds: 30 }); }, { wrapper: makeWrapper() });
    g.emit(42.8746, 74.5698, 9, Date.now());
    await waitFor(() => expect(result.current.last?.ui_state).toBe("INSIDE_GEOFENCE"));
    const sent = f.mock.calls.filter(([u]) => String(u).includes("presence-check"));
    expect(sent).toHaveLength(1);
    const body = JSON.parse(String((sent[0][1] as RequestInit).body));
    expect(body).toMatchObject({ accuracy: 9 });
    expect(body).not.toHaveProperty("distance_m");
    expect(body).not.toHaveProperty("zone");
    // GPS stops updating: no new watch fixes and getCurrentPosition times out (as browsers do after `timeout`)
    g.getCurrentPosition.mockImplementation(((_ok: PositionCallback, fail?: PositionErrorCallback | null) =>
      fail?.({ code: 3, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3, message: "timeout" } as GeolocationPositionError)) as never);
    await act(async () => { await result.current.checkNow(); });
    expect(f.mock.calls.filter(([u]) => String(u).includes("presence-check"))).toHaveLength(1);
  });

  it("does not send while offline and reports CONNECTION_LOST", async () => {
    const g = installGeo();
    const f = mockFetch(() => ({ body: {} }));
    setOnline(false);
    const { result } = renderHook(() => { const geo = useGeolocation(true); return usePresenceDetection(geo, { enabled: true, intervalSeconds: 30 }); }, { wrapper: makeWrapper() });
    g.emit(42.8746, 74.5698, 9);
    await act(async () => { await result.current.checkNow(); });
    expect(result.current.connectionLost).toBe(true);
    expect(f.mock.calls.some(([u]) => String(u).includes("presence-check"))).toBe(false);
  });
});

describe("AutomaticAttendancePanel", () => {
  function setup(state: string, over: Partial<PresenceView> = {}, mode = "AUTOMATIC") {
    const g = installGeo();
    mockFetch((u) => u.includes("/attendance/policy/") ? { body: policy(mode) } : u.includes("/automatic/today/") || u.includes("presence-check") ? { body: payload(state, over, mode) } : { body: {} });
    renderWithProviders(<AutomaticAttendancePanel today={today()} />);
    return g;
  }
  it.each([["AUTO_CHECKIN", "Work started automatically"], ["ACTIVE_SESSION", "Work session active"], ["TEMPORARY_EXIT", "Temporary exit"],
           ["SESSION_RESUMED", "Session resumed"], ["SESSION_COMPLETED", "Work session completed"], ["GPS_INACCURATE", "GPS accuracy too low"],
           ["OUTSIDE_GEOFENCE", "Outside the office zone"], ["UNSCHEDULED", "No scheduled shift"]])("renders %s", async (state, title) => {
    const g = setup(state);
    g.emit(42.8746, 74.5698, 9);
    await waitFor(() => expect(screen.getByTestId("auto-state")).toHaveAttribute("data-state", state));
    expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    expect(screen.getByText(`server says ${state}`)).toBeInTheDocument();
  });

  it("shows server metrics, the tracking indicator and no Check-in button in Automatic mode", async () => {
    const g = setup("ACTIVE_SESSION");
    g.emit(42.8746, 74.5698, 9);
    await waitFor(() => expect(screen.getByTestId("auto-state")).toHaveAttribute("data-state", "ACTIVE_SESSION"));
    expect(screen.getByText("12 m")).toBeInTheDocument();
    expect(screen.getByText("100 m")).toBeInTheDocument();
    expect(screen.getByTestId("tracking-indicator")).toHaveTextContent("Location active");
    expect(screen.queryByTestId("manual-in")).not.toBeInTheDocument();
    expect(screen.queryByTestId("manual-out")).not.toBeInTheDocument();
  });

  it("keeps manual actions in Hybrid mode", async () => {
    const g = setup("ACTIVE_SESSION", {}, "HYBRID");
    g.emit(42.8746, 74.5698, 9);
    expect(await screen.findByTestId("manual-out")).toBeEnabled();
  });

  it("explains a denied permission", async () => {
    const g = setup("ACTIVE_SESSION");
    await waitFor(() => expect(g.watchPosition).toHaveBeenCalled()); // GPS starts once the policy is loaded
    g.deny();
    await waitFor(() => expect(screen.getByTestId("auto-state")).toHaveAttribute("data-state", "LOCATION_DENIED"));
    expect(screen.getByTestId("gps-permission")).toHaveTextContent("GPS blocked");
  });
});
