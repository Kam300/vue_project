// Unit tests for src/services/syncTicker.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.3.
// Requirements covered: 13.1, 13.2, 17.1-17.9, 20.4.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// `isOffline` is mocked via vi.mock; vi.hoisted lets the factory see the ref.
// `runTickInternal` only reads `.value`, never `watch()`s, so a plain mutable
// object suffices and avoids ESM/Vue import gymnastics in the hoist closure.
const { offlineRef } = vi.hoisted(() => ({ offlineRef: { value: false } as { value: boolean } }))
vi.mock('@/services/offlineDetector', () => ({
  isOffline: offlineRef,
  start: vi.fn(),
  stop: vi.fn(),
  runOnlineProbe: vi.fn(),
  _resetForTests: vi.fn()
}))

// Replace the heavy archive builder with a tiny stub.
vi.mock('@/services/backupArchive', () => ({
  createBackupArchive: vi.fn().mockResolvedValue({
    file: new Blob(['stub'], { type: 'application/zip' }),
    schemaVersion: 1,
    createdAtUtc: new Date().toISOString(),
    membersCount: 0,
    memberPhotosCount: 0,
    assetsCount: 0,
    sizeBytes: 4,
    checksumSha256: 'deadbeef'
  }),
  restoreBackupArchive: vi.fn()
}))

import 'fake-indexeddb/auto'
import { setActivePinia, createPinia } from 'pinia'

import { db } from '@/db/database'
import { pendingChangesRepo, listLocalAudit } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import {
  _runTickForTests,
  _resetForTests,
  kick,
  onConflict,
  _getLastKnownTagForTests
} from '@/services/syncTicker'
import type { PendingChange } from '@/types/sync'

const ORIGINAL_FETCH = globalThis.fetch

async function clearGlobalDb(): Promise<void> {
  await db.pending_changes.clear()
  await db.pending_seq_counters.clear()
  await db.local_audit.clear()
  await db.recovery_state.clear()
}

function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const b = new Uint8Array(16)
  for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

async function seedChange(userId: number): Promise<PendingChange> {
  return pendingChangesRepo.enqueue({
    changeId: uuid(),
    userId,
    createdAtUtc: new Date().toISOString(),
    editKind: 'member.create',
    targetId: 'm-1',
    payloadJson: '{}'
  })
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

async function flush(times = 40): Promise<void> {
  for (let i = 0; i < times; i++) {
    await Promise.resolve()
  }
  // fake-indexeddb completes via macrotasks; yield once to let them drain.
  await new Promise((r) => setTimeout(r, 0))
  for (let i = 0; i < times; i++) {
    await Promise.resolve()
  }
}

beforeEach(async () => {
  setActivePinia(createPinia())
  offlineRef.value = false

  await clearGlobalDb()

  // Authenticated app state.
  const app = useAppStore()
  app.authUser = {
    id: 42,
    email: 'test@example.com',
    displayName: 'Test',
    isAdmin: false,
    providers: []
  } as unknown as typeof app.authUser
  app.settings = { ...app.settings, deviceId: 'dev-1' }
})

afterEach(async () => {
  _resetForTests()
  globalThis.fetch = ORIGINAL_FETCH
  await clearGlobalDb()
  vi.clearAllMocks()
})

describe('syncTicker single-flight', () => {
  it('coalesces concurrent kicks into a single in-flight upload', async () => {
    await seedChange(42)

    let resolveUpload: ((value: Response) => void) | null = null
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/v2/backup/upload')) {
        return new Promise<Response>((resolve) => {
          resolveUpload = resolve
        })
      }
      // backupMeta() and any other GETs.
      return Promise.resolve(jsonResponse(200, { success: true, exists: false, schemaVersion: 1 }))
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const p1 = _runTickForTests()
    const p2 = _runTickForTests()
    kick()
    kick()

    // Allow the upload promise to be issued.
    await flush()

    const uploadCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/v2/backup/upload')
    )
    expect(uploadCalls.length).toBe(1)

    // Resolve the upload with 200 so the in-flight promise settles.
    resolveUpload?.(
      jsonResponse(200, {
        success: true,
        exists: true,
        schemaVersion: 1,
        serverVersionTag: 'tag-after-200'
      })
    )

    await Promise.all([p1, p2])
    await flush()
  })
})

describe('syncTicker 200 OK', () => {
  it('removes confirmed changeIds and appends local_audit rows', async () => {
    const a = await seedChange(42)
    const b = await seedChange(42)
    const ids = [a.changeId, b.changeId].sort()

    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/v2/backup/upload')) {
        return Promise.resolve(
          jsonResponse(200, {
            success: true,
            exists: true,
            schemaVersion: 1,
            serverVersionTag: 'tag-200'
          })
        )
      }
      return Promise.resolve(jsonResponse(200, { success: true, exists: false, schemaVersion: 1 }))
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await _runTickForTests()
    await flush()

    const uploadCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/v2/backup/upload')
    )
    expect(uploadCalls).toHaveLength(1)

    const remaining = await pendingChangesRepo.list(42)
    expect(remaining).toHaveLength(0)

    const audit = await listLocalAudit(db)
    const uploadedIds = audit
      .filter((r) => r.action === 'pending_change_uploaded')
      .map((r) => r.changeId)
      .sort()
    expect(uploadedIds).toEqual(ids)

    expect(_getLastKnownTagForTests()).toBe('tag-200')
  })
})

describe('syncTicker 409 Conflict', () => {
  it('does not remove records and emits a conflict event', async () => {
    const a = await seedChange(42)
    const b = await seedChange(42)

    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/v2/backup/upload')) {
        return Promise.resolve(
          jsonResponse(409, {
            success: false,
            error: 'conflict',
            serverVersionTag: 'tag-server'
          })
        )
      }
      if (url.includes('/v2/backup/meta')) {
        return Promise.resolve(
          jsonResponse(200, {
            success: true,
            exists: true,
            schemaVersion: 1,
            serverVersionTag: 'tag-server'
          })
        )
      }
      return Promise.resolve(jsonResponse(200, {}))
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const events: Array<{ userId: number; serverTag: string | null; changeIds: string[] }> = []
    onConflict((m) => events.push(m))

    await _runTickForTests()
    await flush()

    // Buffer is intact.
    const remaining = await pendingChangesRepo.list(42)
    expect(remaining.map((r) => r.changeId).sort()).toEqual(
      [a.changeId, b.changeId].sort()
    )

    // No upload audit rows.
    const audit = await listLocalAudit(db)
    expect(audit.filter((r) => r.action === 'pending_change_uploaded')).toHaveLength(0)

    // Conflict listener fired with the rejected changeIds.
    expect(events).toHaveLength(1)
    expect(events[0]!.userId).toBe(42)
    expect(events[0]!.changeIds.sort()).toEqual([a.changeId, b.changeId].sort())
  })
})

describe('syncTicker offline gating', () => {
  it('does not issue any upload while isOffline is true', async () => {
    await seedChange(42)
    offlineRef.value = true

    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await _runTickForTests()
    await flush()

    const uploadCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/v2/backup/upload')
    )
    expect(uploadCalls).toHaveLength(0)

    const remaining = await pendingChangesRepo.list(42)
    expect(remaining).toHaveLength(1)
  })
})
