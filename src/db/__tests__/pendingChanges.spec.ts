// Unit tests for src/db/pendingChanges.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.1.
// Requirements covered: 16.1, 16.3, 16.4, 16.5, 16.7, 18.8, 20.4.

import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { FamilyOneDatabase } from '@/db/database'
import {
  appendLocalAudit,
  clearRecoveryState,
  createPendingChangesRepo,
  getRecoveryState,
  listLocalAudit,
  setRecoveryState
} from '@/db/pendingChanges'
import {
  PAYLOAD_JSON_MAX_BYTES,
  type EditKind,
  type PendingChange,
  type RecoveryStateRecord
} from '@/types/sync'

// crypto.randomUUID polyfill for older jsdom builds.
function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // RFC 4122 v4 fallback.
  const bytes = new Uint8Array(16)
  for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

function makeChange(
  userId: number,
  overrides: Partial<Omit<PendingChange, 'sequenceNumber'>> = {}
): Omit<PendingChange, 'sequenceNumber'> {
  return {
    changeId: uuid(),
    userId,
    createdAtUtc: new Date().toISOString(),
    editKind: 'member.create' as EditKind,
    targetId: 'm-1',
    payloadJson: '{}',
    ...overrides
  }
}

const DB_NAME = 'familyone_web_db_test'

let database: FamilyOneDatabase

async function openFreshDb(): Promise<FamilyOneDatabase> {
  // Drop any leftover state from a previous test before opening.
  await Dexie.delete(DB_NAME)
  const d = new FamilyOneDatabase(DB_NAME)
  await d.open()
  return d
}

beforeEach(async () => {
  database = await openFreshDb()
})

afterEach(async () => {
  database.close()
  await Dexie.delete(DB_NAME)
})

describe('pendingChangesRepo.enqueue', () => {
  it('allocates strictly increasing sequence numbers per user', async () => {
    const repo = createPendingChangesRepo(database)

    const a = await repo.enqueue(makeChange(1))
    const b = await repo.enqueue(makeChange(1))
    const c = await repo.enqueue(makeChange(1))

    expect(a.sequenceNumber).toBe(1)
    expect(b.sequenceNumber).toBe(2)
    expect(c.sequenceNumber).toBe(3)

    const list = await repo.list(1)
    expect(list.map((r) => r.sequenceNumber)).toEqual([1, 2, 3])
    expect(list.map((r) => r.changeId)).toEqual([a.changeId, b.changeId, c.changeId])
  })

  it('keeps sequence numbers independent across users', async () => {
    const repo = createPendingChangesRepo(database)

    const a1 = await repo.enqueue(makeChange(1))
    const b1 = await repo.enqueue(makeChange(2))
    const a2 = await repo.enqueue(makeChange(1))
    const b2 = await repo.enqueue(makeChange(2))

    expect(a1.sequenceNumber).toBe(1)
    expect(a2.sequenceNumber).toBe(2)
    expect(b1.sequenceNumber).toBe(1)
    expect(b2.sequenceNumber).toBe(2)
  })

  it('persists sequence numbers across a simulated reload (new connection)', async () => {
    const repo = createPendingChangesRepo(database)
    await repo.enqueue(makeChange(1))
    await repo.enqueue(makeChange(1))
    database.close()

    // Open a brand new connection to the same DB name. fake-indexeddb persists
    // across connections within the same IDBFactory instance.
    const reopened = new FamilyOneDatabase(DB_NAME)
    await reopened.open()
    const repo2 = createPendingChangesRepo(reopened)

    const next = await repo2.enqueue(makeChange(1))
    expect(next.sequenceNumber).toBe(3)

    const list = await repo2.list(1)
    expect(list.map((r) => r.sequenceNumber)).toEqual([1, 2, 3])
    reopened.close()
  })

  it('rejects payloads larger than PAYLOAD_JSON_MAX_BYTES', async () => {
    const repo = createPendingChangesRepo(database)
    const tooBig = 'x'.repeat(PAYLOAD_JSON_MAX_BYTES + 1)
    await expect(
      repo.enqueue(makeChange(1, { payloadJson: tooBig }))
    ).rejects.toThrow(/payloadJson is/)
  })

  it('rejects unknown editKind values', async () => {
    const repo = createPendingChangesRepo(database)
    await expect(
      repo.enqueue(makeChange(1, { editKind: 'bogus.kind' as EditKind }))
    ).rejects.toThrow(/editKind/)
  })

  it('rejects non-UUID changeIds', async () => {
    const repo = createPendingChangesRepo(database)
    await expect(
      repo.enqueue(makeChange(1, { changeId: 'not-a-uuid' }))
    ).rejects.toThrow(/UUID v4/)
  })
})

