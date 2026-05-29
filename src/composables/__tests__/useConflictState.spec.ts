// Unit tests for src/composables/useConflictState.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.4.
// Requirements covered: 2.4, 2.5, 2.6, 2.7.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks for the heavy services. We mount these BEFORE importing the module
// under test so the composable picks up the stubs at import time.
// ---------------------------------------------------------------------------

const { conflictListeners } = vi.hoisted(() => ({
  conflictListeners: new Set<(m: { userId: number; serverTag: string | null; changeIds: string[] }) => void>()
}))

vi.mock('@/services/syncTicker', () => ({
  onConflict: (fn: (m: { userId: number; serverTag: string | null; changeIds: string[] }) => void) => {
    conflictListeners.add(fn)
    return () => conflictListeners.delete(fn)
  }
}))

const backupDownloadMock = vi.fn()
const backupMetaMock = vi.fn()
const backupUploadWithMatchMock = vi.fn()

vi.mock('@/services/api', () => ({
  backupDownload: (...args: unknown[]) => backupDownloadMock(...args),
  backupMeta: (...args: unknown[]) => backupMetaMock(...args),
  backupUploadWithMatch: (...args: unknown[]) => backupUploadWithMatchMock(...args)
}))

const restoreBackupArchiveMock = vi.fn()
const createBackupArchiveMock = vi.fn()

vi.mock('@/services/backupArchive', () => ({
  restoreBackupArchive: (...args: unknown[]) => restoreBackupArchiveMock(...args),
  createBackupArchive: (...args: unknown[]) => createBackupArchiveMock(...args)
}))

const deleteByIdsMock = vi.fn()

vi.mock('@/db/pendingChanges', () => ({
  pendingChangesRepo: {
    deleteByIds: (...args: unknown[]) => deleteByIdsMock(...args)
  }
}))

vi.mock('@/stores/appStore', () => ({
  useAppStore: () => ({ settings: { deviceId: 'dev-1' } })
}))

// ---------------------------------------------------------------------------

import { _resetForTests, useConflictState } from '@/composables/useConflictState'

function emitConflict(meta: { userId: number; serverTag: string | null; changeIds: string[] }): void {
  for (const fn of conflictListeners) fn(meta)
}

beforeEach(() => {
  _resetForTests()
  backupDownloadMock.mockReset()
  backupMetaMock.mockReset()
  backupUploadWithMatchMock.mockReset()
  restoreBackupArchiveMock.mockReset()
  createBackupArchiveMock.mockReset()
  deleteByIdsMock.mockReset()

  backupMetaMock.mockResolvedValue({
    success: true,
    exists: true,
    schemaVersion: 1,
    serverVersionTag: 'tag-after-meta'
  })
  createBackupArchiveMock.mockResolvedValue({
    file: new Blob(['x'], { type: 'application/zip' }),
    schemaVersion: 1,
    createdAtUtc: new Date().toISOString(),
    membersCount: 0,
    memberPhotosCount: 0,
    assetsCount: 0,
    sizeBytes: 1,
    checksumSha256: 'deadbeef'
  })
  restoreBackupArchiveMock.mockResolvedValue({
    membersInserted: 0,
    membersMatched: 0,
    photosAdded: 0,
    photosSkippedDuplicates: 0,
    errors: 0
  })
})

afterEach(() => {
  conflictListeners.clear()
})

describe('useConflictState — onConflict subscription', () => {
  it('opens the dialog and populates meta on each conflict event', () => {
    const state = useConflictState()
    expect(state.isOpen.value).toBe(false)
    expect(state.meta.value).toBeNull()

    emitConflict({ userId: 42, serverTag: 'tag-server', changeIds: ['c-1', 'c-2'] })

    expect(state.isOpen.value).toBe(true)
    expect(state.meta.value).toEqual({
      userId: 42,
      serverTag: 'tag-server',
      changeIds: ['c-1', 'c-2']
    })
  })
})

describe('useConflictState.cancel', () => {
  it('hides the dialog without touching the buffer or upload endpoint', async () => {
    const state = useConflictState()
    emitConflict({ userId: 42, serverTag: 'tag-server', changeIds: ['c-1'] })
    expect(state.isOpen.value).toBe(true)

    state.cancel()

    expect(state.isOpen.value).toBe(false)
    expect(state.meta.value).toBeNull()
    expect(backupUploadWithMatchMock).not.toHaveBeenCalled()
    expect(deleteByIdsMock).not.toHaveBeenCalled()
    expect(backupDownloadMock).not.toHaveBeenCalled()
  })
})

describe('useConflictState.overwriteAnyway', () => {
  it('issues a force=true upload and clears confirmed changeIds', async () => {
    backupUploadWithMatchMock.mockResolvedValue({
      success: true,
      exists: true,
      schemaVersion: 1,
      serverVersionTag: 'tag-after-force'
    })
    deleteByIdsMock.mockResolvedValue(2)

    const state = useConflictState()
    emitConflict({ userId: 42, serverTag: 'tag-server', changeIds: ['c-1', 'c-2'] })

    await state.overwriteAnyway()

    expect(backupUploadWithMatchMock).toHaveBeenCalledTimes(1)
    const arg = backupUploadWithMatchMock.mock.calls[0]![0] as {
      ifMatch: string
      force: boolean
      changeIds: string[]
    }
    expect(arg.force).toBe(true)
    expect(arg.ifMatch).toBe('tag-server')
    expect(arg.changeIds).toEqual(['c-1', 'c-2'])

    expect(deleteByIdsMock).toHaveBeenCalledWith(42, ['c-1', 'c-2'])
    expect(state.lastServerTag.value).toBe('tag-after-force')
    expect(state.isOpen.value).toBe(false)
  })

  it('falls back to If-Match: * when no server tag is known', async () => {
    backupUploadWithMatchMock.mockResolvedValue({
      success: true,
      exists: true,
      schemaVersion: 1,
      serverVersionTag: 'tag-after-force'
    })
    deleteByIdsMock.mockResolvedValue(0)

    const state = useConflictState()
    emitConflict({ userId: 42, serverTag: null, changeIds: [] })

    await state.overwriteAnyway()

    const arg = backupUploadWithMatchMock.mock.calls[0]![0] as { ifMatch: string; force: boolean }
    expect(arg.ifMatch).toBe('*')
    expect(arg.force).toBe(true)
    expect(deleteByIdsMock).not.toHaveBeenCalled()
    expect(state.isOpen.value).toBe(false)
  })
})

describe('useConflictState.downloadServer', () => {
  it('issues GET /v2/backup/download, restores the archive, refreshes tag, and closes', async () => {
    const blob = new Blob(['srv'], { type: 'application/zip' })
    backupDownloadMock.mockResolvedValue(blob)

    const state = useConflictState()
    emitConflict({ userId: 42, serverTag: 'tag-server', changeIds: ['c-1'] })

    await state.downloadServer()

    expect(backupDownloadMock).toHaveBeenCalledTimes(1)
    expect(restoreBackupArchiveMock).toHaveBeenCalledWith(blob)
    expect(backupMetaMock).toHaveBeenCalledTimes(1)
    expect(state.lastServerTag.value).toBe('tag-after-meta')
    expect(state.isOpen.value).toBe(false)
    expect(backupUploadWithMatchMock).not.toHaveBeenCalled()
    expect(deleteByIdsMock).not.toHaveBeenCalled()
  })
})
