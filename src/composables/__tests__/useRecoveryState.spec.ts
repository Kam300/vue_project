// Unit tests for src/composables/useRecoveryState.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.4.
// Requirements covered: 18.8, 20.1, 20.4.

import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks for the heavy services. These run before the module under test loads.
// ---------------------------------------------------------------------------

const { recoveryRequestListeners, setRecoveryShownMock } = vi.hoisted(() => ({
  recoveryRequestListeners: new Set<
    (info: { userId: number; reason: string; pendingCount: number }) => void
  >(),
  setRecoveryShownMock: vi.fn()
}))

vi.mock('@/services/api', async (orig) => {
  const real = (await orig()) as Record<string, unknown>
  return {
    ...real,
    onRecoveryRequest: (
      fn: (info: { userId: number; reason: string; pendingCount: number }) => void
    ) => {
      recoveryRequestListeners.add(fn)
      return () => {
        recoveryRequestListeners.delete(fn)
      }
    },
    _setRecoveryShown: (...args: unknown[]) => {
      setRecoveryShownMock(...args)
    }
  }
})

vi.mock('@/services/authIdentity', () => ({
  connectYandexIdentity: vi.fn().mockResolvedValue('ok')
}))

vi.mock('@/services/syncTicker', () => ({
  onSyncResult: vi.fn(() => () => {}),
  _runTickForTests: vi.fn().mockResolvedValue(undefined)
}))

// ---------------------------------------------------------------------------

import { FamilyOneDatabase, db } from '@/db/database'
import { useAppStore } from '@/stores/appStore'
import { setRecoveryState } from '@/db/pendingChanges'
import {
  _bootstrapFromIndexedDbForTests,
  _resetForTests,
  useRecoveryState
} from '@/composables/useRecoveryState'
import type { RecoveryStateRecord } from '@/types/sync'

const DB_NAME = 'familyone_web_db'

let database: FamilyOneDatabase

async function openFreshDb(): Promise<FamilyOneDatabase> {
  await Dexie.delete(DB_NAME)
  if ((db as unknown as { isOpen: () => boolean }).isOpen()) db.close()
  await db.open()
  return db
}

beforeEach(async () => {
  setActivePinia(createPinia())
  database = await openFreshDb()
  recoveryRequestListeners.clear()
  setRecoveryShownMock.mockReset()
  _resetForTests()
})

afterEach(async () => {
  database.close()
  await Dexie.delete(DB_NAME)
})

describe('useRecoveryState — bootstrap from persisted IndexedDB row (Req 18.8)', () => {
  it('opens itself with the stored pendingCount when a recovery_state row is present', async () => {
    const stored: RecoveryStateRecord = {
      userId: 42,
      revokedReason: 'signed_in_on_other_device',
      pendingCount: 7,
      openedAtUtc: '2024-01-15T12:34:56.000Z',
      state: 'Shown'
    }
    await setRecoveryState(stored)

    // Simulate an authenticated user matching the persisted row so the
    // bootstrap selector picks up the right userId.
    const app = useAppStore()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(app as any).authUser = { id: 42, displayName: 'tester', providers: [] }

    await _bootstrapFromIndexedDbForTests()

    const state = useRecoveryState()
    expect(state.isOpen.value).toBe(true)
    expect(state.state.value).toBe('Shown')
    expect(state.userId.value).toBe(42)
    expect(state.revokedReason.value).toBe('signed_in_on_other_device')
    expect(state.pendingCount.value).toBe(7)
    expect(state.openedAtUtc.value).toBe('2024-01-15T12:34:56.000Z')
    // The recovery gate must be re-armed so authenticated calls stay blocked.
    expect(setRecoveryShownMock).toHaveBeenCalledWith(true)
  })

  it('stays Idle when no recovery_state row exists', async () => {
    await _bootstrapFromIndexedDbForTests()

    const state = useRecoveryState()
    expect(state.isOpen.value).toBe(false)
    expect(state.state.value).toBe('Idle')
    expect(state.pendingCount.value).toBe(0)
  })
})
