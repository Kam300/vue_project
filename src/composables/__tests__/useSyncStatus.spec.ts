// Unit tests for src/composables/useSyncStatus.ts
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.6.
// Requirements covered: 19.4.

import { beforeEach, describe, expect, it } from 'vitest'

import { _recordSyncResult } from '@/services/syncTicker'
import { _resetForTests, useDetailState, useSyncStatus } from '@/composables/useSyncStatus'

beforeEach(() => {
  _resetForTests()
})

describe('useSyncStatus.lastSyncResult', () => {
  it('starts as null until a result is recorded', () => {
    const { lastSyncResult } = useSyncStatus()
    expect(lastSyncResult.value).toBeNull()
  })

  it('is populated after _recordSyncResult is called', () => {
    const { lastSyncResult } = useSyncStatus()

    const evt = { atUtc: '2026-04-03T10:00:00.000Z', httpStatus: 200, reason: 'ok' }
    _recordSyncResult(evt)

    expect(lastSyncResult.value).toEqual(evt)
  })

  it('reflects the most recent recorded result', () => {
    const { lastSyncResult } = useSyncStatus()

    _recordSyncResult({ atUtc: '2026-04-03T10:00:00.000Z', httpStatus: 200, reason: 'ok' })
    _recordSyncResult({ atUtc: '2026-04-03T10:01:00.000Z', httpStatus: 409, reason: 'conflict' })

    expect(lastSyncResult.value).toEqual({
      atUtc: '2026-04-03T10:01:00.000Z',
      httpStatus: 409,
      reason: 'conflict'
    })
  })
})

describe('useDetailState', () => {
  it('opens and closes the detail dialog', () => {
    const detail = useDetailState()
    expect(detail.isOpen.value).toBe(false)

    detail.show()
    expect(detail.isOpen.value).toBe(true)

    detail.hide()
    expect(detail.isOpen.value).toBe(false)
  })

  it('toggle flips the open flag', () => {
    const detail = useDetailState()
    detail.toggle()
    expect(detail.isOpen.value).toBe(true)
    detail.toggle()
    expect(detail.isOpen.value).toBe(false)
  })
})
