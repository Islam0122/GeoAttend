import { create } from "zustand";
import { api } from "@/api/client";
import type { GpsActionResult } from "@/api/types";
import * as q from "@/lib/offlineQueue";

interface QueueState {
  pending: q.QueuedAction[];
  lastSynced: q.SyncedResult[];
  syncing: boolean;
  refresh(): Promise<void>;
  sync(): Promise<q.SyncedResult[]>;
}

export const sendQueued: q.Sender = async (a) => {
  const path = a.kind === "CHECK_IN" ? "/attendance/check-in/" : "/attendance/check-out/";
  const res = await api<GpsActionResult>(path, { body: a.payload, raw: true }); // throws ApiError(0) when offline
  const ok = res.state === "CHECK_IN_SUCCESS" || res.state === "CHECK_OUT_SUCCESS";
  return { ok, status: ok ? 201 : res.code ? 422 : 500, message: res.message };
};

export const useQueueStore = create<QueueState>((set, get) => ({
  pending: [],
  lastSynced: [],
  syncing: false,
  refresh: async () => set({ pending: await q.list() }),
  sync: async () => {
    if (get().syncing) return [];
    set({ syncing: true });
    try {
      const results = await q.flush(sendQueued);
      if (results.length) set({ lastSynced: [...results, ...get().lastSynced].slice(0, 20) });
      return results;
    } catch {
      return [];
    } finally {
      set({ syncing: false, pending: await q.list() });
    }
  },
}));
