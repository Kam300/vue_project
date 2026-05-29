// Unit tests for OfflineBanner.vue.
//
// Validates: Requirements 12.1, 12.2, 12.3, 12.4.
//
// We mount with the built-in Vue `createApp` instead of @vue/test-utils
// (not installed in this project) and drive the offline state by mutating
// the shared `isOffline` ref exported by `@/services/offlineDetector`.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import OfflineBanner from '@/components/shared/OfflineBanner.vue'
import { isOffline, _resetForTests } from '@/services/offlineDetector'

const BANNER_TEXT =
  'Вы офлайн. Изменения не синхронизируются с сервером и могут быть перезаписаны другим устройством'

let host: HTMLDivElement | null = null
let app: App | null = null

function mount(): HTMLElement {
  host = document.createElement('div')
  document.body.appendChild(host)
  app = createApp(OfflineBanner)
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

describe('OfflineBanner.vue', () => {
  beforeEach(() => {
    _resetForTests()
    delete document.body.dataset.offline
  })

  afterEach(() => {
    unmount()
    _resetForTests()
    delete document.body.dataset.offline
  })

  it('renders nothing when offline=false', async () => {
    isOffline.value = false
    const root = mount()
    await nextTick()
    expect(root.querySelector('.offline-banner')).toBeNull()
    expect(root.textContent ?? '').not.toContain(BANNER_TEXT)
  })

  it('renders banner text when offline=true', async () => {
    isOffline.value = true
    const root = mount()
    await nextTick()
    const banner = root.querySelector('.offline-banner')
    expect(banner).not.toBeNull()
    expect(banner?.textContent?.trim()).toBe(BANNER_TEXT)
  })

  it("sets document.body.dataset.offline === 'true' while offline=true", async () => {
    isOffline.value = true
    mount()
    await nextTick()
    expect(document.body.dataset.offline).toBe('true')
  })

  it('removes the dataset within 1s when offline becomes false', async () => {
    isOffline.value = true
    mount()
    await nextTick()
    expect(document.body.dataset.offline).toBe('true')

    isOffline.value = false
    // Allow the post-flush watcher + Vue render cycle to run; both occur in
    // the same microtask queue, well under the 1 s budget.
    await nextTick()
    await nextTick()
    expect(document.body.dataset.offline).toBeUndefined()
  })
})
