import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Me } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { AppShell } from "./AppShell";

const base: Me = { id: 1, email: "m@x.co", full_name: "Mia Manager", role: "MANAGER", organization_id: 1, organization_name: "Acme", organization_timezone: "UTC", subscription_plan: "BUSINESS", employee_id: 7, managed_department_ids: [1], has_password: true, google_linked: false };

describe("AppShell (responsive navigation & roles)", () => {
  it("shows Me + Team sections for a manager and opens the mobile drawer", async () => {
    mockFetch(() => ({ body: [] }));
    useAuthStore.setState({ me: base, accessToken: "t" });
    renderWithProviders(<AppShell />, { route: "/app" });
    expect(screen.getAllByText("Team dashboard").length).toBeGreaterThan(0);
    expect(screen.queryByText("Offices & geofences")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(drawer).getByText("Approvals")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Quick" })).toBeInTheDocument(); // mobile bottom nav for employees
  });

  it("shows workspace admin for owners and the offline indicator", async () => {
    mockFetch(() => ({ body: [] }));
    useAuthStore.setState({ me: { ...base, role: "OWNER", employee_id: null }, accessToken: "t" });
    useUiStore.setState({ online: false });
    renderWithProviders(<AppShell />, { route: "/app/admin" });
    expect(screen.getAllByText("Offices & geofences").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Billing").length).toBeGreaterThan(0);
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Quick" })).not.toBeInTheDocument();
  });

  it("hides admin and monitoring from accountants", async () => {
    mockFetch(() => ({ body: [] }));
    useAuthStore.setState({ me: { ...base, role: "ACCOUNTANT", employee_id: null }, accessToken: "t" });
    useUiStore.setState({ online: true });
    renderWithProviders(<AppShell />, { route: "/app/admin" });
    expect(screen.getAllByText("Reports").length).toBeGreaterThan(0);
    expect(screen.queryByText("Monitoring")).not.toBeInTheDocument();
    expect(screen.queryByText("Employees")).not.toBeInTheDocument();
  });
});
