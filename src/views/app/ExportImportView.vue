<script setup lang="ts">
import { reactive, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { useMemberStore } from '@/stores/memberStore'
import { addBackupAudit } from '@/db/repositories'
import { generatePdf, buildPdfDownloadUrl } from '@/services/api'
import { exportMembersToCsv, exportMembersToJson, importMembersFromJsonText } from '@/services/memberData'
import { downloadBlob, downloadText, openLinkInNewTab } from '@/utils/download'

const memberStore = useMemberStore()
const importInput = ref<HTMLInputElement | null>(null)

const importMode = ref<'merge' | 'replace'>('merge')
const importing = ref(false)
const pdfBusy = ref(false)
const pdfProgress = ref(0)
const dragOver = ref(false)
const status = ref('')
const error = ref('')

const pdfSettings = reactive({
  format: 'A4_LANDSCAPE',
  use_drive: true,
  show_photos: true,
  show_dates: true,
  show_patronymic: true,
  title: 'Семейное древо',
  photo_quality: 'medium'
})

function clearMessages(): void {
  status.value = ''
  error.value = ''
}

// Fake progress ticker — плавно движется до ~90%, финальный скачок при завершении
let _progressTimer: ReturnType<typeof setInterval> | null = null

function startFakeProgress(): void {
  pdfProgress.value = 0
  _progressTimer = setInterval(() => {
    if (pdfProgress.value < 88) {
      pdfProgress.value += Math.random() * 4 + 1
    }
  }, 400)
}

function finishProgress(): void {
  if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null }
  pdfProgress.value = 100
  setTimeout(() => { pdfProgress.value = 0 }, 800)
}

async function ensureMembers(): Promise<void> {
  if (!memberStore.members.length) {
    await memberStore.refresh()
  }
}

async function exportJsonFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  const content = exportMembersToJson(memberStore.members)
  const fileName = `familyone_members_${new Date().toISOString().slice(0, 10)}.json`
  downloadText(content, fileName, 'application/json;charset=utf-8')
  await addBackupAudit('local_export', `json:${memberStore.members.length}`)
  status.value = 'JSON экспорт готов.'
}

async function exportCsvFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  const content = exportMembersToCsv(memberStore.members)
  const fileName = `familyone_members_${new Date().toISOString().slice(0, 10)}.csv`
  downloadText(content, fileName, 'text/csv;charset=utf-8')
  await addBackupAudit('local_export', `csv:${memberStore.members.length}`)
  status.value = 'CSV экспорт готов.'
}

function base64ToBlob(base64: string): Blob {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new Blob([bytes], { type: 'application/pdf' })
}

async function exportPdfFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  if (!memberStore.members.length) {
    error.value = 'Нет данных для PDF экспорта.'
    return
  }

  pdfBusy.value = true
  startFakeProgress()
  try {
    const membersForPdf = memberStore.members.map((member) => ({
      ...member,
      photoBase64: member.photoUri || ''
    }))

    const response = await generatePdf({
      members: membersForPdf,
      format: pdfSettings.format,
      use_drive: pdfSettings.use_drive,
      show_photos: pdfSettings.show_photos,
      show_dates: pdfSettings.show_dates,
      show_patronymic: pdfSettings.show_patronymic,
      title: pdfSettings.title,
      photo_quality: pdfSettings.photo_quality
    })

    if (!response.success) {
      throw new Error(response.error || 'PDF генерация завершилась с ошибкой')
    }

    if (response.storage === 'google_drive' && response.drive_id) {
      const url = buildPdfDownloadUrl(response.drive_id)
      openLinkInNewTab(url)
      status.value = 'PDF сгенерирован на сервере. Открыта ссылка на скачивание.'
      await addBackupAudit('local_export', `pdf:drive:${response.drive_id}`)
      return
    }

    if (!response.pdf_base64) {
      throw new Error('PDF не вернулся от сервера')
    }

    const fileName = response.filename || `family_tree_${Date.now()}.pdf`
    const pdfBlob = base64ToBlob(response.pdf_base64)
    downloadBlob(pdfBlob, fileName)
    await addBackupAudit('local_export', `pdf:base64:${pdfBlob.size}`)
    status.value = 'PDF экспорт завершен.'
  } catch (reason) {
    error.value = (reason as Error).message
  } finally {
    finishProgress()
    pdfBusy.value = false
  }
}

function openImportPicker(): void {
  importInput.value?.click()
}

async function processImportFile(file: File): Promise<void> {
  clearMessages()
  if (!file.name.endsWith('.json') && file.type !== 'application/json') {
    error.value = 'Поддерживается только JSON файл.'
    return
  }
  importing.value = true
  try {
    const content = await file.text()
    const report = await importMembersFromJsonText(content, importMode.value)
    await memberStore.refresh()
    const action = importMode.value === 'replace' ? 'local_import_replace' : 'local_import_merge'
    await addBackupAudit(action, JSON.stringify(report))
    status.value = `Импорт завершен. Добавлено: ${report.inserted}, пропущено: ${report.skipped}, связей обновлено: ${report.relationsUpdated}.`
  } catch (reason) {
    error.value = `Ошибка импорта: ${(reason as Error).message}`
  } finally {
    importing.value = false
  }
}