describe('pendingChangesRepo.list / isEmpty / count$', () => {
  it('isEmpty returns true on empty buffer and false after enqueue', async () => {
    const repo = createPendingChangesRepo(database)
    expect(await repo.isEmpty(1)).toBe(true)
    await repo.enqueue(makeChange(1))
    expect(await repo.isEmpty(1)).toBe(false)
  })

  it('count$(userId) reflects the buffer size for that user', async () => {
    const repo = createPendingChangesRepo(database)
    const counter = repo.count$(1)
    // initial async refresh
    await new Promise((r) => setTimeout(r, 0))
    expect(counter.value).toBe(0)

    await repo.enqueue(makeChange(1))
    await repo.enqueue(makeChange(1))
    await new Promise((r) => setTimeout(r, 0))
    expect(counter.value).toBe(2)

    await repo.enqueue(makeChange(2)) // different user
    await new Promise((r) => setTimeout(r, 0))
    expect(counter.value).toBe(2)
  })
})

describe('pendingChangesRepo.deleteByIds', () => {
  it('removes only the listed ids and leaves the rest untouched', async () => {
    const repo = createPendingChangesRepo(database)
    const a = await repo.enqueue(makeChange(1))
    const b = await repo.enqueue(makeChange(1))
    const c = await repo.enqueue(makeChange(1))

    const removed = await repo.deleteByIds(1, [a.changeId, c.changeId])
    expect(removed).toBe(2)

    const remaining = await repo.list(1)
    expect(remaining.map((r) => r.changeId)).toEqual([b.changeId])
    // The remaining row keeps its original sequence number.
    expect(remaining[0]!.sequenceNumber).toBe(2)
  })

  it('does not delete rows owned by a different user', async () => {
    const repo = createPendingChangesRepo(database)
    const mine = await repo.enqueue(makeChange(1))
    const theirs = await repo.enqueue(makeChange(2))

    const removed = await repo.deleteByIds(1, [mine.changeId, theirs.changeId])
    expect(removed).toBe(1)

    expect((await repo.list(1)).length).toBe(0)
    expect((await repo.list(2)).map((r) => r.changeId)).toEqual([theirs.changeId])
  })

  it('returns 0 when given an empty id list', async () => {
    const repo = createPendingChangesRepo(database)
    await repo.enqueue(makeChange(1))
    expect(await repo.deleteByIds(1, [])).toBe(0)
    expect((await repo.list(1)).length).toBe(1)
  })

  it('does not affect future sequence allocation for the same user', async () => {
    const repo = createPendingChangesRepo(database)
    const a = await repo.enqueue(makeChange(1))
    const b = await repo.enqueue(makeChange(1))
    await repo.deleteByIds(1, [a.changeId, b.changeId])
    const c = await repo.enqueue(makeChange(1))
    // Sequence numbers are strictly increasing and never re-used (Req 16.7).
    expect(c.sequenceNumber).toBe(3)
  })
})

describe('appendLocalAudit / listLocalAudit', () => {
  it('persists audit rows with action and timestamp', async () => {
    const id = uuid()
    await appendLocalAudit('pending_change_uploaded', id, database)
    const rows = await listLocalAudit(database)
    expect(rows).toHaveLength(1)
    expect(rows[0]!.action).toBe('pending_change_uploaded')
    expect(rows[0]!.changeId).toBe(id)
    expect(typeof rows[0]!.atUtc).toBe('string')
  })
})

describe('recovery_state helpers', () => {
  it('round-trips and clears the per-user recovery state', async () => {
    const state: RecoveryStateRecord = {
      userId: 42,
      revokedReason: 'signed_in_on_other_device',
      pendingCount: 7,
      openedAtUtc: new Date().toISOString(),
      state: 'Shown'
    }

    expect(await getRecoveryState(42, database)).toBeUndefined()
    await setRecoveryState(state, database)
    expect(await getRecoveryState(42, database)).toEqual(state)

    await clearRecoveryState(42, database)
    expect(await getRecoveryState(42, database)).toBeUndefined()
  })
})
