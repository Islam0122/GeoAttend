/**
 * Offline attendance queue (IndexedDB). Check-in/out taken while offline are stored with the client GPS
 * timestamp and are PENDING until the server validates them; the server records its own received time.
 */
export type QueuedKind = "CHECK_IN" | "CHECK_OUT";

export interface QueuedAction {
  event_uuid: string;
  kind: QueuedKind;
  payload: { event_uuid: string; device_id: string; latitude: number; longitude: number; accuracy: number; recorded_at: string; permission_status: string; offline: boolean };
  queued_at: string;
  attempts: number;
  last_error?: string;
}

export interface SyncedResult {
  event_uuid: string;
  kind: QueuedKind;
  ok: boolean;
  message: string;
  recorded_at: string;
  synced_at: string;
}

const DB = "geoattend";
const STORE = "queue";
const memory = new Map<string, QueuedAction>(); // fallback when IndexedDB is unavailable (private mode, tests)

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === "undefined") return resolve(null);
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "event_uuid" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await openDb();
  if (!db) return undefined;
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const req = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(req ? (req.result as T) : undefined);
    t.onerror = () => reject(t.error);
  });
}

export async function enqueue(a: QueuedAction): Promise<void> {
  memory.set(a.event_uuid, a);
  await tx("readwrite", (s) => s.put(a)).catch(() => undefined);
}

export async function list(): Promise<QueuedAction[]> {
  const rows = (await tx<QueuedAction[]>("readonly", (s) => s.getAll()).catch(() => undefined)) ?? [...memory.values()];
  return rows.sort((a, b) => a.payload.recorded_at.localeCompare(b.payload.recorded_at));
}

export async function remove(id: string): Promise<void> {
  memory.delete(id);
  await tx("readwrite", (s) => s.delete(id)).catch(() => undefined);
}

export async function update(a: QueuedAction): Promise<void> {
  await enqueue(a);
}

export type Sender = (a: QueuedAction) => Promise<{ status: number; ok: boolean; message: string }>;

/**
 * Flush in recorded order. Network errors stop the flush (retry later); server rejections (4xx) are final and
 * removed from the queue so one bad item never blocks the rest; 5xx are retried with backoff.
 */
export async function flush(send: Sender): Promise<SyncedResult[]> {
  const out: SyncedResult[] = [];
  for (const a of await list()) {
    let r: { status: number; ok: boolean; message: string };
    try {
      r = await send(a);
    } catch {
      break; // still offline
    }
    if (r.ok || (r.status >= 400 && r.status < 500)) {
      await remove(a.event_uuid);
      out.push({ event_uuid: a.event_uuid, kind: a.kind, ok: r.ok, message: r.message, recorded_at: a.payload.recorded_at, synced_at: new Date().toISOString() });
    } else {
      await update({ ...a, attempts: a.attempts + 1, last_error: r.message });
      break;
    }
  }
  return out;
}