async function onImportPicked(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  await processImportFile(file)
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
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  await processImportFile(file)
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="import_export"
        title="Экспорт и импорт"
        subtitle="JSON, CSV, PDF через backend и импорт с режимами Merge/Replace"
      />

      <!-- Export section -->
      <article class="app-card block">
        <h2 class="block-title with-icon">
          <AppIcon name="upload_file" :size="20" />
          Экспорт данных
        </h2>
        <div class="export-formats">
          <button class="format-card" @click="exportJsonFile">
            <AppIcon name="list_alt" :size="30" class="format-icon" />
            <span class="format-name">JSON</span>
            <small>Полные данные</small>
          </button>
          <button class="format-card" @click="exportCsvFile">
            <AppIcon name="bar_chart" :size="30" class="format-icon" />
            <span class="format-name">CSV</span>
            <small>Таблица</small>
          </button>
        </div>

        <div class="section-divider"></div>

        <div class="pdf-box">
          <h3 class="with-icon">
            <AppIcon name="description" :size="19" />
            PDF через backend
          </h3>
          <div class="form-grid">
            <div class="field">
              <label>Формат</label>
              <select v-model="pdfSettings.format">
                <option value="A4_LANDSCAPE">A4 Landscape</option>
                <option value="A3_LANDSCAPE">A3 Landscape</option>
                <option value="A4">A4 Portrait</option>
                <option value="A3">A3 Portrait</option>
              </select>
            </div>
            <div class="field">
              <label>Качество фото</label>
              <select v-model="pdfSettings.photo_quality">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>

            <div class="field full-width">
              <label>Заголовок PDF</label>
              <input v-model="pdfSettings.title" type="text" />
            </div>
          </div>

          <div class="toggle-row">
            <label class="toggle-switch">
              <input v-model="pdfSettings.use_drive" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Google Drive</span>
            </label>
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_photos" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Фото</span>
            </label>
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_dates" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Даты</span>
            </label>
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_patronymic" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Отчество</span>
            </label>
          </div>

          <div class="btn-row">
            <button class="btn-action primary" :disabled="pdfBusy" @click="exportPdfFile">
              <AppIcon :name="pdfBusy ? 'hourglass_top' : 'description'" :size="18" />
              {{ pdfBusy ? 'Генерация PDF...' : 'Экспорт PDF' }}
            </button>
          </div>

          <Transition name="fade-progress">
            <div v-if="pdfBusy || pdfProgress > 0" class="pdf-progress-wrap">
              <div class="progress-bar">
                <div
                  class="progress-bar-fill"
                  :class="{ 'progress-pulse': pdfBusy && pdfProgress < 95 }"
                  :style="{ width: Math.min(pdfProgress, 100) + '%' }"
                />
              </div>
              <span class="pdf-progress-label">
                {{ pdfProgress >= 100 ? 'Готово!' : `${Math.round(pdfProgress)}%` }}
              </span>
            </div>
          </Transition>
        </div>
      </article>

      <!-- Import section -->
      <article class="app-card block">
        <h2 class="block-title with-icon">
          <AppIcon name="download" :size="20" />
          Импорт JSON
        </h2>

        <div class="import-row">
          <div class="field mode-field">
            <label>Режим импорта</label>
            <select v-model="importMode">
              <option value="merge">Merge (по умолчанию)</option>
              <option value="replace">Replace (полная замена)</option>
            </select>
          </div>
        </div>

        <div
          class="drop-zone"
          :class="{ active: dragOver || importing }"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
          @click="openImportPicker"
        >
          <AppIcon
            :name="importing ? 'hourglass_top' : 'upload_file'"
            :size="40"
            class="drop-zone-icon"
            :class="{ 'spin-slow': importing }"
          />
          <p class="drop-zone-label">
            <template v-if="importing">Импорт...</template>
            <template v-else>
              Перетащите JSON файл сюда
              <span class="drop-zone-or">или нажмите для выбора</span>
            </template>
          </p>
        </div>

        <input
          ref="importInput"
          type="file"
          accept="application/json,.json"
          style="display: none"
          @change="onImportPicked"
        />
      </article>

      <!-- Status -->
      <article class="app-card block" v-if="status || error">
        <p v-if="status" class="status-success with-icon">
          <AppIcon name="check_circle" :size="18" />
          {{ status }}
        </p>
        <p v-if="error" class="error-msg with-icon">
          <AppIcon name="error" :size="18" />
          {{ error }}
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.block {
  padding: 20px;
}

.block + .block {
  margin-top: 14px;
}

.block-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 16px;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* Format cards */
.export-formats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.format-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 28px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  transition: all var(--transition-normal);
  font-family: var(--font-sans);
  min-width: 120px;
}

.format-card:hover {
  border-color: rgba(124, 92, 252, 0.4);
  background: rgba(124, 92, 252, 0.06);
  transform: translateY(-3px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.format-icon {
  font-size: 2rem;
}

.format-name {
  font-weight: 700;
  font-size: 1rem;
}

.format-card small {
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

/* PDF box */
.pdf-box {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pdf-box h3 {
  font-size: 1rem;
  font-weight: 600;
}

.toggle-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.full-width {
  grid-column: 1 / -1;
}

/* Import row */
.import-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.mode-field {
  max-width: 360px;
  flex: 1;
}

.status-success {
  color: var(--color-success);
  font-size: 0.9rem;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.9rem;
}

/* PDF progress */
.pdf-progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.pdf-progress-label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  min-width: 36px;
  text-align: right;
  white-space: nowrap;
}

@keyframes progress-pulse-anim {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.progress-pulse {
  animation: progress-pulse-anim 1.2s ease-in-out infinite;
}

.fade-progress-enter-active,
.fade-progress-leave-active {
  transition: opacity 0.3s;
}
.fade-progress-enter-from,
.fade-progress-leave-to {
  opacity: 0;
}

/* Drop zone customization */
.drop-zone-label {
  margin: 0;
  font-size: 0.95rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.drop-zone-or {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

@keyframes spin-slow-anim {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spin-slow {
  animation: spin-slow-anim 1.8s linear infinite;
  display: inline-block;
}
</style>
