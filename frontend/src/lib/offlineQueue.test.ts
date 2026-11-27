import { beforeEach, describe, expect, it, vi } from "vitest";
import { enqueue, flush, list, remove, type QueuedAction } from "./offlineQueue";

const item = (id: string, at: string): QueuedAction => ({
  event_uuid: id, kind: "CHECK_IN", queued_at: at, attempts: 0,
  payload: { event_uuid: id, device_id: "web-x", latitude: 1, longitude: 2, accuracy: 10, recorded_at: at, permission_status: "GRANTED_WHEN_IN_USE", offline: true },
});

describe("offline queue", () => {
  beforeEach(async () => { for (const a of await list()) await remove(a.event_uuid); });

  it("flushes in recorded order and removes accepted + rejected items", async () => {
    await enqueue(item("b", "2026-11-23T09:01:00Z"));
    await enqueue(item("a", "2026-11-23T09:00:00Z"));
    const seen: string[] = [];
    const res = await flush(async (x) => { seen.push(x.event_uuid); return x.event_uuid === "a" ? { status: 201, ok: true, message: "ok" } : { status: 422, ok: false, message: "OUTSIDE_GEOFENCE" }; });
    expect(seen).toEqual(["a", "b"]);
    expect(res.map((r) => r.ok)).toEqual([true, false]);
    expect(await list()).toHaveLength(0);
  });

  it("keeps items when offline (network error) and on 5xx", async () => {
    await enqueue(item("c", "2026-11-23T09:00:00Z"));
    await flush(vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    expect(await list()).toHaveLength(1);
    await flush(async () => ({ status: 503, ok: false, message: "down" }));
    const [left] = await list();
    expect(left.attempts).toBe(1);
    expect(left.last_error).toBe("down");
  });
});
