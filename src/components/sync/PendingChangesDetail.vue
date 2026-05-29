<script setup lang="ts">
// PendingChangesDetail.vue — Web client.
//
// Spec refs: .kiro/specs/multi-device-sync-safety/design.md §4.6.
// Requirements: 19.4.
//
// Lists each pending change's `sequenceNumber`, `createdAtUtc`, `editKind`,
// `targetId`. Header shows the most recent Auto_Sync_Tick result
// (timestamp, HTTP status, short reason) sourced from `useSyncStatus()`.
// Opened via `useDetailState().show()` from PendingChangesBadge.

import { ref, watch, type Ref } from 'vue'
import { pendingChangesRepo } from '@/db/pendingChanges'
import { useAppStore } from '@/stores/appStore'
import { useDetailState, useSyncStatus } from '@/composables/useSyncStatus'
import type { PendingChange } from '@/types/sync'

const detail = useDetailState()
const { lastSyncResult } = useSyncStatus()

const rows: Ref<PendingChange[]> = ref([])
const loading = ref(false)
const error = ref('')

function resolveUserId(): number | null {
  try {
    const id = useAppStore().authUser?.id
    if (Number.isInteger(id) && (id as number) > 0) return id as number
  } catch {
    // Pinia not active in some test setups.
  }
  return null
}

