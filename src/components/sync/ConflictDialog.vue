<script setup lang="ts">
// Conflict_Dialog modal — Web client.
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.4.
// Requirements: 2.1, 2.4, 2.5, 2.6, 2.7, 2.8.

import { computed, ref, watch } from 'vue'
import { useConflictState } from '@/composables/useConflictState'
import { backupMeta } from '@/services/api'
import { createBackupArchive, type BackupArchiveBuildResult } from '@/services/backupArchive'
import { useAppStore } from '@/stores/appStore'
import type { BackupMetaResponse } from '@/types/api'

const conflict = useConflictState()

const serverMeta = ref<BackupMetaResponse | null>(null)
const localArchive = ref<BackupArchiveBuildResult | null>(null)
const busy = ref<'download' | 'overwrite' | ''>('')
const error = ref<string>('')
const loadingMeta = ref(false)

const isOpen = computed(() => conflict.isOpen.value)

function deviceId(): string {
  try {
    return String(useAppStore().settings?.deviceId || '')
  } catch {
    return ''
  }
}

async function loadServerMeta(): Promise<void> {
  loadingMeta.value = true
  try {
    serverMeta.value = await backupMeta('', deviceId())
  } catch (reason) {
    error.value = (reason as Error).message || 'Не удалось получить метаданные сервера.'
  } finally {
    loadingMeta.value = false
  }
}

async function loadLocalArchive(): Promise<void> {
  try {
    localArchive.value = await createBackupArchive()
  } catch (reason) {
    error.value = (reason as Error).message || 'Не удалось собрать локальный архив.'
  }
}

watch(
  isOpen,
  async (open) => {
    if (!open) {
      serverMeta.value = null
      localArchive.value = null
      busy.value = ''
      error.value = ''
      return
    }
    error.value = ''
    await Promise.all([loadServerMeta(), loadLocalArchive()])
  },
  { immediate: true }
)

