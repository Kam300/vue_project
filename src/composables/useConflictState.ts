// Conflict_Dialog state machine composable.
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.4.
// Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8.
//
// Subscribes to `onConflict` from `@/services/syncTicker` on module load and
// flips `isOpen` whenever a 409 is observed by the ticker. Components consume
// this composable to render `ConflictDialog.vue` and dispatch actions.

import { ref, type Ref } from 'vue'
import { onConflict, type ConflictMeta } from '@/services/syncTicker'
import { backupDownload, backupMeta, backupUploadWithMatch } from '@/services/api'
import { createBackupArchive, restoreBackupArchive } from '@/services/backupArchive'
import { pendingChangesRepo } from '@/db/pendingChanges'

// ---------------------------------------------------------------------------
// Module-level state (single shared dialog instance per app).
// ---------------------------------------------------------------------------

const isOpen: Ref<boolean> = ref(false)
const meta: Ref<ConflictMeta | null> = ref(null)
const lastServerTag: Ref<string | null> = ref(null)

function show(m: ConflictMeta): void {
  meta.value = m
  isOpen.value = true
}

function hide(): void {
  isOpen.value = false
  meta.value = null
}

// Subscribe at module load (Req 2.4).
let unsubscribe: (() => void) | null = null
function ensureSubscribed(): void {
  if (unsubscribe) return
  unsubscribe = onConflict((m) => {
    show(m)
  })
}
ensureSubscribed()

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function activeDeviceId(): Promise<string> {
  try {
    const mod = await import('@/stores/appStore')
    return String(mod.useAppStore().settings?.deviceId || '')
  } catch {
    return ''
  }
}

async function refreshServerTag(deviceId: string): Promise<void> {
  try {
    const m = await backupMeta('', deviceId)
    lastServerTag.value = m.serverVersionTag || null
  } catch {
    // best-effort; the next syncTicker tick will retry.
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * "Скачать с сервера" (Req 2.5): GET /v2/backup/download, replace the local
 * archive, refresh last-known Server_Version_Tag via backupMeta, close dialog.
 */
async function downloadServer(): Promise<void> {
  const deviceId = await activeDeviceId()
  const blob = await backupDownload('', deviceId)
  await restoreBackupArchive(blob)
  await refreshServerTag(deviceId)
  hide()
}

/**
 * "Перезаписать всё равно" (Req 2.6): re-issue upload with force=true, update
 * last-known tag from the response, atomically remove confirmed changeIds,
 * close dialog.
 */
async function overwriteAnyway(): Promise<void> {
  const m = meta.value
  if (!m) {
    hide()
    return
  }
  const deviceId = await activeDeviceId()
  const archive = await createBackupArchive()
  const response = await backupUploadWithMatch({
    authToken: '',
    deviceId,
    zipFile: archive.file,
    ifMatch: m.serverTag || '*',
    force: true,
    changeIds: m.changeIds
  })
  if (response.serverVersionTag) {
    lastServerTag.value = response.serverVersionTag
  }
  if (m.changeIds.length > 0) {
    await pendingChangesRepo.deleteByIds(m.userId, m.changeIds)
  }
  hide()
}

/**
 * "Отмена" (Req 2.7): discard the upload attempt; leave the buffer and
 * last-known Server_Version_Tag unchanged.
 */
function cancel(): void {
  hide()
}

// ---------------------------------------------------------------------------
// Public composable
// ---------------------------------------------------------------------------

export interface UseConflictState {
  isOpen: Ref<boolean>
  meta: Ref<ConflictMeta | null>
  lastServerTag: Ref<string | null>
  show: (m: ConflictMeta) => void
  hide: () => void
  downloadServer: () => Promise<void>
  overwriteAnyway: () => Promise<void>
  cancel: () => void
}

export function useConflictState(): UseConflictState {
  ensureSubscribed()
  return {
    isOpen,
    meta,
    lastServerTag,
    show,
    hide,
    downloadServer,
    overwriteAnyway,
    cancel
  }
}

// ---------------------------------------------------------------------------
// Test-only helpers
// ---------------------------------------------------------------------------

export function _resetForTests(): void {
  hide()
  lastServerTag.value = null
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
  ensureSubscribed()
}
