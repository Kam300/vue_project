<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { healthCheck, listFaces } from '@/services/api'
import type { HealthResponse } from '@/types/api'

const health = ref<HealthResponse | null>(null)
const latency = ref<number | null>(null)
const status = ref<'loading' | 'online' | 'offline' | 'error'>('loading')
const info = ref('')
const error = ref('')
const facesPreview = ref<Array<{ member_id: string; member_name: string }>>([])
const facesCount = ref(0)
const logs = ref<Array<{ ts: string; icon: string; message: string; type: string }>>([])

let timer: number | null = null

function addLocalLog(icon: string, message: string, type = 'info'): void {
  logs.value.unshift({
    ts: new Date().toLocaleTimeString('ru-RU'),
    icon,
    message,
    type
  })
  logs.value = logs.value.slice(0, 80)
}

async function refreshHealth(): Promise<void> {
  error.value = ''
  const started = performance.now()

  try {
    const response = await healthCheck()
    health.value = response
    latency.value = Math.round(performance.now() - started)
    status.value = 'online'
    info.value = 'Статус сервера обновлен.'

    const merged = [...(response.recent_events || []), ...logs.value]
    const keyMap = new Set<string>()
    const deduped: Array<{ ts: string; icon: string; message: string; type: string }> = []

    for (const item of merged) {
      const key = `${item.ts}_${item.icon}_${item.message}`
      if (keyMap.has(key)) continue
      keyMap.add(key)
      deduped.push({
        ts: item.ts,
        icon: item.icon,
        message: item.message,
        type: item.type || 'info'
      })
      if (deduped.length >= 80) break
    }

    logs.value = deduped
  } catch (reason) {
    status.value = 'offline'
    latency.value = null
    error.value = `Сервер недоступен: ${(reason as Error).message}`
  }
}

async function refreshFaces(): Promise<void> {
  error.value = ''
  try {
    const response = await listFaces()
    if (!response.success) {
      throw new Error(response.error || 'Ошибка получения списка лиц')
    }

    facesCount.value = response.count
    facesPreview.value = response.faces.slice(0, 10)
    addLocalLog('👥', `В базе распознавания ${response.count} лиц`, 'success')
    info.value = 'Список лиц обновлен.'
  } catch (reason) {
    error.value = `Не удалось получить список лиц: ${(reason as Error).message}`
    addLocalLog('⚠️', error.value, 'error')
  }
}

onMounted(async () => {
  await refreshHealth()
  timer = window.setInterval(refreshHealth, 15000)
})

onUnmounted(() => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
})
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="Панель сервера" subtitle="Health, latency, возможности API и журнал событий backend" />

      <article class="app-card panel-card">
        <div class="status-row">
          <span class="chip" :class="status === 'online' ? 'success' : status === 'offline' ? 'error' : 'warn'">
            Статус: {{ status }}
          </span>
          <span class="chip" v-if="latency !== null">Latency: {{ latency }}ms</span>
          <span class="chip" v-if="health">Faces: {{ health.members_count }}</span>
          <span class="chip" v-if="health">Backup API: {{ health.backup ? 'on' : 'off' }}</span>
        </div>

        <div class="btn-row action-row">
          <button class="btn-action" @click="refreshHealth">Обновить health</button>
          <button class="btn-action" @click="refreshFaces">Список лиц</button>
        </div>

        <div class="cap-grid" v-if="health">
          <div class="cap-item">
            <h3>Face recognition</h3>
            <p>{{ health.face_recognition ? 'Активно' : 'Выключено' }}</p>
          </div>
          <div class="cap-item">
            <h3>PDF generation</h3>
            <p>{{ health.pdf_generation ? 'Активно' : 'Выключено' }}</p>
          </div>
          <div class="cap-item">
            <h3>GPU</h3>
            <p>{{ health.gpu?.active_cuda ? 'CUDA' : 'CPU/HOG' }}</p>
          </div>
          <div class="cap-item">
            <h3>Модель</h3>
            <p>{{ health.gpu?.face_model || '-' }}</p>
          </div>
        </div>

        <div class="face-box" v-if="facesCount || facesPreview.length">
          <h3>Лица в базе: {{ facesCount }}</h3>
          <ul>
            <li v-for="face in facesPreview" :key="face.member_id">
              {{ face.member_name }} (ID {{ face.member_id }})
            </li>
          </ul>
        </div>

        <p v-if="info" class="status-line">{{ info }}</p>
        <p v-if="error" class="error">{{ error }}</p>
      </article>

      <article class="app-card panel-card">
        <h2>Журнал событий</h2>
        <div class="log-list">
          <div v-for="log in logs" :key="`${log.ts}_${log.message}`" class="log-item" :class="`log-${log.type}`">
            <span class="time">{{ log.ts }}</span>
            <span class="icon">{{ log.icon }}</span>
            <span>{{ log.message }}</span>
          </div>
          <div v-if="!logs.length" class="status-line">Журнал пуст.</div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.panel-card {
  padding: 16px;
}

.panel-card + .panel-card {
  margin-top: 14px;
}

.status-row,
.action-row {
  margin-bottom: 12px;
}

.cap-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 12px;
}

.cap-item {
  border: 1px solid var(--color-glass-border);
  border-radius: 12px;
  padding: 10px;
}

.cap-item h3 {
  font-size: 0.85rem;
  margin-bottom: 4px;
}

.cap-item p {
  color: var(--color-text-secondary);
  font-size: 0.88rem;
}

.face-box {
  border: 1px dashed var(--color-glass-border);
  border-radius: 12px;
  padding: 10px;
  margin-bottom: 12px;
}

.face-box ul {
  margin-top: 8px;
  display: grid;
  gap: 4px;
  padding-left: 16px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 420px;
  overflow: auto;
}

.log-item {
  border: 1px solid var(--color-glass-border);
  border-radius: 10px;
  padding: 8px 10px;
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  font-size: 0.84rem;
}

.log-item.log-success {
  border-color: rgba(52, 211, 153, 0.45);
}

.log-item.log-error {
  border-color: rgba(248, 113, 113, 0.45);
}

.time {
  color: var(--color-text-muted);
}

.error {
  color: var(--color-error);
}
</style>
