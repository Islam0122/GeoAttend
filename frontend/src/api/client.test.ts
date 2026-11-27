import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "@/stores/auth";
import { mockFetch } from "@/test/utils";
import { api, ApiError, errorMessage } from "./client";

describe("API error handling", () => {
  beforeEach(() => useAuthStore.setState({ accessToken: "old", me: null }));

  it("normalizes FastAPI error shapes", () => {
    expect(errorMessage({ detail: "Nope" }, 400).message).toBe("Nope");
    expect(errorMessage({ detail: [{ loc: ["body", "email"], msg: "bad email" }] }, 422).message).toBe("email: bad email");
    expect(errorMessage({ detail: { code: "PLAN_LIMIT_REACHED", message: "Upgrade" } }, 402)).toEqual({ message: "Upgrade", code: "PLAN_LIMIT_REACHED" });
    expect(errorMessage(null, 0).message).toMatch(/network/i);
    expect(errorMessage({}, 429).message).toMatch(/too many/i);
  });

  it("throws ApiError with status and code", async () => {
    mockFetch(() => ({ status: 409, body: { detail: { code: "ALREADY_CHECKED_IN", message: "Already in" } } }));
    await expect(api("/x/")).rejects.toMatchObject({ status: 409, code: "ALREADY_CHECKED_IN", message: "Already in" });
  });

  it("refreshes the access token once on 401 and retries", async () => {
    let calls = 0;
    const f = mockFetch((url, init) => {
      if (url.endsWith("/auth/refresh/")) return { body: { access_token: "new", refresh_token: "r", expires_in: 60 } };
      calls++;
      const auth = (init?.headers as Record<string, string>).Authorization;
      return auth === "Bearer new" ? { body: { ok: true } } : { status: 401, body: { detail: "expired" } };
    });
    await expect(api<{ ok: boolean }>("/attendance/")).resolves.toEqual({ ok: true });
    expect(calls).toBe(2);
    expect(useAuthStore.getState().accessToken).toBe("new");
    expect(f.mock.calls.some(([u]) => String(u).endsWith("/auth/refresh/"))).toBe(true);
  });

  it("clears the session when refresh fails", async () => {
    mockFetch((url) => (url.endsWith("/auth/refresh/") ? { status: 401, body: { detail: "reuse" } } : { status: 401, body: { detail: "expired" } }));
    await expect(api("/attendance/")).rejects.toBeInstanceOf(ApiError);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("returns rich 4xx bodies in raw mode (GPS results)", async () => {
    mockFetch(() => ({ status: 422, body: { state: "GPS_ACCURACY_LOW", code: "GPS_ACCURACY_LOW", message: "retry" } }));
    await expect(api("/attendance/check-in/", { body: {}, raw: true })).resolves.toMatchObject({ state: "GPS_ACCURACY_LOW" });
  });
});
