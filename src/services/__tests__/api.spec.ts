// Unit tests for src/services/api.ts middleware + backupUploadWithMatch.
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.7.
// Requirements covered: 7.1, 7.2, 7.3, 7.4, 18.3.

import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FamilyOneDatabase, db } from '@/db/database'
import { useAppStore } from '@/stores/appStore'
import { pendingChangesRepo, getRecoveryState } from '@/db/pendingChanges'
import {
  SessionRevokedError,
  _setRecoveryShown,
  _isRecoveryShown,
  backupUploadWithMatch,
  backupMeta,
  authLogout,
  onSessionRevokedToast
} from '@/services/api'
import type { PendingChange } from '@/types/sync'

const ORIGINAL_FETCH = globalThis.fetch
const DB_NAME = 'familyone_web_db'

function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

function makeChange(userId: number): Omit<PendingChange, 'sequenceNumber'> {
  return {
    changeId: uuid(),
    userId,
    createdAtUtc: new Date().toISOString(),
    editKind: 'member.create',
    targetId: 'm-1',
    payloadJson: '{}'
  }
}

async function openFreshDb(): Promise<FamilyOneDatabase> {
  await Dexie.delete(DB_NAME)
  if ((db as unknown as { isOpen: () => boolean }).isOpen()) db.close()
  await db.open()
  return db
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

let database: FamilyOneDatabase

beforeEach(async () => {
  setActivePinia(createPinia())
  database = await openFreshDb()
  _setRecoveryShown(false)
  // Stub authenticated user so the middleware can resolve userId.
  const app = useAppStore()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(app as any).authUser = { id: 42, displayName: 'tester', providers: [] }
})

afterEach(async () => {
  database.close()
  await Dexie.delete(DB_NAME)
  globalThis.fetch = ORIGINAL_FETCH
  _setRecoveryShown(false)
  vi.restoreAllMocks()
})

describe('authedRequest 401 session_revoked', () => {
  it('buffer-empty 401 → clears local auth, fires toast, throws SessionRevokedError (Req 7.1, 7.2)', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(401, { error: 'session_revoked', reason: 'signed_in_on_other_device' })
      ) as unknown as typeof fetch

    const toastSpy = vi.fn()
    const unsubscribe = onSessionRevokedToast(toastSpy)

    await expect(backupMeta('tok', 'dev')).rejects.toBeInstanceOf(SessionRevokedError)

    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0].reason).toBe('signed_in_on_other_device')

    const app = useAppStore()
    expect(app.authUser).toBeNull()
    expect(_isRecoveryShown()).toBe(false)

    unsubscribe()
  })

  it('buffer-non-empty 401 → persists recovery_state, sets isRecoveryShown (Req 7.3, 18.1)', async () => {
    // Seed one pending change for user 42.
    await pendingChangesRepo.enqueue(makeChange(42))

    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(401, { error: 'session_revoked', reason: 'signed_in_on_other_device' })
      ) as unknown as typeof fetch

    await expect(backupMeta('tok', 'dev')).rejects.toBeInstanceOf(SessionRevokedError)

    const state = await getRecoveryState(42)
    expect(state).toBeDefined()
    expect(state?.userId).toBe(42)
    expect(state?.revokedReason).toBe('signed_in_on_other_device')
    expect(state?.pendingCount).toBe(1)
    expect(state?.state).toBe('Shown')
    expect(_isRecoveryShown()).toBe(true)

    // App auth is preserved (Req 18.2).
    expect(useAppStore().authUser).not.toBeNull()
  })

  it('blocks authenticated outbound calls while isRecoveryShown=true except /v2/auth/* (Req 7.4, 18.3)', async () => {
    _setRecoveryShown(true)
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { success: true }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    // Authenticated non-auth call must be blocked without hitting fetch.
    await expect(backupMeta('tok', 'dev')).rejects.toBeInstanceOf(SessionRevokedError)
    expect(fetchMock).not.toHaveBeenCalled()

    // /v2/auth/logout must still go through.
    await expect(authLogout()).resolves.toEqual({ success: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('backupUploadWithMatch', () => {
  it('builds a multipart body with backup_file + change_ids and sets the expected headers/query', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true, exists: true, schemaVersion: 2 }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'application/zip' })
    await backupUploadWithMatch({
      authToken: 'tok',
      deviceId: 'dev-1',
      zipFile: blob,
      ifMatch: 'abc',
      force: true,
      changeIds: ['c1', 'c2']
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch(/\/v2\/backup\/upload\?force=true$/)
    expect(init.method).toBe('POST')

    const headers = init.headers as Record<string, string>
    expect(headers['If-Match']).toBe('abc')
    expect(headers['X-Client-Capabilities']).toBe('if-match-v1')
    expect(headers['Authorization']).toBe('Bearer tok')
    expect(headers['X-FamilyOne-Device']).toBe('dev-1')

    const body = init.body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('change_ids')).toBe(JSON.stringify(['c1', 'c2']))
    expect(body.get('backup_file')).toBeInstanceOf(Blob)
  })

  it('omits force=true and uses ifMatch="*" without it', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true, exists: true, schemaVersion: 2 }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const blob = new Blob([new Uint8Array([1])], { type: 'application/zip' })
    await backupUploadWithMatch({
      authToken: 'tok',
      zipFile: blob,
      ifMatch: '*',
      changeIds: []
    })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).not.toMatch(/force=true/)
    expect((init.headers as Record<string, string>)['If-Match']).toBe('*')
  })
})
