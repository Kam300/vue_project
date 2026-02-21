<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useMemberStore } from '@/stores/memberStore'
import { useAppStore } from '@/stores/appStore'
import { addBackupAudit } from '@/db/repositories'
import { healthCheck, recognizeFace } from '@/services/api'
import { fromServerMemberId, syncProfileFaces } from '@/services/familySync'
import { compressImageToJpeg, fileToDataUrl } from '@/utils/image'

interface PhotoTask {
  id: string
  fileName: string
  dataUrl: string
  status: 'pending' | 'recognized' | 'manual' | 'failed' | 'saved' | 'duplicate'
  recognizedMemberId: number | null
  selectedMemberId: number | null
  confidence: number | null
  facesCount: number
  error: string
}

const memberStore = useMemberStore()
const appStore = useAppStore()

const pickInput = ref<HTMLInputElement | null>(null)
const queue = ref<PhotoTask[]>([])
const threshold = ref(0.6)
const recognitionBusy = ref(false)
const saveBusy = ref(false)
const syncBusy = ref(false)
const info = ref('')
const error = ref('')
const serverStatus = ref<'unknown' | 'online' | 'offline'>('unknown')
const serverLatency = ref<number | null>(null)
const bulkMemberId = ref<number | null>(null)

const memberOptions = computed(() => memberStore.members)

const recognizedGroups = computed(() => {
  const groups = new Map<number, PhotoTask[]>()
  for (const task of queue.value) {
    if (!task.selectedMemberId) continue
    const current = groups.get(task.selectedMemberId) || []
    current.push(task)
    groups.set(task.selectedMemberId, current)
  }
  return Array.from(groups.entries())
    .map(([memberId, tasks]) => ({
      memberId,
      member: memberStore.membersById.get(memberId) || null,
      tasks
    }))
    .sort((a, b) => a.memberId - b.memberId)
})

const unresolvedTasks = computed(() => queue.value.filter((task) => !task.selectedMemberId))

onMounted(async () => {
  if (!memberStore.members.length) {
    await memberStore.refresh()
  }
  await checkServer()
})

function openPicker(): void {
  pickInput.value?.click()
}

function resetMessages(): void {
  info.value = ''
  error.value = ''
}

function createTaskId(fileName: string): string {
  return `${Date.now()}_${Math.random().toString(36).slice(2)}_${fileName}`
}

async function onFilesPicked(event: Event): Promise<void> {
  resetMessages()
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (!files.length) return

  const incoming = files.slice(0, 20)
  if (files.length > 20) {
    info.value = 'Одновременно можно загрузить не более 20 фотографий. Лишние файлы пропущены.'
  }

  const tasks: PhotoTask[] = []
  for (const file of incoming) {
    const compressed = await compressImageToJpeg(file, { maxEdge: 1280, quality: 0.85 })
    const dataUrl = await fileToDataUrl(compressed)
    tasks.push({
      id: createTaskId(file.name),
      fileName: file.name,
      dataUrl,
      status: 'pending',
      recognizedMemberId: null,
      selectedMemberId: null,
      confidence: null,
      facesCount: 0,
      error: ''
    })
  }

  queue.value = [...tasks]
}

function clearQueue(): void {
  queue.value = []
  bulkMemberId.value = null
  resetMessages()
}

function resolveLocalMemberId(rawMemberId: string | number): number | null {
  const parsed = Number(rawMemberId)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  if (memberStore.membersById.has(parsed)) return parsed

  const decoded = fromServerMemberId(parsed)
  if (memberStore.membersById.has(decoded)) return decoded

  return null
}

async function checkServer(): Promise<void> {
  const started = performance.now()
  try {
    await healthCheck()
    serverStatus.value = 'online'
    serverLatency.value = Math.round(performance.now() - started)
  } catch {
    serverStatus.value = 'offline'
    serverLatency.value = null
  }
}

