// Pending_Changes_Buffer + local audit + recovery state (Web).
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.1, §8 Web data models.
// Requirements: 16.1, 16.3, 16.4, 16.5, 16.7, 18.8, 20.4.
//
// Built on the existing Dexie infrastructure (`@/db/database`).

import { ref, type Ref } from 'vue'
import Dexie from 'dexie'
import { db } from '@/db/database'
import {
  EDIT_KINDS,
  PAYLOAD_JSON_MAX_BYTES,
  type EditKind,
  type LocalAuditAction,
  type LocalAuditRecord,
  type PendingChange,
  type RecoveryStateRecord
} from '@/types/sync'

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

const UUID_V4_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function assertValidChange(c: Pick<PendingChange,
  'changeId' | 'userId' | 'createdAtUtc' | 'editKind' | 'targetId' | 'payloadJson'
>): void {
  if (typeof c.changeId !== 'string' || !UUID_V4_RE.test(c.changeId)) {
    throw new Error('pendingChanges: changeId must be a UUID v4')
  }
  if (!Number.isInteger(c.userId) || c.userId <= 0) {
    throw new Error('pendingChanges: userId must be a positive integer')
  }
  if (typeof c.createdAtUtc !== 'string' || !c.createdAtUtc) {
    throw new Error('pendingChanges: createdAtUtc must be a non-empty ISO string')
  }
  if (!EDIT_KINDS.includes(c.editKind as EditKind)) {
    throw new Error(`pendingChanges: editKind '${c.editKind}' is not in the enumerated set`)
  }
  if (typeof c.targetId !== 'string') {
    throw new Error('pendingChanges: targetId must be a string')
  }
  if (typeof c.payloadJson !== 'string') {
    throw new Error('pendingChanges: payloadJson must be a string')
  }
  // Byte size check (UTF-8). TextEncoder is available in browsers and modern Node.
  const byteLength = new TextEncoder().encode(c.payloadJson).byteLength
  if (byteLength > PAYLOAD_JSON_MAX_BYTES) {
    throw new Error(
      `pendingChanges: payloadJson is ${byteLength} bytes (max ${PAYLOAD_JSON_MAX_BYTES})`
    )
  }
}

// ---------------------------------------------------------------------------
// Count observable: lightweight Vue ref-backed wrapper.
// One ref per (db, userId), refreshed via Dexie hooks so subscribers see live updates.
// ---------------------------------------------------------------------------

const COUNT_REFS = new WeakMap<typeof db, Map<number, Ref<number>>>()
const HOOKED_DBS = new WeakSet<typeof db>()

function refsFor(database: typeof db): Map<number, Ref<number>> {
  let map = COUNT_REFS.get(database)
  if (!map) {
    map = new Map()
    COUNT_REFS.set(database, map)
  }
  return map
}

async function refreshCount(userId: number, database: typeof db = db): Promise<void> {
  const map = refsFor(database)
  const r = map.get(userId)
  if (!r) return
  r.value = await database.pending_changes.where('userId').equals(userId).count()
}

function ensureHooks(database: typeof db = db): void {
  if (HOOKED_DBS.has(database)) return
  HOOKED_DBS.add(database)
  const onChange = (mod: { userId?: number } | undefined, primaryKey: unknown, _change: unknown) => {
    // Best-effort: if we know the userId, refresh just that one; otherwise refresh all known.
    void primaryKey
    const map = refsFor(database)
    if (mod && typeof mod.userId === 'number' && map.has(mod.userId)) {
      void refreshCount(mod.userId, database)
      return
    }
    for (const uid of map.keys()) void refreshCount(uid, database)
  }
  database.pending_changes.hook('creating', (_pk, obj) => {
    onChange(obj as { userId?: number }, _pk, 'create')
  })
  database.pending_changes.hook('deleting', (_pk, obj) => {
    onChange(obj as { userId?: number }, _pk, 'delete')
  })
  database.pending_changes.hook('updating', (_mod, _pk, obj) => {
    onChange(obj as { userId?: number }, _pk, 'update')
  })
}

// ---------------------------------------------------------------------------
// pendingChangesRepo
// ---------------------------------------------------------------------------

