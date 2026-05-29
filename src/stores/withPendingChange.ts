// Edit interception helper for the Pending_Changes_Buffer.
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.2.
// Requirements: 16.3, 16.4, 16.8.
//
// Every Pinia mutation that mutates the family tree is wrapped by this helper
// so the durable enqueue happens BEFORE `apply()` (i.e. before the UI sees
// success). If `apply()` throws, the pending_changes row is intentionally
// kept in the buffer — the user does not lose data. The error is re-thrown
// so the caller can react.

import { pendingChangesRepo } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import type { EditKind, PendingChange } from '@/types/sync'

/**
 * CustomEvent name dispatched on `window` after a successful `apply()`.
 * The `syncTicker` (task 6.2) subscribes to this event to debounce-trigger
 * `Auto_Sync_Tick`. Until that module exists we rely on the event bus.
 */
export const SYNC_TICK_EVENT = 'familyone:edit-tick'

function resolveUserId(): number {
  // Read from the existing auth snapshot held by the app store.
  // `appStore.init()` populates `authUser` from `authBootstrap()` and keeps
  // it in sync; that is the only place authenticated user state lives in the
  // Web client right now.
  const app = useAppStore()
  const id = app.authUser?.id
  if (!Number.isInteger(id) || (id as number) <= 0) {
    throw new Error('withPendingChange: no authenticated user (authUser.id missing)')
  }
  return id as number
}

function generateChangeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // RFC 4122 v4 fallback for environments without crypto.randomUUID.
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

function dispatchTick(): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(SYNC_TICK_EVENT))
  } catch {
    // Some test environments lack a working CustomEvent constructor; ignore.
  }
}

/**
 * Wrap a Pinia mutation so the corresponding `PendingChange` is durably
 * enqueued before the local apply step runs.
 *
 * Order of operations:
 *   1. Resolve `userId` from the auth snapshot.
 *   2. Build the `PendingChange` (sequenceNumber is allocated inside `enqueue`).
 *   3. `await pendingChangesRepo.enqueue(change)` — durable commit.
 *   4. `await apply()` — local IndexedDB / Pinia mutation.
 *   5. On success, dispatch `familyone:edit-tick` so `syncTicker` runs.
 *   6. On failure, the pending_changes row is intentionally kept; the error
 *      is re-thrown.
 */
export async function withPendingChange<T>(
  editKind: EditKind,
  targetId: string,
  diff: unknown,
  apply: () => Promise<T>
): Promise<T> {
  const userId = resolveUserId()
  const change: Omit<PendingChange, 'sequenceNumber'> = {
    changeId: generateChangeId(),
    userId,
    createdAtUtc: new Date().toISOString(),
    editKind,
    targetId,
    // `payloadJson` carries the diff snapshot so the upload code can
    // reconstruct the cumulative archive even if the in-memory mutation
    // is later rolled back by the caller.
    payloadJson: JSON.stringify(diff ?? null)
  }

  // Durable enqueue MUST resolve before `apply()` runs (Req 16.4).
  await pendingChangesRepo.enqueue(change)

  // Intentionally NOT wrapped in try/catch: if `apply()` throws we want the
  // pending_changes row to stay in the buffer (Req 16.8) and the error to
  // propagate so the UI can surface it.
  const result = await apply()

  // Edge-trigger Auto_Sync_Tick. The real ticker arrives in task 6.2; until
  // then the event bus is the only contract.
  dispatchTick()

  return result
}
