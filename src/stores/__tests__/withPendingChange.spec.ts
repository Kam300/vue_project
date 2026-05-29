// Unit tests for src/stores/withPendingChange.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.2.
// Requirements covered: 16.3, 16.4, 16.8.

import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { FamilyOneDatabase, db } from '@/db/database'
import { useAppStore } from '@/stores/appStore'
import { SYNC_TICK_EVENT, withPendingChange } from '@/stores/withPendingChange'

const DB_NAME = 'familyone_web_db' // withPendingChange uses the default `db`

let database: FamilyOneDatabase

async function openFreshDb(): Promise<FamilyOneDatabase> {
  await Dexie.delete(DB_NAME)
  // The module-level `db` instance points at this name; reopen it so tests
  // observe the same connection withPendingChange writes to.
  if ((db as unknown as { isOpen: () => boolean }).isOpen()) db.close()
  await db.open()
  return db
}

beforeEach(async () => {
  setActivePinia(createPinia())
  database = await openFreshDb()
  // Stub an authenticated user so resolveUserId() succeeds.
  const app = useAppStore()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(app as any).authUser = { id: 7, displayName: 'tester' }
})

afterEach(async () => {
  database.close()
  await Dexie.delete(DB_NAME)
})

describe('withPendingChange', () => {
  it('enqueues the pending change BEFORE apply() runs (Req 16.4)', async () => {
    const order: string[] = []

    await withPendingChange('member.create', '', { foo: 'bar' }, async () => {
      // At this point the row MUST already be in the buffer.
      const rows = await database.pending_changes.where('userId').equals(7).toArray()
      order.push(`apply(buffer=${rows.length})`)
      return undefined
    })

    expect(order).toEqual(['apply(buffer=1)'])

    const persisted = await database.pending_changes.where('userId').equals(7).toArray()
    expect(persisted).toHaveLength(1)
    expect(persisted[0]!.editKind).toBe('member.create')
    expect(persisted[0]!.targetId).toBe('')
    expect(persisted[0]!.payloadJson).toBe(JSON.stringify({ foo: 'bar' }))
    expect(persisted[0]!.sequenceNumber).toBe(1)
    expect(typeof persisted[0]!.changeId).toBe('string')
    expect(typeof persisted[0]!.createdAtUtc).toBe('string')
  })

  it('keeps the pending_changes row when apply() throws (Req 16.8)', async () => {
    const boom = new Error('apply failed')

    await expect(
      withPendingChange('member.update', '42', { id: 42 }, async () => {
        throw boom
      })
    ).rejects.toBe(boom)

    const persisted = await database.pending_changes.where('userId').equals(7).toArray()
    expect(persisted).toHaveLength(1)
    expect(persisted[0]!.editKind).toBe('member.update')
    expect(persisted[0]!.targetId).toBe('42')
  })

  it('dispatches the familyone:edit-tick event on success (task 6.2 contract)', async () => {
    const seen: Event[] = []
    const listener = (e: Event): void => {
      seen.push(e)
    }
    window.addEventListener(SYNC_TICK_EVENT, listener)
    try {
      await withPendingChange('member.delete', '99', { id: 99 }, async () => {
        return 'ok'
      })
    } finally {
      window.removeEventListener(SYNC_TICK_EVENT, listener)
    }

    expect(seen).toHaveLength(1)
    expect(seen[0]!.type).toBe(SYNC_TICK_EVENT)
  })

  it('does NOT dispatch the edit-tick event when apply() throws', async () => {
    let dispatched = 0
    const listener = (): void => {
      dispatched += 1
    }
    window.addEventListener(SYNC_TICK_EVENT, listener)
    try {
      await expect(
        withPendingChange('member.update', '1', {}, async () => {
          throw new Error('nope')
        })
      ).rejects.toThrow('nope')
    } finally {
      window.removeEventListener(SYNC_TICK_EVENT, listener)
    }

    expect(dispatched).toBe(0)
  })

  it('throws when no authenticated user is present', async () => {
    const app = useAppStore()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(app as any).authUser = null

    await expect(
      withPendingChange('member.create', '', {}, async () => undefined)
    ).rejects.toThrow(/no authenticated user/)
  })
})
