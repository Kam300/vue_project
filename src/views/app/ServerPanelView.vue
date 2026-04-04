<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { healthCheck, listFaces } from '@/services/api'
import type { HealthResponse } from '@/types/api'

const health = ref<HealthResponse | null>(null)
const latency = ref<number | null>(null)
const status = ref<'loading' | 'online' | 'offline' | 'error'>('loading')
const info = ref('')
const error = ref('')
const warning = ref('')
const facesPreview = ref<Array<{ member_id: string; member_name: string }>>([])
const facesCount = ref(0)
const logs = ref<Array<{ ts: string; icon: string; message: string; type: string }>>([])
const healthBusy = ref(false)
const facesBusy = ref(false)

let timer: number | null = null
let stopPolling = false
let healthRequestController: AbortController | null = null
let facesRequestController: AbortController | null = null
const LOG_ICON_ALIASES: Record<string, string> = {
  '\u{1F465}': 'groups',
  '\u26A0\uFE0F': 'warning',
  '\u2705': 'check_circle',
  '\u274C': 'error',
  '\u{1F514}': 'notifications'
}

function normalizeLogIcon(rawIcon?: string): string {
  if (!rawIcon) return 'notifications'
  if (LOG_ICON_ALIASES[rawIcon]) return LOG_ICON_ALIASES[rawIcon]
  if (/^[a-z0-9_]+$/i.test(rawIcon)) return rawIcon
  return 'notifications'
}

function addLocalLog(icon: string, message: string, type = 'info'): void {
  logs.value.unshift({
    ts: new Date().toLocaleTimeString('ru-RU'),
    icon,
    message,
    type
  })
  logs.value = logs.value.slice(0, 80)
}

function getNowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now()
}

function clearRefreshTimer(): void {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
}

function scheduleRefresh(delay = 15000): void {
  clearRefreshTimer()
  if (stopPolling) return
  timer = window.setTimeout(() => {
    void refreshHealth()
  }, delay)
}

function isCancelled(controller: AbortController | null, reason: unknown): boolean {
  return Boolean(controller?.signal.aborted) || (reason instanceof Error && reason.message === 'Запрос был отменён.')
}

async function refreshHealth(): Promise<void> {
  if (healthBusy.value) return

  error.value = ''
  warning.value = ''
  healthBusy.value = true
  const started = getNowMs()
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  healthRequestController = controller

  try {
    const response = await healthCheck({
      signal: controller?.signal,
      timeoutMs: 8000
    })
    health.value = response
    latency.value = Math.round(getNowMs() - started)
    status.value = 'online'
    info.value = 'Статус сервера обновлен.'
    if (!response.face_recognition) {
      warning.value = response.face_recognition_error
        ? `AI-распознавание отключено на этом сервере: ${response.face_recognition_error}`
        : 'AI-распознавание отключено на этом сервере.'
    }

    const merged = [...(response.recent_events || []), ...logs.value]
    const keyMap = new Set<string>()
    const deduped: Array<{ ts: string; icon: string; message: string; type: string }> = []

    for (const item of merged) {
      const key = `${item.ts}_${item.icon}_${item.message}`
      if (keyMap.has(key)) continue
      keyMap.add(key)
      deduped.push({
        ts: item.ts,
        icon: normalizeLogIcon(item.icon),
        message: item.message,
        type: item.type || 'info'
      })
      if (deduped.length >= 80) break
    }

    logs.value = deduped
  } catch (reason) {
    if (isCancelled(controller, reason) || stopPolling) return
    status.value = 'offline'
    latency.value = null
    error.value = `Сервер недоступен: ${(reason as Error).message}`
  } finally {
    if (healthRequestController === controller) {
      healthRequestController = null
    }
    healthBusy.value = false
    if (!stopPolling) {
      scheduleRefresh()
    }
  }
}