async function reload(): Promise<void> {
  const userId = resolveUserId()
  if (userId === null) {
    rows.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    rows.value = await pendingChangesRepo.list(userId)
  } catch (reason) {
    error.value = (reason as Error).message || 'Не удалось загрузить буфер изменений.'
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(
  detail.isOpen,
  (open) => {
    if (open) void reload()
  },
  { immediate: true }
)

function close(): void {
  detail.hide()
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString()
}

function statusClass(status: number | null | undefined): string {
  if (status === 200) return 'status-ok'
  if (status === 409) return 'status-conflict'
  if (status === 428) return 'status-precondition'
  if (status === 401) return 'status-revoked'
  if (typeof status === 'number' && status >= 500) return 'status-error'
  return 'status-unknown'
}
</script>

<template>
  <Transition name="detail-fade">
    <div
      v-if="detail.isOpen.value"
      class="detail-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pending-detail-title"
      @click.self="close"
    >
      <div class="detail-card">
        <header class="detail-head">
          <h2 id="pending-detail-title" class="detail-title">Несинхронизированные изменения</h2>
          <button
            type="button"
            class="detail-close"
            aria-label="Закрыть"
            @click="close"
          >
            ×
          </button>
        </header>

        <section class="detail-status">
          <h3 class="detail-status-title">Последняя попытка синхронизации</h3>
          <dl v-if="lastSyncResult" class="detail-status-grid">
            <div>
              <dt>Время (UTC)</dt>
              <dd>{{ formatDate(lastSyncResult.atUtc) }}</dd>
            </div>
            <div>
              <dt>HTTP</dt>
              <dd :class="statusClass(lastSyncResult.httpStatus)">
                {{ lastSyncResult.httpStatus || '—' }}
              </dd>
            </div>
            <div>
              <dt>Причина</dt>
              <dd>{{ lastSyncResult.reason }}</dd>
            </div>
          </dl>
          <p v-else class="detail-status-empty">Синхронизация ещё не запускалась.</p>
        </section>

        <section class="detail-list">
          <p v-if="loading" class="detail-empty">Загрузка…</p>
          <p v-else-if="error" class="detail-error" role="alert">{{ error }}</p>
          <p v-else-if="rows.length === 0" class="detail-empty">
            Нет несинхронизированных изменений.
          </p>
          <table v-else class="detail-table">
            <thead>
              <tr>
                <th class="col-seq">#</th>
                <th class="col-time">Создано (UTC)</th>
                <th class="col-kind">Тип</th>
                <th class="col-target">Цель</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.changeId">
                <td class="col-seq">{{ row.sequenceNumber }}</td>
                <td class="col-time">{{ formatDate(row.createdAtUtc) }}</td>
                <td class="col-kind">{{ row.editKind }}</td>
                <td class="col-target" :title="row.targetId">{{ row.targetId || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <footer class="detail-actions">
          <button type="button" class="btn btn-ghost" @click="close">Закрыть</button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.detail-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(8, 12, 22, 0.62);
  backdrop-filter: blur(4px);
}

.detail-card {
  width: min(720px, 100%);
  max-height: min(80vh, 720px);
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  gap: 14px;
  padding: 22px;
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.12));
  background: var(--color-bg-alt, #161b29);
  color: var(--color-text, #ecedf3);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-title {
  margin: 0;
  font-size: 1.12rem;
  font-weight: 700;
}

.detail-close {
  appearance: none;
  background: transparent;
  border: 0;
  color: var(--color-text-secondary, #a1a7b8);
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
}

.detail-close:hover {
  background: var(--color-surface-hover, rgba(255, 255, 255, 0.06));
}

.detail-status {
  padding: 12px 14px;
  border-radius: var(--radius-md, 12px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.08));
  background: var(--color-surface, rgba(255, 255, 255, 0.03));
}

.detail-status-title {
  margin: 0 0 8px;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary, #a1a7b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.detail-status-grid > div {
  display: grid;
  gap: 2px;
}

.detail-status-grid dt {
  margin: 0;
  font-size: 0.74rem;
  color: var(--color-text-secondary, #a1a7b8);
}

.detail-status-grid dd {
  margin: 0;
  font-size: 0.88rem;
  font-variant-numeric: tabular-nums;
  word-break: break-word;
}

.detail-status-empty {
  margin: 0;
  font-size: 0.86rem;
  color: var(--color-text-secondary, #a1a7b8);
}

.status-ok {
  color: #6ddc8a;
}
.status-conflict {
  color: #ffb74d;
}
.status-precondition {
  color: #ffd166;
}
.status-revoked {
  color: #ff8a95;
}
.status-error {
  color: #ff8a95;
}
.status-unknown {
  color: var(--color-text-secondary, #a1a7b8);
}

.detail-list {
  overflow: auto;
  border-radius: var(--radius-md, 12px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.08));
  background: var(--color-surface, rgba(255, 255, 255, 0.02));
}

.detail-empty,
.detail-error {
  margin: 0;
  padding: 18px;
  font-size: 0.88rem;
  text-align: center;
  color: var(--color-text-secondary, #a1a7b8);
}

.detail-error {
  color: #ff8a95;
}

.detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.detail-table thead th {
  position: sticky;
  top: 0;
  background: var(--color-bg-alt, #161b29);
  border-bottom: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.1));
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary, #a1a7b8);
  padding: 8px 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 0.74rem;
}

.detail-table tbody td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.06));
  vertical-align: top;
}

.detail-table tbody tr:last-child td {
  border-bottom: 0;
}

.col-seq {
  width: 56px;
  font-variant-numeric: tabular-nums;
}

.col-time {
  width: 200px;
  font-variant-numeric: tabular-nums;
}

.col-kind {
  width: 180px;
}

.col-target {
  word-break: break-all;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn {
  appearance: none;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 9px 18px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 140ms ease, background 140ms ease, border-color 140ms ease;
}

.btn-ghost {
  background: transparent;
  border-color: var(--color-glass-border, rgba(255, 255, 255, 0.18));
  color: var(--color-text, #ecedf3);
}

.btn-ghost:hover:not(:disabled) {
  background: var(--color-surface-hover, rgba(255, 255, 255, 0.06));
}

.detail-fade-enter-active,
.detail-fade-leave-active {
  transition: opacity 160ms ease;
}

.detail-fade-enter-from,
.detail-fade-leave-to {
  opacity: 0;
}
</style>
