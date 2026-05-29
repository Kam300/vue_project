import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import {
  isOffline,
  start,
  stop,
  runOnlineProbe,
  _resetForTests
} from '@/services/offlineDetector'

const ORIGINAL_FETCH = globalThis.fetch

function setOnLine(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', {
    configurable: true,
    get: () => value
  })
}

function flush(): Promise<void> {
  return Promise.resolve().then(() => Promise.resolve())
}

describe('offlineDetector', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    setOnLine(true)
    _resetForTests()
  })

  afterEach(() => {
    stop()
    _resetForTests()
    vi.useRealTimers()
    globalThis.fetch = ORIGINAL_FETCH
  })

  it('flips isOffline to true within 1s of window.offline event', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    start()
    expect(isOffline.value).toBe(false)

    setOnLine(false)
    window.dispatchEvent(new Event('offline'))

    // Allow microtasks + advance under 1s.
    await flush()
    vi.advanceTimersByTime(500)
    await flush()

    expect(isOffline.value).toBe(true)
  })

  it('only clears isOffline after probe returns 2xx (window.online alone is not enough)', async () => {
    let resolveProbe: ((value: Response) => void) | null = null
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveProbe = resolve
        })
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch
    start()

    // Go offline first.
    setOnLine(false)
    window.dispatchEvent(new Event('offline'))
    await flush()
    expect(isOffline.value).toBe(true)

    // Now the OS reports online; this fires runOnlineProbe but should NOT
    // immediately clear isOffline until the probe returns 2xx.
    setOnLine(true)
    window.dispatchEvent(new Event('online'))
    await flush()
    expect(isOffline.value).toBe(true)
    expect(fetchMock).toHaveBeenCalled()

    // Resolve the probe with 200.
    resolveProbe?.(new Response(null, { status: 200 }))
    await flush()
    await flush()

    expect(isOffline.value).toBe(false)
  })

  it('keeps offline state when probe returns 5xx', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 503 }))
    start()
    expect(isOffline.value).toBe(false)

    const ok = await runOnlineProbe()
    expect(ok).toBe(false)

    await flush()
    expect(isOffline.value).toBe(true)

    // Still offline shortly after.
    vi.advanceTimersByTime(1_000)
    await flush()
    expect(isOffline.value).toBe(true)
  })
})
