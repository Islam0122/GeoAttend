import { useAuthStore } from "@/stores/auth";
import type { TokenPair } from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown, public code?: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

export function errorMessage(body: unknown, status: number): { message: string; code?: string } {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if ("state" in b && typeof b.message === "string") return { message: b.message, code: String(b.code ?? "") };
    const d = b.detail;
    if (typeof d === "string") return { message: d };
    if (Array.isArray(d)) return { message: d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ") };
    if (d && typeof d === "object") {
      const o = d as Record<string, unknown>;
      return { message: String(o.message ?? o.code ?? `Request failed (${status})`), code: o.code ? String(o.code) : undefined };
    }
  }
  if (status === 0) return { message: "Network error — check your connection." };
  if (status === 429) return { message: "Too many requests. Please wait a moment." };
  return { message: `Request failed (${status})` };
}

let refreshing: Promise<boolean> | null = null;

/** Rotate the refresh cookie and obtain a new access token. Single-flight across concurrent requests. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE}/auth/refresh/`, { method: "POST", credentials: "include" })
    .then(async (r) => {
      if (!r.ok) {
        useAuthStore.getState().clear();
        return false;
      }
      useAuthStore.getState().setAccessToken(((await r.json()) as TokenPair).access_token);
      return true;
    })
    .catch(() => false)
    .finally(() => (refreshing = null));
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Params;
  /** Return non-2xx JSON bodies instead of throwing (used by GPS check-in which returns rich 4xx results). */
  raw?: boolean;
}

export async function api<T>(path: string, opts: RequestOptions = {}, retry = true): Promise<T> {
  const qs = opts.params
    ? "?" + new URLSearchParams(Object.entries(opts.params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString()
    : "";
  const token = useAuthStore.getState().accessToken;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${qs}`, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, errorMessage(null, 0).message);
  }
  if (res.status === 401 && retry && token && (await refreshSession())) return api<T>(path, opts, false);
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok && !(opts.raw && body && typeof body === "object")) {
    const { message, code } = errorMessage(body, res.status);
    throw new ApiError(res.status, message, body, code);
  }
  return body as T;
}

export async function downloadCsv(path: string, params: Params, filename: string) {
  const token = useAuthStore.getState().accessToken;
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)]));
  const res = await fetch(`${API_BASE}${path}?${qs}`, { credentials: "include", headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `Export failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
