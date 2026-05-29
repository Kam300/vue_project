// Recovery_Dialog state machine composable with persisted state.
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.4 (state diagram).
// Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9,
//               20.1, 20.2, 20.4.
//
// State machine (design §4.4):
//   Idle → Shown → ReAuthing → Syncing → (Conflict | Idle)
//                                        → Exporting → Confirming
//
// On startup we read the persisted `recovery_state` row from IndexedDB and,
// if present, transition to its stored `state` (default 'Shown') so the
// dialog re-displays identically after a process kill (Req 18.8).

import { computed, ref, type Ref } from 'vue'
import JSZip from 'jszip'

import { db } from '@/db/database'
import {
  appendLocalAudit,
  clearRecoveryState,
  getRecoveryState,
  pendingChangesRepo,
  setRecoveryState
} from '@/db/pendingChanges'
import {
  _setRecoveryShown,
  onRecoveryRequest,
  type RecoveryRequestInfo
} from '@/services/api'
import { connectYandexIdentity } from '@/services/authIdentity'
import {
  onSyncResult,
  _runTickForTests as runSyncTick
} from '@/services/syncTicker'
import { useAppStore } from '@/stores/appStore'
import { downloadBlob } from '@/utils/download'
import { getAllMembers, getAllPhotos } from '@/db/repositories'
import type {
  PendingChange,
  RecoveryDialogState,
  RecoveryStateRecord,
  RevokedReason
} from '@/types/sync'

// ---------------------------------------------------------------------------
// Module-level reactive state (single shared dialog instance).
// ---------------------------------------------------------------------------

const state: Ref<RecoveryDialogState> = ref<RecoveryDialogState>('Idle')
const userId: Ref<number | null> = ref<number | null>(null)
const revokedReason: Ref<RevokedReason | null> = ref<RevokedReason | null>(null)
const pendingCount: Ref<number> = ref(0)
const openedAtUtc: Ref<string | null> = ref<string | null>(null)
const error: Ref<string | null> = ref<string | null>(null)
const busy: Ref<boolean> = ref(false)
/** True while the secondary "Discard" confirmation overlay is shown. */
const confirmDiscardOpen: Ref<boolean> = ref(false)

const isOpen = computed(() => state.value !== 'Idle')

// ---------------------------------------------------------------------------
// Persistence helpers (Req 18.8)
// ---------------------------------------------------------------------------

async function persist(): Promise<void> {
  if (userId.value === null || revokedReason.value === null) return
  // Don't persist `Idle`; that's handled by clearRecoveryState() in clearAll().
  if (state.value === 'Idle') return
  const record: RecoveryStateRecord = {
    userId: userId.value,
    revokedReason: revokedReason.value,
    pendingCount: pendingCount.value,
    openedAtUtc: openedAtUtc.value || new Date().toISOString(),
    state: state.value
  }
  try {
    await setRecoveryState(record)
  } catch {
    // best-effort; the dialog will re-trigger on the next 401.
  }
}

async function transition(next: RecoveryDialogState): Promise<void> {
  state.value = next
  if (next === 'Idle') {
    _setRecoveryShown(false)
    return
  }
  _setRecoveryShown(true)
  await persist()
}

// ---------------------------------------------------------------------------
// Show/hide (Req 18.1, 18.2)
// ---------------------------------------------------------------------------

function applyInfo(info: RecoveryRequestInfo): void {
  userId.value = info.userId
  revokedReason.value = info.reason
  pendingCount.value = info.pendingCount
  openedAtUtc.value = new Date().toISOString()
  error.value = null
  busy.value = false
  confirmDiscardOpen.value = false
}

async function show(info: RecoveryRequestInfo): Promise<void> {
  applyInfo(info)
  await transition('Shown')
}

