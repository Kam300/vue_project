<script setup lang="ts">
// PendingChangesBadge.vue — Web client.
//
// Spec refs: .kiro/specs/multi-device-sync-safety/design.md §4.6.
// Requirements: 19.1, 19.3, 19.5, 19.6.
//
// Subscribes to `pendingChangesRepo.count$(userId)` and renders the count of
// pending changes in the application header. Visible while N > 0, hidden
// within 1 s of N reaching 0 (Req 19.3, 19.5, 19.6). Always rendered
// regardless of Offline_State.
//
// Activating the badge opens PendingChangesDetail (task 7.4); for now we
// just emit an `open` event so the parent can wire it up later.

import { computed, ref, watch, type Ref } from 'vue'
import { pendingChangesRepo } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import { useDetailState } from '@/composables/useSyncStatus'

const detail = useDetailState()

const ZERO_REF: Ref<number> = ref(0)

function resolveUserId(): number | null {
  try {
    const id = useAppStore().authUser?.id
    if (Number.isInteger(id) && (id as number) > 0) return id as number
  } catch {
    // Pinia might not be active during certain test setups.
  }
  return null
}

const userId = resolveUserId()
const count: Ref<number> = userId === null ? ZERO_REF : pendingChangesRepo.count$(userId)

// Russian pluralisation for "изменение" (change).
function pluralize(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'изменение'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'изменения'
  return 'изменений'
}

function adjective(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'несинхронизированное'
  return 'несинхронизированных'
}

const label = computed(() => `${count.value} ${adjective(count.value)} ${pluralize(count.value)}`)

// Visibility tracks count > 0. The hide-on-empty transition is bounded by
// 1 s (Req 19.3); we hide immediately, well within budget.
const visible = ref(count.value > 0)
watch(
  count,
  (next) => {
    visible.value = next > 0
  },
  { flush: 'post' }
)

const emit = defineEmits<{
  (event: 'open'): void
}>()

function onActivate(): void {
  detail.show()
  emit('open')
}
</script>

<template>
  <button
    v-if="visible"
    type="button"
    class="pending-badge"
    :title="label"
    :aria-label="label"
    @click="onActivate"
  >
    <span class="pending-badge-count">{{ count }}</span>
    <span class="pending-badge-text">{{ adjective(count) }} {{ pluralize(count) }}</span>
  </button>
</template>

<style scoped>
.pending-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 167, 38, 0.55);
  background: rgba(255, 167, 38, 0.16);
  color: #ffb74d;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
}

.pending-badge:hover {
  background: rgba(255, 167, 38, 0.24);
  border-color: rgba(255, 167, 38, 0.75);
  transform: translateY(-1px);
}

.pending-badge:focus-visible {
  outline: 2px solid rgba(255, 167, 38, 0.8);
  outline-offset: 2px;
}

.pending-badge-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  padding: 0 4px;
  border-radius: 999px;
  background: rgba(255, 167, 38, 0.85);
  color: #1a1a1a;
  font-size: 0.72rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.pending-badge-text {
  white-space: nowrap;
}

@media (max-width: 480px) {
  .pending-badge-text {
    display: none;
  }
}
</style>