async function refreshFaces(): Promise<void> {
  if (facesBusy.value) return

  error.value = ''
  facesBusy.value = true
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  facesRequestController = controller
  try {
    const response = await listFaces({
      signal: controller?.signal,
      timeoutMs: 10000
    })
    if (!response.success) {
      throw new Error(response.error || 'Ошибка получения списка лиц')
    }

    facesCount.value = response.count
    facesPreview.value = response.faces.slice(0, 10)
    addLocalLog('groups', `В базе распознавания ${response.count} лиц`, 'success')
    info.value = 'Список лиц обновлен.'
  } catch (reason) {
    if (isCancelled(controller, reason)) return
    error.value = `Не удалось получить список лиц: ${(reason as Error).message}`
    addLocalLog('warning', error.value, 'error')
  } finally {
    if (facesRequestController === controller) {
      facesRequestController = null
    }
    facesBusy.value = false
  }
}

onMounted(async () => {
  stopPolling = false
  await refreshHealth()
})

onUnmounted(() => {
  stopPolling = true
  clearRefreshTimer()
  healthRequestController?.abort()
  facesRequestController?.abort()
})
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader icon="dns" title="Панель сервера" subtitle="Health, latency, возможности API и журнал событий" />

      <article class="app-card panel-card">
        <!-- Status dashboard -->
        <div class="dashboard-grid">
          <div class="dash-card" :class="status">
            <div class="dash-icon-wrap">
              <span class="dash-dot" :class="status"></span>
            </div>
            <div>
              <div class="dash-label">Статус</div>
              <div class="dash-value">{{ status === 'online' ? 'Онлайн' : status === 'offline' ? 'Офлайн' : status === 'error' ? 'Ошибка' : 'Загрузка...' }}</div>
            </div>
          </div>

          <div class="dash-card">
            <div class="dash-icon-wrap"><AppIcon name="bolt" :size="22" /></div>
            <div>
              <div class="dash-label">Latency</div>
              <div class="dash-value">{{ latency !== null ? latency + 'ms' : '—' }}</div>
            </div>
          </div>

          <div class="dash-card" v-if="health">
            <div class="dash-icon-wrap"><AppIcon name="groups" :size="22" /></div>
            <div>
              <div class="dash-label">Faces</div>
              <div class="dash-value">{{ health.members_count }}</div>
            </div>
          </div>

          <div class="dash-card" v-if="health">
            <div class="dash-icon-wrap"><AppIcon name="save" :size="22" /></div>
            <div>
              <div class="dash-label">Backup API</div>
              <div class="dash-value">{{ health.backup ? 'Активен' : 'Выкл' }}</div>
            </div>
          </div>
        </div>

        <div class="btn-row action-row">
          <button class="btn-action" @click="refreshHealth" :disabled="healthBusy">
            <AppIcon name="refresh" :size="16" />
            {{ healthBusy ? 'Обновляем...' : 'Обновить health' }}
          </button>
          <button class="btn-action" @click="refreshFaces" :disabled="facesBusy">
            <AppIcon name="person_search" :size="16" />
            {{ facesBusy ? 'Загружаем...' : 'Список лиц' }}
          </button>
        </div>

        <p v-if="warning" class="warn-msg" style="margin-top: 8px">{{ warning }}</p>

        <!-- Capabilities -->
        <div class="cap-grid" v-if="health">
          <div class="cap-item" :class="{ active: health.face_recognition }">
            <span class="cap-icon"><AppIcon name="psychology" :size="22" /></span>
            <h3>Face recognition</h3>
            <span class="chip" :class="health.face_recognition ? 'success' : ''">
              {{ health.face_recognition ? 'Активно' : 'Выкл' }}
            </span>
          </div>
          <div class="cap-item" :class="{ active: health.pdf_generation }">
            <span class="cap-icon"><AppIcon name="description" :size="22" /></span>
            <h3>PDF generation</h3>
            <span class="chip" :class="health.pdf_generation ? 'success' : ''">
              {{ health.pdf_generation ? 'Активно' : 'Выкл' }}
            </span>
          </div>
          <div class="cap-item">
            <span class="cap-icon"><AppIcon name="memory" :size="22" /></span>
            <h3>GPU</h3>
            <span class="chip">{{ health.gpu?.active_cuda ? 'CUDA' : 'CPU/HOG' }}</span>
          </div>
          <div class="cap-item">
            <span class="cap-icon"><AppIcon name="smart_toy" :size="22" /></span>
            <h3>Модель</h3>
            <span class="chip">{{ health.gpu?.face_model || '—' }}</span>
          </div>
        </div>

        <!-- Faces preview -->
        <div class="face-box" v-if="facesCount || facesPreview.length">
          <h3 class="with-icon">
            <AppIcon name="groups" :size="20" />
            Лица в базе: {{ facesCount }}
          </h3>
          <div class="face-chips">
            <span v-for="face in facesPreview" :key="face.member_id" class="chip">
              {{ face.member_name }}
            </span>
          </div>
        </div>

        <p v-if="info" class="status-line" style="margin-top: 12px">{{ info }}</p>
        <p v-if="error" class="error-msg" style="margin-top: 8px">{{ error }}</p>
      </article>

      <!-- Event log -->
      <article class="app-card panel-card" style="margin-top: 16px">
        <h2 class="log-title with-icon">
          <AppIcon name="list_alt" :size="20" />
          Журнал событий
        </h2>
        <div class="log-list">
          <TransitionGroup name="log-anim">
            <div v-for="log in logs" :key="`${log.ts}_${log.message}`" class="log-item" :class="`log-${log.type}`">
              <span class="time">{{ log.ts }}</span>
              <span class="icon"><AppIcon :name="normalizeLogIcon(log.icon)" :size="16" /></span>
              <span class="log-text">{{ log.message }}</span>
            </div>
          </TransitionGroup>
          <div v-if="!logs.length" class="empty-state" style="padding: 24px">Журнал пуст.</div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.panel-card {
  padding: 20px;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* Dashboard grid */
.dashboard-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 16px;
}

