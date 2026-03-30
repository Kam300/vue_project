<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { useMemberStore } from '@/stores/memberStore'
import { useAppStore } from '@/stores/appStore'
import { addBackupAudit } from '@/db/repositories'
import { healthCheck, recognizeFace } from '@/services/api'
import { resolveLocalMemberIdFromServer, syncProfileFaces } from '@/services/familySync'
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
const faceRecognitionAvailable = ref(true)
const faceRecognitionError = ref('')
const bulkMemberId = ref<number | null>(null)
const dragOver = ref(false)
const recognitionProgress = ref(0)

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

async function processFiles(files: File[]): Promise<void> {
  resetMessages()
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

async function onFilesPicked(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  await processFiles(files)
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave(): void {
  dragOver.value = false
}

async function onDrop(e: DragEvent): Promise<void> {
  e.preventDefault()
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'))
  await processFiles(files)
}

function clearQueue(): void {
  queue.value = []
  bulkMemberId.value = null
  recognitionProgress.value = 0
  resetMessages()
}

function resolveLocalMemberId(rawMemberId: string | number): number | null {
  return resolveLocalMemberIdFromServer(
    rawMemberId,
    memberStore.members,
    appStore.settings.deviceId
  )
}

async function checkServer(): Promise<void> {
  const started = performance.now()
  try {
    const response = await healthCheck()
    serverStatus.value = 'online'
    serverLatency.value = Math.round(performance.now() - started)
    faceRecognitionAvailable.value = Boolean(response.face_recognition)
    faceRecognitionError.value = response.face_recognition
      ? ''
      : (response.face_recognition_error || 'AI-распознавание отключено на этом сервере')
  } catch {
    serverStatus.value = 'offline'
    serverLatency.value = null
    faceRecognitionAvailable.value = false
    faceRecognitionError.value = 'Сервер AI недоступен'
  }
}

async function runRecognition(task: PhotoTask): Promise<void> {
  task.error = ''
  task.confidence = null
  task.facesCount = 0

  try {
    const response = await recognizeFace({
      image: task.dataUrl,
      threshold: threshold.value,
      device_id: appStore.settings.deviceId || undefined
    })
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
  if (!faceRecognitionAvailable.value) {
    error.value = faceRecognitionError.value || 'AI-распознавание недоступно на этом сервере'
    return
  }
  resetMessages()
  recognitionBusy.value = true
  recognitionProgress.value = 0

  let processed = 0
  try {
    for (const task of queue.value) {
      await runRecognition(task)
      processed += 1
      recognitionProgress.value = Math.round((processed / queue.value.length) * 100)
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
  if (!faceRecognitionAvailable.value) {
    error.value = faceRecognitionError.value || 'AI-распознавание недоступно на этом сервере'
    return
  }
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

function statusChipClass(status: PhotoTask['status']): string {
  switch (status) {
    case 'recognized':
    case 'saved':
      return 'success'
    case 'manual':
    case 'duplicate':
      return 'warn'
    case 'failed':
      return 'error'
    default:
      return ''
  }
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="smart_toy"
        title="Фото + AI"
        subtitle="Пакетная загрузка, авто-распознавание и ручное закрепление фотографий"
      />

      <article class="app-card ai-toolbar-card">
        <!-- Drop zone -->
        <div
          class="drop-zone"
          :class="{ active: dragOver }"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
          @click="openPicker"
        >
          <span class="drop-zone-icon">
            <AppIcon name="photo_camera" :size="34" />
          </span>
          <p><strong>Перетащите фото</strong> сюда или <strong>нажмите</strong> для выбора</p>
          <small>До 20 фотографий за раз</small>
        </div>

        <div class="toolbar-row">
          <div class="chip-row">
            <span class="chip" :class="serverStatus === 'online' ? 'success' : serverStatus === 'offline' ? 'error' : ''">
              {{ serverStatus === 'online' ? 'Онлайн' : serverStatus === 'offline' ? 'Офлайн' : 'Не проверен' }}
            </span>
            <span v-if="serverLatency !== null" class="chip">
              <AppIcon name="bolt" :size="16" />
              {{ serverLatency }}ms
            </span>
          </div>
          <div class="btn-row">
            <button class="btn-action" @click="checkServer">
              <AppIcon name="refresh" :size="16" />
              Проверить
            </button>
            <button class="btn-action" :disabled="syncBusy || !faceRecognitionAvailable" @click="runFaceSync">
              <AppIcon :name="syncBusy ? 'hourglass_top' : 'sync'" :size="16" />
              {{ syncBusy ? 'Синхронизация...' : 'Синхр. профили' }}
            </button>
          </div>
        </div>

        <p v-if="serverStatus === 'online' && !faceRecognitionAvailable" class="warn-msg" style="margin-top: 10px">
          {{ faceRecognitionError }}
        </p>

        <div class="section-divider"></div>

        <div class="controls-row">
          <div class="field threshold-field">
            <label>Порог AI (0.3 — 0.9)</label>
            <input v-model.number="threshold" type="number" min="0.3" max="0.9" step="0.05" />
          </div>

          <div class="btn-row">
            <button class="btn-action primary" :disabled="recognitionBusy || !queue.length || !faceRecognitionAvailable" @click="recognizeAll">
              <AppIcon :name="recognitionBusy ? 'hourglass_top' : 'psychology'" :size="16" />
              {{ recognitionBusy ? 'Распознавание...' : 'Автораспознавание' }}
            </button>
            <button class="btn-action" :disabled="saveBusy || !queue.length" @click="saveAssignments">
              <AppIcon :name="saveBusy ? 'hourglass_top' : 'save'" :size="16" />
              {{ saveBusy ? 'Сохранение...' : 'Сохранить' }}
            </button>
            <button class="btn-action danger" :disabled="!queue.length" @click="clearQueue">
              <AppIcon name="delete" :size="16" />
              Очистить
            </button>
          </div>
        </div>

        <!-- Progress bar -->
        <div v-if="recognitionBusy" class="progress-bar" style="margin-top: 12px">
          <div class="progress-bar-fill" :style="{ width: recognitionProgress + '%' }"></div>
        </div>

        <p v-if="info" class="status-line with-icon" style="margin-top: 10px">
          <AppIcon name="check_circle" :size="17" />
          {{ info }}
        </p>
        <p v-if="error" class="error-msg" style="margin-top: 8px">{{ error }}</p>

        <input
          ref="pickInput"
          type="file"
          accept="image/*"
          multiple
          style="display: none"
          @change="onFilesPicked"
        />
      </article>

      <!-- Assignment area -->
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
            <span class="chip success">{{ group.tasks.length }} фото</span>
          </h2>
          <div class="photo-grid">
            <article v-for="task in group.tasks" :key="task.id" class="photo-card">
              <img :src="task.dataUrl" :alt="task.fileName" />
              <div class="photo-meta">
                <strong>{{ task.fileName }}</strong>
                <span class="chip" :class="statusChipClass(task.status)">{{ statusLabel(task.status) }}</span>
                <div v-if="task.confidence !== null" class="confidence-wrap">
                  <div class="progress-bar">
                    <div class="progress-bar-fill" :style="{ width: (task.confidence * 100) + '%' }"></div>
                  </div>
                  <small>{{ (task.confidence * 100).toFixed(1) }}%</small>
                </div>
                <small v-if="task.error" class="error-msg">{{ task.error }}</small>
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
                <span class="chip" :class="statusChipClass(task.status)">{{ statusLabel(task.status) }}</span>
                <small v-if="task.error" class="error-msg">{{ task.error }}</small>
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
        <div class="empty-state">
          <span class="empty-state-icon">
            <AppIcon name="imagesmode" :size="32" />
          </span>
          <p>Загрузите фотографии, чтобы запустить AI-распознавание.</p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.ai-toolbar-card,
.assignment-card {
  padding: 20px;
}

.assignment-card {
  margin-top: 16px;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.warn-msg {
  color: #fbbf24;
  font-size: 0.92rem;
}

.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.controls-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
}

.threshold-field {
  max-width: 200px;
}

.confidence-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confidence-wrap .progress-bar {
  flex: 1;
  height: 4px;
}

.confidence-wrap small {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-secondary);
  white-space: nowrap;
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
  margin-top: 20px;
}

.group-block h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 1.05rem;
}

.photo-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.photo-card {
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--input-bg);
  transition: all var(--transition-normal);
}

.photo-card:hover {
  border-color: rgba(124, 92, 252, 0.25);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
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
  padding: 12px;
}

.photo-meta strong {
  font-size: 0.84rem;
  word-break: break-word;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.8rem;
}
</style>