async function runRecognition(task: PhotoTask): Promise<void> {
  task.error = ''
  task.confidence = null
  task.facesCount = 0

  try {
    const response = await recognizeFace({ image: task.dataUrl, threshold: threshold.value })
    task.facesCount = Number(response.faces_count || 0)

    if (!response.success || !response.results?.length) {
      task.status = 'manual'
      task.error = response.error || 'Лицо не распознано автоматически'
      return
    }

    const sorted = [...response.results].sort((a, b) => b.confidence - a.confidence)
    const candidate = sorted.find((item) => resolveLocalMemberId(item.member_id) !== null) || sorted[0]
    const localMemberId = resolveLocalMemberId(candidate.member_id)

    task.confidence = candidate.confidence
    task.recognizedMemberId = localMemberId

    if (!localMemberId) {
      task.status = 'manual'
      task.error = 'Распознанный ID отсутствует в локальной базе'
      return
    }

    task.selectedMemberId = localMemberId
    task.status = 'recognized'
  } catch (reason) {
    task.status = 'failed'
    task.error = (reason as Error).message || 'Ошибка распознавания'
  }
}

async function recognizeAll(): Promise<void> {
  if (!queue.value.length) return
  resetMessages()
  recognitionBusy.value = true

  let processed = 0
  try {
    for (const task of queue.value) {
      await runRecognition(task)
      processed += 1
    }
    info.value = `Автораспознавание завершено: обработано ${processed} фото.`
  } finally {
    recognitionBusy.value = false
  }
}

function applyBulkMember(): void {
  if (!bulkMemberId.value) return
  for (const task of unresolvedTasks.value) {
    task.selectedMemberId = bulkMemberId.value
    task.status = task.status === 'pending' ? 'manual' : task.status
  }
}

async function saveAssignments(): Promise<void> {
  if (!queue.value.length) return
  resetMessages()
  saveBusy.value = true

  let saved = 0
  let duplicates = 0
  let skipped = 0

  try {
    for (const task of queue.value) {
      if (!task.selectedMemberId) {
        skipped += 1
        continue
      }

      const result = await memberStore.addPhotoToMember(task.selectedMemberId, task.dataUrl, {
        isProfilePhoto: false,
        description: `AI импорт: ${task.fileName}`
      })

      if (result === 'saved') {
        task.status = 'saved'
        saved += 1
      } else {
        task.status = 'duplicate'
        duplicates += 1
      }
    }

    info.value = `Сохранение завершено. Добавлено: ${saved}, дубликаты: ${duplicates}, без назначения: ${skipped}.`
  } finally {
    saveBusy.value = false
  }
}

async function runFaceSync(): Promise<void> {
  resetMessages()
  syncBusy.value = true
  try {
    const report = await syncProfileFaces(appStore.settings.deviceId)
    await addBackupAudit('face_sync', JSON.stringify(report))
    info.value = `Синхронизация профилей: зарегистрировано ${report.registered}, пропущено ${report.skipped}, ошибок ${report.failed}.`
  } catch (reason) {
    error.value = `Не удалось синхронизировать профили: ${(reason as Error).message}`
  } finally {
    syncBusy.value = false
  }
}