.dash-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  transition: all var(--transition-fast);
}

.dash-card:hover {
  background: var(--card-hover-bg);
  border-color: rgba(124, 92, 252, 0.2);
}

.dash-card.online {
  border-color: rgba(52, 211, 153, 0.3);
}

.dash-card.offline,
.dash-card.error {
  border-color: rgba(248, 113, 113, 0.3);
}

.dash-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dash-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-text-muted);
  animation: blink-dot 2s ease infinite;
}

.dash-dot.online {
  background: var(--color-success);
  box-shadow: 0 0 8px var(--color-success);
}

.dash-dot.offline {
  background: var(--color-error);
}

.dash-label {
  font-size: 0.72rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.dash-value {
  font-size: 1.05rem;
  font-weight: 600;
}

.action-row {
  margin-bottom: 16px;
}

/* Capabilities */
.cap-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 16px;
}

.cap-item {
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all var(--transition-fast);
}

.cap-item.active {
  border-color: rgba(52, 211, 153, 0.3);
}

.cap-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.cap-item h3 {
  font-size: 0.85rem;
  font-weight: 600;
}

/* Faces */
.face-box {
  border: 1px dashed var(--color-glass-border);
  border-radius: var(--radius-md);
  padding: 14px;
}

.face-box h3 {
  font-size: 0.95rem;
  margin-bottom: 10px;
}

.face-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* Log */
.log-title {
  font-size: 1rem;
  margin-bottom: 12px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 420px;
  overflow: auto;
}

.log-item {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 0.84rem;
  transition: background var(--transition-fast);
}

.log-item:hover {
  background: var(--color-surface-hover);
}

.log-item.log-success {
  border-left: 3px solid var(--color-success);
}

.log-item.log-error {
  border-left: 3px solid var(--color-error);
}

.time {
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.log-text {
  color: var(--color-text-secondary);
}

.error-msg {
  color: var(--color-error);
  font-size: 0.85rem;
}

.warn-msg {
  color: #fbbf24;
  font-size: 0.9rem;
}

.log-anim-enter-active {
  animation: slide-in-log 0.3s ease-out;
}
</style>
