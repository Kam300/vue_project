// Auto_Sync_Tick service for the Web client.
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.3.
// Requirements: 13.1, 13.2, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 20.4.
//
// Public API:
//   - start() / stop()         install/remove triggers and load initial tag.
//   - kick()                   manual trigger (debounced through single-flight).
//   - _runTickForTests()       async helper that bypasses real timers.
//   - onConflict(fn)           subscribe to 409 events for ConflictDialog.

import { ref, watch, type Ref, type WatchStopHandle } from 'vue'
import { appendLocalAudit, pendingChangesRepo } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import { isOffline } from '@/services/offlineDetector'
import { backupMeta, backupUploadWithMatch, SessionRevokedError } from '@/services/api'
import { createBackupArchive } from '@/services/backupArchive'
import { SYNC_TICK_EVENT } from '@/stores/withPendingChange'
import type { BackupMetaResponse } from '@/types/api'

const EDIT_DEBOUNCE_MS = 5_000
const PERIODIC_MS = 30_000
const BACKOFF_INITIAL_MS = 1_000
const BACKOFF_CEILING_MS = 5 * 60_000
const TAG_REFRESH_DELAY_MS = 1_000

export interface ConflictMeta {
  userId: number
  /** Server's current `serverVersionTag` if it could be refreshed, otherwise null. */
  serverTag: string | null
  /** Pending `changeId`s that were attempted in the rejected upload. */
  changeIds: string[]
}

type ConflictListener = (meta: ConflictMeta) => void

const conflictListeners = new Set<ConflictListener>()

/**
 * Result of the most recent `Auto_Sync_Tick` (Req 19.4 / design §4.6).
 * `httpStatus = 0` means a network/transport failure with no server response.
 */
export interface SyncResult {
  /** ISO 8601 UTC timestamp of the outcome. */
  atUtc: string
  /** HTTP status (200 / 409 / 428 / 5xx) or 0 for network errors. */
  httpStatus: number
  /** Short human-readable reason ("ok", "conflict", "precondition_required", ...). */
  reason: string
}

type SyncResultListener = (result: SyncResult) => void

const syncResultListeners = new Set<SyncResultListener>()

/** Subscribe to per-tick outcome events. Returns an unsubscribe handle. */
export function onSyncResult(fn: SyncResultListener): () => void {
  syncResultListeners.add(fn)
  return () => {
    syncResultListeners.delete(fn)
  }
}

/**
 * Fan-out a tick result to listeners. Exported so `useSyncStatus` (and tests)
 * can record outcomes when running outside of the real ticker loop.
 */
export function _recordSyncResult(result: SyncResult): void {
  for (const fn of syncResultListeners) {
    try {
      fn(result)
    } catch {
      // ignore listener failures
    }
  }
}

function emitSyncResult(httpStatus: number, reason: string): void {
  _recordSyncResult({
    atUtc: new Date().toISOString(),
    httpStatus,
    reason
  })
}

/**
 * Subscribe to `409 Conflict` events. ConflictDialog wires this in task 7.1.
 * Returns an unsubscribe function.
 */
export function onConflict(fn: ConflictListener): () => void {
  conflictListeners.add(fn)
  return () => {
    conflictListeners.delete(fn)
  }
}

function emitConflict(meta: ConflictMeta): void {
  for (const fn of conflictListeners) {
    try {
      fn(meta)
    } catch {
      // ignore listener failures
    }
  }
}

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

let started = false
let editDebounceTimer: ReturnType<typeof setTimeout> | null = null
let periodicTimer: ReturnType<typeof setInterval> | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let editTickHandler: (() => void) | null = null
let unwatchOffline: WatchStopHandle | null = null
let unwatchUser: WatchStopHandle | null = null

let inFlight: Promise<void> | null = null
let lastKnownTag = '*'
let backoffMs = BACKOFF_INITIAL_MS
let stoppedDueToRevoke = false

// Test hook so specs can inspect the in-memory tag without exporting it.
const _lastKnownTagRef: Ref<string> = ref('*')

function setLastKnownTag(tag: string): void {
  lastKnownTag = tag
  _lastKnownTagRef.value = tag
}

