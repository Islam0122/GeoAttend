import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export function renderWithProviders(ui: ReactNode, { route = "/" } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter></QueryClientProvider>);
}

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;

/** Route-based fetch mock. Unmatched requests return 404. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const r = handler(url, init);
    if (!r) return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404, headers: { "content-type": "application/json" } });
    if (r.status === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function mockGeolocation(opts: { permission?: "granted" | "denied" | "prompt"; position?: { latitude: number; longitude: number; accuracy: number }; error?: number }) {
  const getCurrentPosition = vi.fn((ok: PositionCallback, fail?: PositionErrorCallback | null, _opts?: PositionOptions) => {
    void _opts;
    if (opts.error) {
      fail?.({ code: opts.error, message: "x", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError);
      return;
    }
    const p = opts.position!;
    ok({ coords: { ...p, altitude: null, altitudeAccuracy: null, heading: null, speed: null }, timestamp: Date.now() } as unknown as GeolocationPosition);
  });
  Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition, watchPosition: vi.fn(), clearWatch: vi.fn() }, configurable: true });
  Object.defineProperty(navigator, "permissions", {
    value: { query: vi.fn(async () => ({ state: opts.permission ?? "granted", addEventListener: vi.fn(), removeEventListener: vi.fn() })) },
    configurable: true,
  });
  return getCurrentPosition;
}

export function setOnline(v: boolean) {
  Object.defineProperty(navigator, "onLine", { value: v, configurable: true });
}
