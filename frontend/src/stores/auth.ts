import { create } from "zustand";
import type { Me } from "@/api/types";

/** Access token lives only in memory. The refresh token is an httpOnly cookie the JS never sees. */
interface AuthState {
  accessToken: string | null;
  me: Me | null;
  bootstrapped: boolean;
  setAccessToken(t: string | null): void;
  setMe(me: Me | null): void;
  setBootstrapped(): void;
  clear(): void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  me: null,
  bootstrapped: false,
  setAccessToken: (accessToken) => set({ accessToken }),
  setMe: (me) => set({ me }),
  setBootstrapped: () => set({ bootstrapped: true }),
  clear: () => set({ accessToken: null, me: null }),
}));
