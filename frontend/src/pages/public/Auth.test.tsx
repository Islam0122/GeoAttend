import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { Login, Register } from "./Auth";

describe("auth forms", () => {
  it("validates login input with zod", async () => {
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<Login />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
  });

  it("shows API errors on failed login", async () => {
    mockFetch(() => ({ status: 401, body: { detail: "Invalid email or password" } }));
    renderWithProviders(<Login />);
    await userEvent.type(screen.getByLabelText("Work email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid email or password")).toBeInTheDocument();
  });

  it("requires a 10+ character password on registration", async () => {
    mockFetch(() => ({ body: {} }));
    renderWithProviders(<Register />);
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(await screen.findByText("At least 10 characters")).toBeInTheDocument();
    expect(screen.getByText("Company name is required")).toBeInTheDocument();
  });
});
