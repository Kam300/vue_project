// useSyncStatus — exposes the most recent Auto_Sync_Tick result.
//
// Spec refs:
//   .kiro/specs/multi-device-sync-safety/design.md §4.6.
// Requirements: 19.4.
//
// PendingChangesDetail.vue reads `lastSyncResult` to render the timestamp,
// HTTP status, and short reason of the most recent tick. The ticker calls
// `_recordSyncResult()` from `@/services/syncTicker` on every 200 / 409 /
// 428 / 5xx outcome (and on session_revoked / network errors); this
// composable subscribes once and mirrors the latest event into a Vue ref.

import { ref, type Ref } from 'vue'
import { onSyncResult, type SyncResult } from '@/services/syncTicker'

const lastSyncResult: Ref<SyncResult | null> = ref(null)

let unsubscribe: (() => void) | null = null
function ensureSubscribed(): void {
  if (unsubscribe) return
  unsubscribe = onSyncResult((result) => {
    lastSyncResult.value = result
  })
}
ensureSubscribed()

export interface UseSyncStatus {
  lastSyncResult: Ref<SyncResult | null>
}

export function useSyncStatus(): UseSyncStatus {
  ensureSubscribed()
  return { lastSyncResult }
}

// ---------------------------------------------------------------------------
// Detail dialog open/close coordination.
// PendingChangesBadge calls `useDetailState().show()`; PendingChangesDetail
// reads `isOpen` and calls `hide()` on close.
// ---------------------------------------------------------------------------

const detailOpen: Ref<boolean> = ref(false)

export interface UseDetailState {
  isOpen: Ref<boolean>
  show: () => void
  hide: () => void
  toggle: () => void
}

export function useDetailState(): UseDetailState {
  return {
    isOpen: detailOpen,
    show: () => {
      detailOpen.value = true
    },
    hide: () => {
      detailOpen.value = false
    },
    toggle: () => {
      detailOpen.value = !detailOpen.value
    }
  }
}

// ---------------------------------------------------------------------------
// Test-only helpers
// ---------------------------------------------------------------------------

export function _resetForTests(): void {
  lastSyncResult.value = null
  detailOpen.value = false
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
  ensureSubscribed()
}