export interface PendingChangesRepo {
  /**
   * Allocate the next `sequenceNumber` and persist the row inside a single
   * `readwrite` transaction. Resolves only after the transaction commits
   * (Req 16.4, 16.7).
   */
  enqueue(change: Omit<PendingChange, 'sequenceNumber'>): Promise<PendingChange>
  /** Returns rows for `userId` ordered by `sequenceNumber` ASC. */
  list(userId: number): Promise<PendingChange[]>
  /** Live count of pending changes for `userId`. */
  count$(userId: number): Ref<number>
  /** True when the buffer for `userId` is empty. */
  isEmpty(userId: number): Promise<boolean>
  /** Atomically delete the listed `changeId`s. Returns the number of rows removed. */
  deleteByIds(userId: number, ids: string[]): Promise<number>
}

function buildRepo(database: typeof db = db): PendingChangesRepo {
  ensureHooks(database)

  return {
    async enqueue(change) {
      assertValidChange(change)
      const userId = change.userId
      const inserted = await database.transaction(
        'rw',
        database.pending_changes,
        database.pending_seq_counters,
        async () => {
          // Allocate next sequenceNumber inside the same transaction.
          // Sequence numbers are strictly monotonic and never re-used
          // after a row is deleted (Req 16.7), so we persist the counter
          // separately from `pending_changes`.
          const counter = await database.pending_seq_counters.get(userId)
          const nextSeq = (counter?.nextSeq ?? 1)
          await database.pending_seq_counters.put({
            userId,
            nextSeq: nextSeq + 1
          })
          const row: PendingChange = { ...change, sequenceNumber: nextSeq }
          await database.pending_changes.add(row)
          return row
        }
      )
      // Awaiting the transaction promise above guarantees commit before resolving.
      await refreshCount(userId, database)
      return inserted
    },

    async list(userId) {
      return database.pending_changes
        .where('[userId+sequenceNumber]')
        .between([userId, Dexie.minKey], [userId, Dexie.maxKey])
        .toArray()
    },

    count$(userId) {
      const map = refsFor(database)
      const existing = map.get(userId)
      if (existing) return existing
      const r = ref(0)
      map.set(userId, r)
      // Initial population.
      void refreshCount(userId, database)
      return r
    },

    async isEmpty(userId) {
      const first = await database.pending_changes
        .where('userId')
        .equals(userId)
        .first()
      return first === undefined
    },

    async deleteByIds(userId, ids) {
      if (ids.length === 0) return 0
      const removed = await database.transaction('rw', database.pending_changes, async () => {
        return database.pending_changes
          .where('changeId')
          .anyOf(ids)
          // Defensive: only remove rows belonging to the active user.
          .filter((row) => row.userId === userId)
          .delete()
      })
      await refreshCount(userId, database)
      return removed
    }
  }
}

// ---------------------------------------------------------------------------

export const pendingChangesRepo: PendingChangesRepo = buildRepo(db)

/**
 * Build a repo bound to a specific Dexie database. Exported for tests that
 * need to simulate a process restart by opening a fresh connection.
 */
export function createPendingChangesRepo(database: typeof db): PendingChangesRepo {
  return buildRepo(database)
}

// ---------------------------------------------------------------------------
// local_audit helpers
// ---------------------------------------------------------------------------

export async function appendLocalAudit(
  action: LocalAuditAction,
  changeId: string,
  database: typeof db = db
): Promise<LocalAuditRecord> {
  if (!UUID_V4_RE.test(changeId)) {
    throw new Error('appendLocalAudit: changeId must be a UUID v4')
  }
  const record: LocalAuditRecord = {
    changeId,
    action,
    atUtc: new Date().toISOString()
  }
  await database.local_audit.put(record)
  return record
}

export async function listLocalAudit(database: typeof db = db): Promise<LocalAuditRecord[]> {
  return database.local_audit.orderBy('atUtc').toArray()
}

// ---------------------------------------------------------------------------
// recovery_state helpers
// ---------------------------------------------------------------------------

export async function getRecoveryState(
  userId: number,
  database: typeof db = db
): Promise<RecoveryStateRecord | undefined> {
  return database.recovery_state.get(userId)
}

export async function setRecoveryState(
  state: RecoveryStateRecord,
  database: typeof db = db
): Promise<void> {
  if (!Number.isInteger(state.userId) || state.userId <= 0) {
    throw new Error('setRecoveryState: userId must be a positive integer')
  }
  await database.recovery_state.put(state)
}

export async function clearRecoveryState(
  userId: number,
  database: typeof db = db
): Promise<void> {
  await database.recovery_state.delete(userId)
}