export function _getLastKnownTagForTests(): string {
  return lastKnownTag
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function activeUserId(): number | null {
  try {
    const id = useAppStore().authUser?.id
    return typeof id === 'number' && id > 0 ? id : null
  } catch {
    return null
  }
}

function activeDeviceId(): string {
  try {
    return String(useAppStore().settings?.deviceId || '')
  } catch {
    return ''
  }
}

async function shouldSkip(userId: number | null): Promise<boolean> {
  // Req 17.7: a session_revoked observation halts the loop until recovery completes.
  if (stoppedDueToRevoke) return true
  // Req 13.1, 17.8: never sync while offline.
  if (isOffline.value) return true
  // Req 17.1: requires an authenticated session.
  if (userId === null) return true
  // Req 17.1: skip when the buffer is empty.
  if (await pendingChangesRepo.isEmpty(userId)) return true
  return false
}

function clearEditDebounce(): void {
  if (editDebounceTimer !== null) {
    clearTimeout(editDebounceTimer)
    editDebounceTimer = null
  }
}

function clearRetryTimer(): void {
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
}

function scheduleRetry(ms: number): void {
  clearRetryTimer()
  retryTimer = setTimeout(() => {
    retryTimer = null
    kick()
  }, ms)
}

function scheduleBackoff(): void {
  // Req 17.6: exponential back-off, capped at 5 min.
  const delay = backoffMs
  backoffMs = Math.min(backoffMs * 2, BACKOFF_CEILING_MS)
  scheduleRetry(delay)
}

function isErrorWithMessage(err: unknown, re: RegExp): boolean {
  return err instanceof Error && re.test(err.message)
}

// ---------------------------------------------------------------------------
// Tick body
// ---------------------------------------------------------------------------

async function runTickInternal(): Promise<void> {
  const userId = activeUserId()
  if (await shouldSkip(userId)) return
  const uid = userId as number

  // Snapshot the buffer so the changeIds we send match the records we'll
  // remove on a 200 OK response (Req 17.3, 16.6).
  const pending = await pendingChangesRepo.list(uid)
  if (pending.length === 0) return
  const changeIds = pending.map((p) => p.changeId)

  let archive: Blob
  try {
    const built = await createBackupArchive()
    archive = built.file
  } catch {
    // Archive build failure leaves the buffer intact (Req 17.6 spirit).
    scheduleBackoff()
    return
  }

  let response: BackupMetaResponse
  try {
    response = await backupUploadWithMatch({
      authToken: '',
      deviceId: activeDeviceId(),
      zipFile: archive,
      ifMatch: lastKnownTag,
      force: false,
      changeIds
    })
  } catch (err) {
    // Req 17.7: api.ts middleware already handled session_revoked recovery.
    if (err instanceof SessionRevokedError) {
      stoppedDueToRevoke = true
      emitSyncResult(401, 'session_revoked')
      return
    }

    // Req 17.4: 409 Conflict — keep buffer, surface to ConflictDialog.
    if (isErrorWithMessage(err, /^conflict\b/i)) {
      let serverTag: string | null = null
      try {
        const meta = await backupMeta('', activeDeviceId())
        serverTag = meta.serverVersionTag || null
        if (serverTag) setLastKnownTag(serverTag)
      } catch {
        // best-effort; the dialog can re-fetch.
      }
      emitConflict({ userId: uid, serverTag, changeIds })
      // Reset back-off on a clean 409 (no retry storm).
      backoffMs = BACKOFF_INITIAL_MS
      emitSyncResult(409, 'conflict')
      return
    }

    // Req 17.5: 428 Precondition Required — refresh tag, reschedule in 1s.
    if (isErrorWithMessage(err, /^precondition_required\b/i)) {
      try {
        const meta = await backupMeta('', activeDeviceId())
        if (meta.serverVersionTag) setLastKnownTag(meta.serverVersionTag)
      } catch {
        // ignore; next tick will retry.
      }
      backoffMs = BACKOFF_INITIAL_MS
      scheduleRetry(TAG_REFRESH_DELAY_MS)
      emitSyncResult(428, 'precondition_required')
      return
    }

    // Req 17.6: 5xx / network / timeout — exponential back-off, buffer intact.
    scheduleBackoff()
    const message = err instanceof Error ? err.message : String(err)
    const status = /\b5\d{2}\b/.exec(message)
    emitSyncResult(status ? Number(status[0]) : 0, message || 'network_error')
    return
  }

  // 200 OK (Req 17.3, 16.6, 20.4).
  if (response.serverVersionTag) {
    setLastKnownTag(response.serverVersionTag)
  }
  // Atomic removal of confirmed changeIds.
  await pendingChangesRepo.deleteByIds(uid, changeIds)
  // Local audit row per removed change.
  for (const id of changeIds) {
    try {
      await appendLocalAudit('pending_change_uploaded', id)
    } catch {
      // best-effort; the buffer removal is the source of truth.
    }
  }
  // Reset back-off on success.
  backoffMs = BACKOFF_INITIAL_MS
  emitSyncResult(200, 'ok')
}

// ---------------------------------------------------------------------------
// Public triggers
// ---------------------------------------------------------------------------

/**
 * Run a tick immediately (test helper). Honours the single-flight guarantee
 * (Req 17.9): two concurrent calls share the same in-flight Promise.
 */
export async function _runTickForTests(): Promise<void> {
  if (inFlight) return inFlight
  const promise = runTickInternal().finally(() => {
    inFlight = null
  })
  inFlight = promise
  return promise
}

/**
 * Edge-trigger an Auto_Sync_Tick. Coalesced with any in-flight tick (Req 17.9).
 */
export function kick(): void {
  if (inFlight) return
  void _runTickForTests()
}

function onEditTick(): void {
  // Req 17.1(a): debounce 5s, restart timer on every event.
  clearEditDebounce()
  editDebounceTimer = setTimeout(() => {
    editDebounceTimer = null
    kick()
  }, EDIT_DEBOUNCE_MS)
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function start(): Promise<void> {
  if (started) return
  started = true
  stoppedDueToRevoke = false
  backoffMs = BACKOFF_INITIAL_MS

  // Initial tag load (best-effort).
  try {
    const meta = await backupMeta('', activeDeviceId())
    if (meta.serverVersionTag) setLastKnownTag(meta.serverVersionTag)
  } catch {
    // No connectivity / no session — keep '*' and wait for an upload to learn the tag.
  }

  // Trigger (a): edit-debounced 5s via window event from withPendingChange.
  if (typeof window !== 'undefined') {
    editTickHandler = onEditTick
    window.addEventListener(SYNC_TICK_EVENT, editTickHandler)
  }

  // Trigger (b): periodic 30s while authenticated.
  periodicTimer = setInterval(() => {
    kick()
  }, PERIODIC_MS)

  // Trigger (c): edge offline -> online.
  unwatchOffline = watch(isOffline, (now, prev) => {
    if (prev === true && now === false) kick()
  })

  // Trigger (d): edge login complete (null -> non-null user id).
  try {
    const app = useAppStore()
    unwatchUser = watch(
      () => app.authUser?.id ?? null,
      (now, prev) => {
        const wasOut = prev === null || prev === undefined
        const isIn = typeof now === 'number' && now > 0
        if (wasOut && isIn) {
          // A fresh login also clears any prior session-revoked latch.
          stoppedDueToRevoke = false
          kick()
        }
      }
    )
  } catch {
    // Pinia not active (test harness); login-edge trigger unavailable.
  }
}

export function stop(): void {
  if (!started) return
  started = false

  if (editTickHandler !== null && typeof window !== 'undefined') {
    window.removeEventListener(SYNC_TICK_EVENT, editTickHandler)
  }
  editTickHandler = null

  clearEditDebounce()
  clearRetryTimer()
  if (periodicTimer !== null) {
    clearInterval(periodicTimer)
    periodicTimer = null
  }
  if (unwatchOffline) {
    unwatchOffline()
    unwatchOffline = null
  }
  if (unwatchUser) {
    unwatchUser()
    unwatchUser = null
  }
  inFlight = null
  stoppedDueToRevoke = false
}

// ---------------------------------------------------------------------------
// Test-only helpers
// ---------------------------------------------------------------------------

export function _resetForTests(): void {
  stop()
  setLastKnownTag('*')
  backoffMs = BACKOFF_INITIAL_MS
  conflictListeners.clear()
  syncResultListeners.clear()
  inFlight = null
  stoppedDueToRevoke = false
}
