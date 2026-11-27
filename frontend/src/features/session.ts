import { api, refreshSession } from "@/api/client";
import { queryClient } from "@/api/queryClient";
import type { Me, TokenPair } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { browserLabel, deviceId } from "@/lib/device";

async function loadMe(): Promise<Me | null> {
  try {
    const me = await api<Me>("/auth/me/");
    useAuthStore.getState().setMe(me);
    if (me.employee_id) void registerDevice();
    return me;
  } catch {
    useAuthStore.getState().clear();
    return null;
  }
}

/** On app start: exchange the httpOnly refresh cookie for an access token. */
export async function bootstrapSession(): Promise<void> {
  if (await refreshSession()) await loadMe();
  useAuthStore.getState().setBootstrapped();
}

export async function acceptTokens(t: TokenPair): Promise<Me | null> {
  useAuthStore.getState().setAccessToken(t.access_token);
  return loadMe();
}

export async function logout(): Promise<void> {
  await api("/auth/logout/", { method: "POST" }).catch(() => undefined);
  useAuthStore.getState().clear();
  queryClient.clear();
}

/** Register this browser as the employee's device (required by the server for GPS events). */
export async function registerDevice(permission?: string): Promise<void> {
  let perm = permission;
  if (!perm) {
    try {
      const s = await navigator.permissions?.query({ name: "geolocation" as PermissionName });
      perm = s?.state === "granted" ? "GRANTED_WHEN_IN_USE" : s?.state === "denied" ? "DENIED" : "UNKNOWN";
    } catch {
      perm = "UNKNOWN";
    }
  }
  await api("/devices/register/", {
    body: { device_id: deviceId(), platform: "WEB", model: browserLabel(), os_version: null, app_version: "pwa-2.0", location_permission: perm, precise_location: true, background_enabled: false },
  }).catch(() => undefined);
}

// ---- Google Sign-In (OpenID Connect implicit id_token flow; no Google Maps, no SDK) ----
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
export const googleEnabled = !!GOOGLE_CLIENT_ID;

export function startGoogleSignIn(intent: "login" | "register", extra?: Record<string, string>) {
  const nonce = crypto.randomUUID();
  const state = crypto.randomUUID();
  sessionStorage.setItem("geoattend.google", JSON.stringify({ nonce, state, intent, extra: extra ?? {} }));
  const p = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID ?? "", response_type: "id_token", scope: "openid email profile", nonce, state, prompt: "select_account",
    redirect_uri: `${window.location.origin}/auth/google/callback`,
  });
  window.location.assign(`https://accounts.google.com/o/oauth2/v2/auth?${p}`);
}

export function readGoogleCallback(hash: string): { idToken: string; nonce: string; intent: string; extra: Record<string, string> } {
  const p = new URLSearchParams(hash.replace(/^#/, ""));
  const saved = JSON.parse(sessionStorage.getItem("geoattend.google") ?? "null") as { nonce: string; state: string; intent: string; extra: Record<string, string> } | null;
  sessionStorage.removeItem("geoattend.google");
  if (p.get("error")) throw new Error(`Google sign-in cancelled (${p.get("error")})`);
  if (!saved || p.get("state") !== saved.state) throw new Error("Sign-in session expired. Please try again.");
  const idToken = p.get("id_token");
  if (!idToken) throw new Error("Google did not return an ID token.");
  return { idToken, nonce: saved.nonce, intent: saved.intent, extra: saved.extra };
}


/** Report the browser's location-permission state (never coordinates). Registers the device if needed. */
export async function reportPermission(permission: string): Promise<void> {
  try {
    await api("/devices/heartbeat/", { body: { device_id: deviceId(), location_permission: permission, precise_location: true, background_enabled: false } });
  } catch {
    await registerDevice(permission);
  }
}
