import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Today } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { mockFetch, mockGeolocation, renderWithProviders, setOnline } from "@/test/utils";
import { list, remove } from "@/lib/offlineQueue";
import { CheckInPanel } from "./CheckInPanel";

vi.mock("@/components/GeoMap", () => ({ GeoMap: () => <div data-testid="map" /> }));

const OFFICE = { id: 1, name: "Bishkek HQ", latitude: 42.8746, longitude: 74.5698, radius_m: 100, max_accuracy_m: 50, timezone: "Asia/Bishkek" };
const metresNorth = (m: number) => OFFICE.latitude + m / 111_320;

function today(over: Partial<Today["actions"]> = {}): Today {
  return {
    work_date: "2026-11-23",
    shift: { start: "2026-11-23T03:00:00Z", end: "2026-11-23T12:00:00Z", break_start: null, break_end: null, timezone: "Asia/Bishkek", grace_period_minutes: 5, tracking_window_start: "2026-11-23T02:00:00Z", tracking_window_end: "2026-11-23T14:00:00Z" },
    record: null,
    location: { presence: "UNKNOWN", office_id: null, distance_m: null, accuracy_m: null, last_update: null, session_status: null },
    offices: [OFFICE],
    actions: { window_open: true, can_check_in: true, can_check_out: false, can_start_break: false, can_end_break: false, live_session_id: null, live_status: null, confirmation_policy: "AUTOMATIC", checkout_requires_geofence: false, consent_granted: true, ...over },
    server_time: new Date().toISOString(),
  };
}

const success = { state: "CHECK_IN_SUCCESS", code: "OK", message: "You checked in successfully.", office_id: 1, office_name: "Bishkek HQ", radius_m: 100, max_accuracy_m: 50, distance_m: 35, accuracy_m: 12, zone: "INSIDE", session_id: 9, record_id: 3, attendance_status: "PRESENT", pending_approval: false, recorded_at: "2026-11-23T02:57:00Z", received_at: "2026-11-23T02:57:01Z", duplicate: false };