function formatBytes(n?: number | null): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '—'
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / (1024 * 1024)).toFixed(2)} МБ`
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString()
}

function shortHash(hash?: string | null): string {
  if (!hash) return '—'
  return hash.length > 16 ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : hash
}

async function onDownload(): Promise<void> {
  if (busy.value) return
  busy.value = 'download'
  error.value = ''
  try {
    await conflict.downloadServer()
  } catch (reason) {
    error.value = (reason as Error).message || 'Не удалось скачать backup с сервера.'
  } finally {
    busy.value = ''
  }
}

async function onOverwrite(): Promise<void> {
  if (busy.value) return
  busy.value = 'overwrite'
  error.value = ''
  try {
    await conflict.overwriteAnyway()
  } catch (reason) {
    error.value = (reason as Error).message || 'Не удалось перезаписать backup.'
  } finally {
    busy.value = ''
  }
}

function onCancel(): void {
  if (busy.value) return
  conflict.cancel()
}
</script>

<template>
  <Transition name="conflict-fade">
    <div
      v-if="isOpen"
      class="conflict-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="conflict-title"
    >
      <div class="conflict-card">
        <header class="conflict-head">
          <h2 id="conflict-title" class="conflict-title">Конфликт синхронизации</h2>
          <p class="conflict-sub">
            На сервере есть более новая версия архива, чем та, что известна этому устройству.
            Выберите, как разрешить конфликт.
          </p>
        </header>

        <section class="conflict-grid">
          <div class="conflict-col">
            <h3 class="conflict-col-title">Версия на сервере</h3>
            <dl class="conflict-meta">
              <div>
                <dt>Обновлено (UTC)</dt>
                <dd>
                  <span v-if="loadingMeta">…</span>
                  <span v-else>{{ formatDate(serverMeta?.updatedAtUtc) }}</span>
                </dd>
              </div>
              <div>
                <dt>Размер</dt>
                <dd>{{ formatBytes(serverMeta?.sizeBytes) }}</dd>
              </div>
              <div>
                <dt>SHA-256</dt>
                <dd :title="serverMeta?.checksumSha256 || ''">
                  {{ shortHash(serverMeta?.checksumSha256) }}
                </dd>
              </div>
            </dl>
          </div>

          <div class="conflict-col">
            <h3 class="conflict-col-title">Локальный архив</h3>
            <dl class="conflict-meta">
              <div>
                <dt>Создан (UTC)</dt>
                <dd>{{ formatDate(localArchive?.createdAtUtc) }}</dd>
              </div>
              <div>
                <dt>Размер</dt>
                <dd>{{ formatBytes(localArchive?.sizeBytes) }}</dd>
              </div>
              <div>
                <dt>SHA-256</dt>
                <dd :title="localArchive?.checksumSha256 || ''">
                  {{ shortHash(localArchive?.checksumSha256) }}
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <p v-if="error" class="conflict-error" role="alert">{{ error }}</p>

        <footer class="conflict-actions">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="busy !== ''"
            @click="onDownload"
          >
            {{ busy === 'download' ? 'Скачивание…' : 'Скачать с сервера' }}
          </button>
          <button
            type="button"
            class="btn btn-danger"
            :disabled="busy !== ''"
            @click="onOverwrite"
          >
            {{ busy === 'overwrite' ? 'Загрузка…' : 'Перезаписать всё равно' }}
          </button>
          <button
            type="button"
            class="btn btn-ghost"
            :disabled="busy !== ''"
            @click="onCancel"
          >
            Отмена
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.conflict-overlay {
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

.conflict-card {
  width: min(640px, 100%);
  display: grid;
  gap: 18px;
  padding: 24px;
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.12));
  background: var(--color-surface, #161b29);
  color: var(--color-text, #ecedf3);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.conflict-head {
  display: grid;
  gap: 6px;
}

.conflict-title {
  margin: 0;
  font-size: 1.18rem;
  line-height: 1.3;
  font-weight: 700;
}

.conflict-sub {
  margin: 0;
  color: var(--color-text-secondary, #a1a7b8);
  font-size: 0.88rem;
  line-height: 1.45;
}

.conflict-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 520px) {
  .conflict-grid {
    grid-template-columns: 1fr;
  }
}

.conflict-col {
  padding: 14px;
  border-radius: var(--radius-md, 12px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.08));
  background: rgba(255, 255, 255, 0.03);
}

.conflict-col-title {
  margin: 0 0 10px;
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--color-text-secondary, #a1a7b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.conflict-meta {
  display: grid;
  gap: 8px;
  margin: 0;
}

.conflict-meta > div {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
}

.conflict-meta dt {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary, #a1a7b8);
}

.conflict-meta dd {
  margin: 0;
  font-size: 0.86rem;
  word-break: break-all;
  font-variant-numeric: tabular-nums;
}

.conflict-error {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm, 8px);
  background: rgba(220, 53, 69, 0.12);
  color: #ff8a95;
  font-size: 0.86rem;
}

.conflict-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
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

.btn:disabled {
  opacity: 0.6;
  cursor: progress;
}

.btn-primary {
  background: var(--gradient-accent, linear-gradient(135deg, #4f80ff, #6a5cff));
  color: #fff;
}

.btn-danger {
  background: rgba(220, 53, 69, 0.18);
  border-color: rgba(220, 53, 69, 0.38);
  color: #ff8a95;
}

.btn-danger:hover:not(:disabled) {
  background: rgba(220, 53, 69, 0.26);
}

.btn-ghost {
  background: transparent;
  border-color: var(--color-glass-border, rgba(255, 255, 255, 0.18));
  color: var(--color-text, #ecedf3);
}

.btn-ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.conflict-fade-enter-active,
.conflict-fade-leave-active {
  transition: opacity 160ms ease;
}

.conflict-fade-enter-from,
.conflict-fade-leave-to {
  opacity: 0;
}
</style>