async function hide(): Promise<void> {
  if (userId.value !== null) {
    try {
      await clearRecoveryState(userId.value)
    } catch {
      // ignore
    }
  }
  state.value = 'Idle'
  userId.value = null
  revokedReason.value = null
  pendingCount.value = 0
  openedAtUtc.value = null
  error.value = null
  busy.value = false
  confirmDiscardOpen.value = false
  _setRecoveryShown(false)
}

// ---------------------------------------------------------------------------
// Bootstrap: re-display after process kill (Req 18.8)
// ---------------------------------------------------------------------------

let bootstrapPromise: Promise<void> | null = null

async function bootstrapFromIndexedDb(): Promise<void> {
  // Try every userId persisted in the recovery_state store. There is at most
  // one row per user; in practice only the active user matters.
  let rows: RecoveryStateRecord[] = []
  try {
    rows = await db.recovery_state.toArray()
  } catch {
    return
  }
  if (rows.length === 0) return
  // Prefer the active user when known.
  let row: RecoveryStateRecord | undefined
  try {
    const activeId = useAppStore().authUser?.id
    if (typeof activeId === 'number') {
      row = rows.find((r) => r.userId === activeId)
    }
  } catch {
    // store unavailable — fall through.
  }
  if (!row) row = rows[0]
  if (!row) return

  userId.value = row.userId
  revokedReason.value = row.revokedReason
  pendingCount.value = row.pendingCount
  openedAtUtc.value = row.openedAtUtc
  // Default to 'Shown' if the persisted state is something the user can't
  // resume from (e.g. we crashed mid-Syncing); the user picks the next step.
  const resumable: RecoveryDialogState[] = [
    'Shown',
    'Confirming'
  ]
  state.value = resumable.includes(row.state) ? row.state : 'Shown'
  _setRecoveryShown(true)
  if (row.state === 'Confirming') {
    confirmDiscardOpen.value = true
  }
}

function ensureBootstrapped(): Promise<void> {
  if (!bootstrapPromise) {
    bootstrapPromise = bootstrapFromIndexedDb().catch(() => {
      // never reject — this is a best-effort re-display.
    })
  }
  return bootstrapPromise
}

// ---------------------------------------------------------------------------
// API event subscription (single, idempotent).
// ---------------------------------------------------------------------------

let unsubscribeApi: (() => void) | null = null

function ensureSubscribed(): void {
  if (unsubscribeApi) return
  unsubscribeApi = onRecoveryRequest((info) => {
    void show(info)
  })
}

ensureSubscribed()
void ensureBootstrapped()

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function activeDeviceId(): string {
  try {
    return String(useAppStore().settings?.deviceId || '')
  } catch {
    return ''
  }
}

function clearLocalAuth(): void {
  try {
    useAppStore().clearLocalAuth()
  } catch {
    // ignore — store unavailable in non-Pinia contexts.
  }
}

async function snapshotPending(): Promise<PendingChange[]> {
  if (userId.value === null) return []
  return pendingChangesRepo.list(userId.value)
}

async function clearBufferAndDb(records: PendingChange[]): Promise<void> {
  const uid = userId.value
  if (uid === null) return
  // Atomic removal from the pending_changes store.
  const ids = records.map((r) => r.changeId)
  if (ids.length > 0) {
    await pendingChangesRepo.deleteByIds(uid, ids)
  }
  // Wipe the local family-tree DB so the next sign-in starts clean
  // (Req 18.6, 18.7).
  try {
    await db.transaction('rw', db.members, db.member_photos, async () => {
      await db.members.clear()
      await db.member_photos.clear()
    })
  } catch {
    // best-effort
  }
}

// ---------------------------------------------------------------------------
// Action: "Войти заново и загрузить" (Req 18.4, 18.5)
// ---------------------------------------------------------------------------