describe("CheckInPanel", () => {
  beforeEach(async () => {
    setOnline(true);
    useAuthStore.setState({ accessToken: "t" });
    for (const a of await list()) await remove(a.event_uuid);
  });

  it("asks for permission before reading location", async () => {
    mockGeolocation({ permission: "prompt", position: { latitude: metresNorth(10), longitude: OFFICE.longitude, accuracy: 10 } });
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<CheckInPanel today={today()} />);
    expect(await screen.findByText("Location permission required")).toBeInTheDocument();
    expect(screen.getByTestId("permission-badge")).toHaveTextContent("Permission needed");
  });

  it("shows inside-geofence metrics and checks in successfully (server authority)", async () => {
    const geo = mockGeolocation({ permission: "granted", position: { latitude: metresNorth(35), longitude: OFFICE.longitude, accuracy: 12 } });
    const f = mockFetch((url) => (url.includes("/attendance/check-in/") ? { status: 201, body: success } : { body: {} }));
    renderWithProviders(<CheckInPanel today={today()} />);
    await waitFor(() => expect(screen.getByTestId("check-state")).toHaveAttribute("data-state", "INSIDE_GEOFENCE"));
    expect(screen.getByText("±12 m")).toBeInTheDocument();
    expect(screen.getByText("35 m")).toBeInTheDocument();
    expect(screen.getByText("100 m")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("check-in-button"));
    expect(await screen.findByText(/You checked in successfully at 08:57/)).toBeInTheDocument();
    const call = f.mock.calls.find(([u]) => String(u).includes("/attendance/check-in/"))!;
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(body).toMatchObject({ accuracy: 12, permission_status: "GRANTED_WHEN_IN_USE" });
    expect(body.event_uuid).toMatch(/[0-9a-f-]{36}/);
    expect(body).not.toHaveProperty("distance_m"); // never sends a client-computed distance
    expect(geo.mock.calls[0][2]).toMatchObject({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });

  it("shows OUTSIDE_GEOFENCE with distance", async () => {
    mockGeolocation({ permission: "granted", position: { latitude: metresNorth(400), longitude: OFFICE.longitude, accuracy: 10 } });
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<CheckInPanel today={today()} />);
    await waitFor(() => expect(screen.getByTestId("check-state")).toHaveAttribute("data-state", "OUTSIDE_GEOFENCE"));
    expect(screen.getByText(/about 400 m from Bishkek HQ/)).toBeInTheDocument();
  });

  it("asks to retry when the server reports low GPS accuracy", async () => {
    mockGeolocation({ permission: "granted", position: { latitude: metresNorth(20), longitude: OFFICE.longitude, accuracy: 30 } });
    mockFetch((url) => (url.includes("/check-in/") ? { status: 422, body: { ...success, state: "GPS_ACCURACY_LOW", code: "GEOFENCE_BOUNDARY", message: "Move closer and retry." } } : { body: {} }));
    renderWithProviders(<CheckInPanel today={today()} />);
    await waitFor(() => expect(screen.getByTestId("check-state")).toHaveAttribute("data-state", "INSIDE_GEOFENCE"));
    await userEvent.click(screen.getByTestId("check-in-button"));
    expect(await screen.findByText("GPS accuracy too low — please retry")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("handles denied permission", async () => {
    mockGeolocation({ permission: "denied", error: 1 });
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<CheckInPanel today={today()} />);
    expect((await screen.findAllByText("Location blocked")).length).toBe(2);
    expect(screen.getByTestId("check-state")).toHaveAttribute("data-state", "PERMISSION_DENIED");
    expect(screen.getByTestId("permission-badge")).toHaveTextContent("Location blocked");
  });

  it("queues the check-in offline and marks it pending", async () => {
    mockGeolocation({ permission: "granted", position: { latitude: metresNorth(10), longitude: OFFICE.longitude, accuracy: 8 } });
    const f = mockFetch(() => ({ body: {} }));
    setOnline(false);
    renderWithProviders(<CheckInPanel today={today()} />);
    await waitFor(() => expect(screen.getByTestId("check-state")).toHaveAttribute("data-state", "INSIDE_GEOFENCE"));
    await userEvent.click(screen.getByTestId("check-in-button"));
    expect(await screen.findByText(/saved offline — pending/)).toBeInTheDocument();
    expect(f.mock.calls.some(([u]) => String(u).includes("/check-in/"))).toBe(false);
    const q = await list();
    expect(q).toHaveLength(1);
    expect(q[0].payload.offline).toBe(true);
  });

  it("requires consent first", async () => {
    mockGeolocation({ permission: "granted", position: { latitude: OFFICE.latitude, longitude: OFFICE.longitude, accuracy: 8 } });
    mockFetch((url) => (url.includes("/consent/me/") ? { body: { granted: false, consent_version: null, updated_at: null, required_version: "1.0", policy_text: "Used only for attendance." } } : { body: {} }));
    renderWithProviders(<CheckInPanel today={today({ consent_granted: false })} />);
    expect(await screen.findByText("How your location is used")).toBeInTheDocument();
    expect(await screen.findByText("Used only for attendance.")).toBeInTheDocument();
    expect(screen.queryByTestId("check-in-button")).not.toBeInTheDocument();
  });

  it("shows check-out when checked in", async () => {
    mockGeolocation({ permission: "granted", position: { latitude: OFFICE.latitude, longitude: OFFICE.longitude, accuracy: 8 } });
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<CheckInPanel today={today({ live_session_id: 5, live_status: "OPEN", can_check_out: true, can_start_break: true, can_check_in: false })} />);
    expect(await screen.findByTestId("check-out-button")).toBeEnabled();
    expect(screen.queryByTestId("check-in-button")).not.toBeInTheDocument();
  });
});
