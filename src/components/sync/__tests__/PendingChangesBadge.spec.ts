// Unit tests for PendingChangesBadge.vue.
//
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.6.
// Validates: Requirements 19.1, 19.3, 19.5, 19.6.
//
// We mount with the built-in Vue `createApp` (no @vue/test-utils in this
// project) and drive the badge by mutating the IndexedDB-backed
// `pending_changes` store via `pendingChangesRepo`.

import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick, type App } from 'vue'

import PendingChangesBadge from '@/components/sync/PendingChangesBadge.vue'
import { db, FamilyOneDatabase } from '@/db/database'
import { pendingChangesRepo } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import type { EditKind, PendingChange } from '@/types/sync'

const DB_NAME = 'familyone_web_db'
const USER_ID = 7

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

function makeChange(): Omit<PendingChange, 'sequenceNumber'> {
  return {
    changeId: uuid(),
    userId: USER_ID,
    createdAtUtc: new Date().toISOString(),
    editKind: 'member.create' as EditKind,
    targetId: 'm-1',
    payloadJson: '{}'
  }
}

let host: HTMLDivElement | null = null
let app: App | null = null

function mount(): HTMLElement {
  host = document.createElement('div')
  document.body.appendChild(host)
  app = createApp(PendingChangesBadge)
  app.mount(host)
  return host
}

function unmount(): void {
  if (app !== null) {
    app.unmount()
    app = null
  }
  if (host !== null && host.parentNode !== null) {
    host.parentNode.removeChild(host)
    host = null
  }
}

async function flushAsync(): Promise<void> {
  // Two macro-task ticks let the Dexie hook + the count$ ref propagate
  // through Vue's reactive scheduler.
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(async () => {
  setActivePinia(createPinia())
  if ((db as unknown as { isOpen: () => boolean }).isOpen()) db.close()
  await Dexie.delete(DB_NAME)
  await db.open()
  // Stub an authenticated user so the badge resolves a userId.
  const appStore = useAppStore()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(appStore as any).authUser = { id: USER_ID, displayName: 'tester' }
})

afterEach(async () => {
  unmount()
  db.close()
  await Dexie.delete(DB_NAME)
})

describe('PendingChangesBadge.vue', () => {
  it('shows the count and Russian label when the buffer has 2 changes', async () => {
    await pendingChangesRepo.enqueue(makeChange())
    await pendingChangesRepo.enqueue(makeChange())

    const root = mount()
    await flushAsync()

    const badge = root.querySelector('.pending-badge')
    expect(badge).not.toBeNull()

    const count = badge?.querySelector('.pending-badge-count')
    expect(count?.textContent?.trim()).toBe('2')

    const text = badge?.querySelector('.pending-badge-text')
    expect(text?.textContent?.trim()).toBe('несинхронизированных изменения')

    expect(badge?.getAttribute('aria-label')).toBe('2 несинхронизированных изменения')
  })

  it('hides the badge when the buffer empties (Req 19.3)', async () => {
    const a = await pendingChangesRepo.enqueue(makeChange())
    const b = await pendingChangesRepo.enqueue(makeChange())

    const root = mount()
    await flushAsync()
    expect(root.querySelector('.pending-badge')).not.toBeNull()

    await pendingChangesRepo.deleteByIds(USER_ID, [a.changeId, b.changeId])
    await flushAsync()

    expect(root.querySelector('.pending-badge')).toBeNull()
  })
})
