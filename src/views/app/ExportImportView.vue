<script setup lang="ts">
import { reactive, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
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
  try {
    const membersForPdf = memberStore.members.map((member) => ({
      ...member,
      // Backend draw_member_card ожидает photoBase64; в web профиле хранится photoUri (data URL).
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
    pdfBusy.value = false
  }
}

function openImportPicker(): void {
  importInput.value?.click()
}

async function onImportPicked(event: Event): Promise<void> {
  clearMessages()
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return

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
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="Экспорт и импорт" subtitle="JSON, CSV, PDF через backend и импорт с режимами Merge/Replace" />

      <article class="app-card block">
        <h2>Экспорт</h2>
        <div class="btn-row">
          <button class="btn-action" @click="exportJsonFile">Экспорт JSON</button>
          <button class="btn-action" @click="exportCsvFile">Экспорт CSV</button>
        </div>

        <div class="pdf-box">
          <h3>PDF через backend</h3>
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
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>

            <div class="field full-width">
              <label>Заголовок PDF</label>
              <input v-model="pdfSettings.title" type="text" />
            </div>
          </div>

          <div class="btn-row check-row">
            <label class="switch"><input v-model="pdfSettings.use_drive" type="checkbox" /> Google Drive</label>
            <label class="switch"><input v-model="pdfSettings.show_photos" type="checkbox" /> Фото</label>
            <label class="switch"><input v-model="pdfSettings.show_dates" type="checkbox" /> Даты</label>
            <label class="switch"
              ><input v-model="pdfSettings.show_patronymic" type="checkbox" /> Отчество</label
            >
          </div>

          <div class="btn-row">
            <button class="btn-action primary" :disabled="pdfBusy" @click="exportPdfFile">
              {{ pdfBusy ? 'Генерация PDF...' : 'Экспорт PDF' }}
            </button>
          </div>
        </div>
      </article>

      <article class="app-card block">
        <h2>Импорт JSON</h2>
        <div class="field mode-field">
          <label>Режим импорта</label>
          <select v-model="importMode">
            <option value="merge">Merge (по умолчанию)</option>
            <option value="replace">Replace (полная замена)</option>
          </select>
        </div>
        <div class="btn-row">
          <button class="btn-action" :disabled="importing" @click="openImportPicker">
            {{ importing ? 'Импорт...' : 'Выбрать JSON файл' }}
          </button>
        </div>
        <input
          ref="importInput"
          type="file"
          accept="application/json,.json"
          style="display: none"
          @change="onImportPicked"
        />
      </article>

      <article class="app-card block" v-if="status || error">
        <p v-if="status" class="status-line">{{ status }}</p>
        <p v-if="error" class="error">{{ error }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.block {
  padding: 16px;
}

.block + .block {
  margin-top: 14px;
}

h2 {
  margin-bottom: 12px;
}

.pdf-box {
  margin-top: 14px;
  border: 1px dashed var(--color-glass-border);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pdf-box h3 {
  font-size: 0.95rem;
}

.check-row {
  gap: 14px;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.86rem;
  color: var(--color-text-secondary);
}

.full-width {
  grid-column: 1 / -1;
}

.mode-field {
  max-width: 360px;
  margin-bottom: 12px;
}

.error {
  color: var(--color-error);
}
</style>