function statusLabel(status: PhotoTask['status']): string {
  switch (status) {
    case 'pending':
      return 'Ожидает'
    case 'recognized':
      return 'Распознано'
    case 'manual':
      return 'Нужно подтверждение'
    case 'failed':
      return 'Ошибка AI'
    case 'saved':
      return 'Сохранено'
    case 'duplicate':
      return 'Дубликат'
    default:
      return status
  }
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        title="Фото + AI"
        subtitle="Пакетная загрузка, авто-распознавание и ручное закрепление фотографий"
      />

      <article class="app-card ai-toolbar-card">
        <div class="ai-toolbar">
          <div class="btn-row">
            <button class="btn-action primary" @click="openPicker">Загрузить фото (до 20)</button>
            <button class="btn-action" @click="checkServer">Проверить сервер</button>
            <button class="btn-action" :disabled="syncBusy" @click="runFaceSync">
              {{ syncBusy ? 'Синхронизация...' : 'Синхронизация профилей' }}
            </button>
          </div>

          <div class="chip-row">
            <span class="chip" :class="serverStatus === 'online' ? 'success' : serverStatus === 'offline' ? 'error' : ''">
              Сервер: {{ serverStatus === 'online' ? 'онлайн' : serverStatus === 'offline' ? 'офлайн' : 'не проверен' }}
            </span>
            <span v-if="serverLatency !== null" class="chip">Latency: {{ serverLatency }}ms</span>
          </div>
        </div>

        <div class="second-row">
          <div class="field threshold-field">
            <label>Порог AI (0.3 - 0.9)</label>
            <input v-model.number="threshold" type="number" min="0.3" max="0.9" step="0.05" />
          </div>

          <div class="btn-row">
            <button class="btn-action" :disabled="recognitionBusy || !queue.length" @click="recognizeAll">
              {{ recognitionBusy ? 'Распознавание...' : 'Автораспознавание' }}
            </button>
            <button class="btn-action" :disabled="saveBusy || !queue.length" @click="saveAssignments">
              {{ saveBusy ? 'Сохранение...' : 'Сохранить назначения' }}
            </button>
            <button class="btn-action danger" :disabled="!queue.length" @click="clearQueue">Очистить</button>
          </div>
        </div>

        <p v-if="info" class="status-line">{{ info }}</p>
        <p v-if="error" class="error">{{ error }}</p>

        <input
          ref="pickInput"
          type="file"
          accept="image/*"
          multiple
          style="display: none"
          @change="onFilesPicked"
        />
      </article>

      <article class="app-card assignment-card" v-if="queue.length">
        <div class="bulk-row">
          <div class="field bulk-field">
            <label>Массово назначить нераспознанные фото</label>
            <select v-model="bulkMemberId">
              <option :value="null">Выберите члена семьи</option>
              <option v-for="member in memberOptions" :key="member.id" :value="member.id">
                {{ member.firstName }} {{ member.lastName }}
              </option>
            </select>
          </div>
          <button class="btn-action" @click="applyBulkMember" :disabled="!bulkMemberId">Применить</button>
        </div>

        <section v-for="group in recognizedGroups" :key="group.memberId" class="group-block">
          <h2>
            {{ group.member ? `${group.member.firstName} ${group.member.lastName}` : `ID ${group.memberId}` }}
            <span class="chip">{{ group.tasks.length }} фото</span>
          </h2>
          <div class="photo-grid">
            <article v-for="task in group.tasks" :key="task.id" class="photo-card">
              <img :src="task.dataUrl" :alt="task.fileName" />
              <div class="photo-meta">
                <strong>{{ task.fileName }}</strong>
                <span class="chip">{{ statusLabel(task.status) }}</span>
                <small v-if="task.confidence !== null">Confidence: {{ task.confidence.toFixed(3) }}</small>
                <small v-if="task.error" class="error">{{ task.error }}</small>
              </div>
            </article>
          </div>
        </section>

        <section class="group-block" v-if="unresolvedTasks.length">
          <h2>
            Требуют назначения
            <span class="chip warn">{{ unresolvedTasks.length }} фото</span>
          </h2>
          <div class="photo-grid">
            <article v-for="task in unresolvedTasks" :key="task.id" class="photo-card">
              <img :src="task.dataUrl" :alt="task.fileName" />
              <div class="photo-meta">
                <strong>{{ task.fileName }}</strong>
                <span class="chip warn">{{ statusLabel(task.status) }}</span>
                <small v-if="task.error" class="error">{{ task.error }}</small>
                <div class="field">
                  <label>Назначить</label>
                  <select v-model="task.selectedMemberId">
                    <option :value="null">Выберите человека</option>
                    <option v-for="member in memberOptions" :key="member.id" :value="member.id">
                      {{ member.firstName }} {{ member.lastName }}
                    </option>
                  </select>
                </div>
              </div>
            </article>
          </div>
        </section>
      </article>

      <article class="app-card" v-else>
        <div class="empty-state">Загрузите фотографии, чтобы запустить AI-распознавание.</div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.ai-toolbar-card,
.assignment-card {
  padding: 16px;
}

.ai-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}

.chip-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.second-row {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}

.threshold-field {
  max-width: 220px;
}

.bulk-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.bulk-field {
  min-width: 260px;
  max-width: 420px;
}

.group-block + .group-block {
  margin-top: 16px;
}

.group-block h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 1rem;
}

.photo-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.photo-card {
  border: 1px solid var(--color-glass-border);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
}

.photo-card img {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}

.photo-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
}

.photo-meta strong {
  font-size: 0.86rem;
  word-break: break-word;
}

.photo-meta small {
  color: var(--color-text-secondary);
}

.error {
  color: var(--color-error);
  font-size: 0.82rem;
}
</style>