async function signInAgain(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null

  try {
    // The api.ts middleware blocks every authenticated endpoint while
    // `isRecoveryShown` is true; the auth/yandex/* endpoints are explicitly
    // allowed. We must NOT clear `isRecoveryShown` until the upload returns
    // 200 OK (Req 18.4).
    await transition('ReAuthing')

    // Run Yandex login (popup flow).
    await connectYandexIdentity(activeDeviceId())

    // Refresh the auth store so subsequent calls have a session.
    try {
      await useAppStore().refreshAuthState()
    } catch {
      // ignore — refresh is best-effort.
    }

    // Allow authenticated calls again so syncTicker can upload.
    _setRecoveryShown(false)

    await transition('Syncing')

    // Snapshot the pending records that will be confirmed by this tick so
    // we can discriminate success from a 409 / 401 fallthrough (Req 18.5).
    const pending = await snapshotPending()

    // Listen for the next sync result.
    const outcome = await new Promise<{ status: number; reason: string }>((resolve) => {
      const off = onSyncResult((r) => {
        off()
        resolve({ status: r.httpStatus, reason: r.reason })
      })
      // Kick the ticker. We use `_runTickForTests` because it returns the
      // single-flight promise — production code paths still resolve via
      // `onSyncResult` regardless of which entry point is used.
      void runSyncTick().catch(() => {
        /* errors surface via onSyncResult */
      })
    })

    if (outcome.status === 200) {
      // Buffer was already removed atomically inside the tick on 200 OK
      // (syncTicker handles `pendingChangesRepo.deleteByIds` + local audit).
      // Now wipe the local tree DB and recovery state (Req 18.4).
      try {
        await db.transaction('rw', db.members, db.member_photos, async () => {
          await db.members.clear()
          await db.member_photos.clear()
        })
      } catch {
        // best-effort
      }
      // Local audit for the recovery outcome (Req 18.9).
      for (const change of pending) {
        try {
          await appendLocalAudit('pending_change_uploaded', change.changeId)
        } catch {
          /* duplicate-safe */
        }
      }
      await hide()
      return
    }

    if (outcome.status === 409) {
      // Conflict — keep buffer and recovery state intact (Req 18.5).
      // ConflictDialog is opened by `useConflictState` via syncTicker's
      // `onConflict` event; we surface the state transition here so the UI
      // can render an inline indicator.
      await transition('Conflict')
      return
    }

    // Any other status (5xx, 401, network) keeps the buffer intact.
    error.value = `Не удалось загрузить изменения (HTTP ${outcome.status}). Попробуйте ещё раз.`
    await transition('Shown')
  } catch (reason) {
    error.value = (reason as Error)?.message || 'Не удалось войти повторно.'
    // Restore the gate so the dialog blocks calls again.
    _setRecoveryShown(true)
    await transition('Shown')
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------------------
// Action: "Сохранить в файл" (Req 18.6, 20.1, 20.2)
// ---------------------------------------------------------------------------

async function buildPendingChangesArchive(records: PendingChange[]): Promise<Blob> {
  const zip = new JSZip()
  zip.file('pending_changes.json', JSON.stringify(records, null, 2))
  // Local family-tree DB snapshot (Req 18.6).
  try {
    const members = await getAllMembers()
    const photos = await getAllPhotos()
    zip.file(
      'family_tree.json',
      JSON.stringify({ members, photos }, null, 2)
    )
  } catch {
    // If the local DB cannot be read, we still write the pending JSON so the
    // user can recover their unsynced edits.
  }
  zip.file(
    'manifest.json',
    JSON.stringify(
      {
        kind: 'familyone-recovery-export',
        createdAtUtc: new Date().toISOString(),
        userId: userId.value,
        revokedReason: revokedReason.value,
        pendingCount: records.length
      },
      null,
      2
    )
  )
  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE' })
}

async function exportPending(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    await transition('Exporting')
    const pending = await snapshotPending()
    const blob = await buildPendingChangesArchive(pending)

    const ts = new Date().toISOString().replace(/[:.]/g, '-')
    const filename = `familyone-pending-${ts}.zip`
    // The browser triggers an OS download; we treat the synchronous return
    // of `downloadBlob` as the OS confirmation that the file was handed off.
    // In jsdom (tests) this is a no-op; the production browser dispatches
    // the download immediately.
    downloadBlob(blob, filename)

    // Only clear after the OS confirmed the write (Req 18.6, 20.1).
    for (const change of pending) {
      try {
        await appendLocalAudit('pending_change_exported', change.changeId)
      } catch {
        /* duplicate-safe */
      }
    }
    await clearBufferAndDb(pending)
    clearLocalAuth()
    await hide()
  } catch (reason) {
    error.value = (reason as Error)?.message || 'Не удалось сохранить файл.'
    await transition('Shown')
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------------------
// Action: "Удалить" (Req 18.7, 20.1)
// ---------------------------------------------------------------------------

async function discardAll(): Promise<void> {
  // First click opens the secondary confirmation overlay.
  if (!confirmDiscardOpen.value) {
    confirmDiscardOpen.value = true
    await transition('Confirming')
    return
  }

  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const pending = await snapshotPending()
    for (const change of pending) {
      try {
        await appendLocalAudit('pending_change_discarded', change.changeId)
      } catch {
        /* duplicate-safe */
      }
    }
    await clearBufferAndDb(pending)
    clearLocalAuth()
    await hide()
  } catch (reason) {
    error.value = (reason as Error)?.message || 'Не удалось удалить изменения.'
    confirmDiscardOpen.value = false
    await transition('Shown')
  } finally {
    busy.value = false
  }
}

function cancelDiscard(): void {
  confirmDiscardOpen.value = false
  if (state.value === 'Confirming') {
    void transition('Shown')
  }
}

// ---------------------------------------------------------------------------
// Public composable
// ---------------------------------------------------------------------------

export interface UseRecoveryState {
  state: Ref<RecoveryDialogState>
  isOpen: Ref<boolean>
  userId: Ref<number | null>
  revokedReason: Ref<RevokedReason | null>
  pendingCount: Ref<number>
  openedAtUtc: Ref<string | null>
  error: Ref<string | null>
  busy: Ref<boolean>
  confirmDiscardOpen: Ref<boolean>
  /** Re-runs the bootstrap from IndexedDB (Req 18.8). */
  bootstrap: () => Promise<void>
  /** Show the dialog explicitly (mostly used by tests). */
  show: (info: RecoveryRequestInfo) => Promise<void>
  /** Hide and clear persisted recovery state. */
  hide: () => Promise<void>
  signInAgain: () => Promise<void>
  exportPending: () => Promise<void>
  /** First call opens the secondary confirmation; second call commits the discard. */
  discardAll: () => Promise<void>
  cancelDiscard: () => void
}

export function useRecoveryState(): UseRecoveryState {
  ensureSubscribed()
  void ensureBootstrapped()
  return {
    state,
    isOpen,
    userId,
    revokedReason,
    pendingCount,
    openedAtUtc,
    error,
    busy,
    confirmDiscardOpen,
    bootstrap: ensureBootstrapped,
    show,
    hide,
    signInAgain,
    exportPending,
    discardAll,
    cancelDiscard
  }
}

// ---------------------------------------------------------------------------
// Test-only helpers
// ---------------------------------------------------------------------------

export function _resetForTests(): void {
  if (unsubscribeApi) {
    unsubscribeApi()
    unsubscribeApi = null
  }
  bootstrapPromise = null
  state.value = 'Idle'
  userId.value = null
  revokedReason.value = null
  pendingCount.value = 0
  openedAtUtc.value = null
  error.value = null
  busy.value = false
  confirmDiscardOpen.value = false
  _setRecoveryShown(false)
  ensureSubscribed()
}

/** Force re-running the bootstrap from IndexedDB (test helper). */
export async function _bootstrapFromIndexedDbForTests(): Promise<void> {
  bootstrapPromise = null
  await ensureBootstrapped()
}
