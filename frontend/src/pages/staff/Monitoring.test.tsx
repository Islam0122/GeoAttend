import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MonitoringEmployee, SessionState, ZoneStatus } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { Monitoring } from "./Monitoring";

vi.mock("@/components/GeoMap", () => ({ GeoMap: () => <div data-testid="map" /> }));

const ZONES: [ZoneStatus, string][] = [["INSIDE", "Inside"], ["OUTSIDE", "Outside"], ["LOCATION_DETECTED", "Detected"], ["STALE", "Stale"],
  ["UNKNOWN", "Unknown"], ["LOCATION_DENIED", "Location denied"], ["NO_OFFICE", "No office"]];
const SESSIONS: SessionState[] = ["ACTIVE", "TEMPORARY_EXIT", "COMPLETED", "NOT_STARTED", "PENDING_CHECKOUT", "ACTIVE", "NOT_STARTED"];

const row = (i: number, zone: ZoneStatus): MonitoringEmployee => ({
  employee_id: i, employee_name: `Emp ${i}`, position: "Dev", department_name: "Eng", assigned_offices: zone === "NO_OFFICE" ? [] : ["HQ"], office_id: 1, office_name: "HQ",
  zone_status: zone, zone_reason: "r", distance_m: zone === "UNKNOWN" ? null : 30 + i, accuracy_m: zone === "UNKNOWN" ? null : 9, last_update: null, last_activity: null,
  permission: zone === "LOCATION_DENIED" ? "DENIED" : "GRANTED_WHEN_IN_USE", consent_granted: true, attendance_status: i % 2 ? "LATE" : "PRESENT", session_status: SESSIONS[i],
  check_in_time: null, check_out_time: null, working_minutes: 61, late_minutes: i % 2 ? 5 : 0, temporary_exit_started_at: null, temporary_exit_minutes: 0,
});

describe("Employee Monitoring", () => {
  it("renders every zone and session status from server data, with summary cards and no coordinates", async () => {
    useAuthStore.setState({ me: { organization_timezone: "UTC" } as never, accessToken: "t" });
    const rows = ZONES.map(([z], i) => row(i, z));
    const f = mockFetch((u) => u.includes("/monitoring/employees/") ? { body: rows }
      : u.includes("/monitoring/summary/") ? { body: { generated_at: "", total_employees: 7, currently_inside: 1, currently_outside: 1, active_sessions: 2, late_today: 3, temporary_exits: 1, location_unavailable: 3, stale: 1, no_permission: 1, no_office: 1, stale_after_seconds: 120 } }
      : { body: [] });
    renderWithProviders(<Monitoring />);
    for (const [z, label] of ZONES) {
      const r = await screen.findByTestId(`row-${ZONES.findIndex(([x]) => x === z)}`);
      expect(within(r).getByTestId("zone")).toHaveTextContent(label);
    }
    expect(within(screen.getByTestId("row-1")).getByTestId("session")).toHaveTextContent("Temporary exit");
    expect(within(screen.getByTestId("row-2")).getByTestId("session")).toHaveTextContent("Completed");
    expect(screen.getByText("Currently inside")).toBeInTheDocument();
    expect(screen.getByText("Location unavailable")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/latitude|longitude/i);
    expect(screen.getByTestId("updated-at")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Temporary exits" }));
    await waitFor(() => expect(f.mock.calls.some(([u]) => String(u).includes("filter=temporary_exit"))).toBe(true));
  });
});
