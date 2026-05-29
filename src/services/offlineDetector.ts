// Offline detector for the Web client.
//
// Design refs: §4.5 Offline detector. Implements the state formula
//   isOffline = (!navigator.onLine) || lastProbeFailedWithin30s
//
// Public API:
//   - isOffline: Ref<boolean>           Source of truth for templates.
//   - start() / stop()                  Install/remove window listeners + periodic probe.
//   - runOnlineProbe()                  Single probe of GET /v2/presence/ping (8s timeout).
//
// Requirements: 10.1, 10.2, 10.3, 10.4, 12.2, 13.3.

import { ref, type Ref } from 'vue'
import { getApiBaseUrl } from '@/services/api'
import { useAppStore } from '@/stores/appStore'

const PROBE_TIMEOUT_MS = 8_000
const PROBE_INTERVAL_MS = 30_000
const PROBE_WINDOW_MS = 30_000

const osOnline = ref<boolean>(initialOsOnline())
const lastProbeAt = ref<number>(0)
const lastProbeOk = ref<boolean>(true)

export const isOffline: Ref<boolean> = ref<boolean>(false)

let onlineHandler: ((event: Event) => void) | null = null
let offlineHandler: ((event: Event) => void) | null = null
let intervalHandle: ReturnType<typeof setInterval> | null = null
let probeWindowTimer: ReturnType<typeof setTimeout> | null = null

function initialOsOnline(): boolean {
  return typeof navigator !== 'undefined' ? navigator.onLine !== false : true
}

function lastProbeFailedWithin30s(now: number = Date.now()): boolean {
  if (lastProbeOk.value) return false
  if (lastProbeAt.value <= 0) return false
  return now - lastProbeAt.value < PROBE_WINDOW_MS
}

function recompute(): void {
  isOffline.value = !osOnline.value || lastProbeFailedWithin30s()
}

function scheduleProbeWindowExpiry(): void {
  if (probeWindowTimer !== null) {
    clearTimeout(probeWindowTimer)
    probeWindowTimer = null
  }
  if (lastProbeOk.value) return
  probeWindowTimer = setTimeout(() => {
    probeWindowTimer = null
    recompute()
  }, PROBE_WINDOW_MS)
}

export async function runOnlineProbe(): Promise<boolean> {
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timeoutId =
    controller !== null
      ? setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
      : null

  let ok = false
  try {
    const response = await fetch(`${getApiBaseUrl()}/v2/presence/ping`, {
      method: 'GET',
      credentials: 'same-origin',
      signal: controller ? controller.signal : undefined
    })
    ok = response.status >= 200 && response.status < 300
  } catch {
    ok = false
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId)
  }

  lastProbeAt.value = Date.now()
  lastProbeOk.value = ok
  scheduleProbeWindowExpiry()
  recompute()
  return ok
}

function handleOffline(): void {
  osOnline.value = false
  // Latch a failed probe so a subsequent `online` event alone cannot flip
  // isOffline back to false before runOnlineProbe() returns 2xx.
  lastProbeAt.value = Date.now()
  lastProbeOk.value = false
  scheduleProbeWindowExpiry()
  recompute()
}

function handleOnline(): void {
  osOnline.value = true
  recompute()
  // Only a 2xx probe may clear isOffline; the latch set in handleOffline()
  // (or any recent probe failure) keeps it true until runOnlineProbe resolves.
  void runOnlineProbe()
}

function isAuthenticated(): boolean {
  // Pinia must be active when this is invoked (called from setInterval after start()).
  // In tests where Pinia is not installed, we fall through to false.
  try {
    const store = useAppStore()
    return Boolean(store.authUser)
  } catch {
    return false
  }
}

export function start(): void {
  if (typeof window === 'undefined') return
  if (onlineHandler !== null || offlineHandler !== null || intervalHandle !== null) return

  osOnline.value = initialOsOnline()
  lastProbeAt.value = 0
  lastProbeOk.value = true
  if (probeWindowTimer !== null) {
    clearTimeout(probeWindowTimer)
    probeWindowTimer = null
  }
  recompute()

  onlineHandler = handleOnline
  offlineHandler = handleOffline
  window.addEventListener('online', onlineHandler)
  window.addEventListener('offline', offlineHandler)

  intervalHandle = setInterval(() => {
    if (!isAuthenticated()) return
    void runOnlineProbe()
  }, PROBE_INTERVAL_MS)
}

export function stop(): void {
  if (typeof window !== 'undefined') {
    if (onlineHandler !== null) window.removeEventListener('online', onlineHandler)
    if (offlineHandler !== null) window.removeEventListener('offline', offlineHandler)
  }
  onlineHandler = null
  offlineHandler = null

  if (intervalHandle !== null) {
    clearInterval(intervalHandle)
    intervalHandle = null
  }
  if (probeWindowTimer !== null) {
    clearTimeout(probeWindowTimer)
    probeWindowTimer = null
  }
}

// Test-only helper. Resets module-level state and detaches listeners/timers.
export function _resetForTests(): void {
  stop()
  osOnline.value = initialOsOnline()
  lastProbeAt.value = 0
  lastProbeOk.value = true
  isOffline.value = false
}
