<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useAppStore } from '@/stores/appStore'
import { useMemberStore } from '@/stores/memberStore'
import { addBackupAudit, getBackupAudit } from '@/db/repositories'
import { backupDelete, backupDownload, backupMeta, backupUpload } from '@/services/api'
import {
  ensureGoogleIdentityLoaded,
  getGoogleClientId,
  signInWithGooglePopup,
  signOutGoogle
} from '@/services/googleIdentity'
import { createBackupArchive, restoreBackupArchive } from '@/services/backupArchive'
import { syncProfileFaces } from '@/services/familySync'
import { downloadBlob } from '@/utils/download'
import type { BackupAuditRecord } from '@/types/models'
import type { BackupMetaResponse } from '@/types/api'

const appStore = useAppStore()
const memberStore = useMemberStore()

const backupInput = ref<HTMLInputElement | null>(null)
const restoreInput = ref<HTMLInputElement | null>(null)

const audit = ref<BackupAuditRecord[]>([])
const remoteMeta = ref<BackupMetaResponse | null>(null)

const status = ref('')
const error = ref('')

const authBusy = ref(false)
const metaBusy = ref(false)
const buildBusy = ref(false)
const uploadBusy = ref(false)
const downloadBusy = ref(false)
const deleteBusy = ref(false)
const restoreBusy = ref(false)

const hasGoogleClientId = computed(() => Boolean(getGoogleClientId()))
const isAuthorized = computed(() => Boolean(appStore.googleIdToken))
const canUseServerBackup = computed(() => Boolean(appStore.settings.deviceId))
const autoSyncBusy = ref(false)
let autoSyncTimer = 0

function clearMessages(): void {
  status.value = ''
  error.value = ''
}

function applyRemoteError(prefix: string, reason: unknown): void {
  const message = (reason as Error).message || 'Unknown error'
  const normalized = message.toLowerCase()
  const isAuthError =
    normalized.includes('invalid or expired google token') ||
    normalized.includes('missing bearer token') ||
    normalized.includes('x-familyone-device') ||
    normalized.includes('http 401') ||
    normalized.includes('unauthorized')

  if (isAuthError) {
    appStore.clearGoogleToken()
    remoteMeta.value = null
    error.value = `${prefix}: ${message}. Выполните вход через Google снова.`
    return
  }

  error.value = `${prefix}: ${message}`
}

async function reloadAudit(): Promise<void> {
  audit.value = await getBackupAudit()
}

async function initializeScreen(): Promise<void> {
  if (!memberStore.members.length) {
    await memberStore.refresh()
  }
  await reloadAudit()
  if (canUseServerBackup.value) {
    await fetchRemoteMeta({ silent: true })
  }
}

onMounted(() => {
  initializeScreen()
  if (canUseServerBackup.value) {
    autoSyncTimer = window.setInterval(() => {
      void refreshRemoteStatusSilently()
    }, 30000)
  }
})

onUnmounted(() => {
  if (autoSyncTimer) {
    window.clearInterval(autoSyncTimer)
  }
})

async function signInGoogle(): Promise<void> {
  clearMessages()
  if (!hasGoogleClientId.value) {
    status.value = 'Google OAuth не настроен. Используется device auth режим для серверного backup.'
    return
  }

  authBusy.value = true
  try {
    await ensureGoogleIdentityLoaded()
    const token = await signInWithGooglePopup()
    appStore.setGoogleToken(token, 'Google account')
    status.value = 'Google вход выполнен.'
    await fetchRemoteMeta()
  } catch (reason) {
    error.value = `Google вход не выполнен: ${(reason as Error).message || 'Unknown error'}`
  } finally {
    authBusy.value = false
  }
}

function signOut(): void {
  signOutGoogle(appStore.googleIdToken)
  appStore.clearGoogleToken()
  remoteMeta.value = null
  status.value = 'Google сессия очищена.'
}

function getBackupAuthContext(): { token: string; deviceId: string } {
  const deviceId = String(appStore.settings.deviceId || '').trim()
  if (!deviceId) {
    throw new Error('Device ID не инициализирован. Перезапустите приложение.')
  }
  return {
    token: appStore.googleIdToken || '',
    deviceId
  }
}

async function fetchRemoteMeta(options: { silent?: boolean } = {}): Promise<void> {
  if (!options.silent) {
    clearMessages()
  }

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    if (!options.silent) {
      error.value = (reason as Error).message
    }
    return
  }

  metaBusy.value = true
  try {
    remoteMeta.value = await backupMeta(auth.token, auth.deviceId)
    if (!options.silent) {
      status.value = remoteMeta.value.exists
        ? 'Метаданные серверного backup получены.'
        : 'Серверный backup не найден.'
    }
  } catch (reason) {
    if (!options.silent) {
      applyRemoteError('Не удалось получить метаданные', reason)
    }
  } finally {
    metaBusy.value = false
  }
}

async function refreshRemoteStatusSilently(): Promise<void> {
  if (!canUseServerBackup.value || metaBusy.value || autoSyncBusy.value) return
  autoSyncBusy.value = true
  try {
    await fetchRemoteMeta({ silent: true })
  } finally {
    autoSyncBusy.value = false
  }
}

function parseIsoMs(value?: string | null): number {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

function isRemoteRestoreAudit(details: string): boolean {
  if (!details) return false
  return details.includes('"source":"remote-download"') || details.includes('remote-download')
}

const lastRemoteRestoreAtMs = computed(() => {
  const latest = audit.value
    .filter((entry) => entry.action === 'backup_restore' && isRemoteRestoreAudit(entry.details))
    .map((entry) => Date.parse(entry.timestamp))
    .filter((value) => !Number.isNaN(value))
    .sort((a, b) => b - a)[0]
  return latest || 0
})

const remoteBackupUpdatedAtMs = computed(() =>
  parseIsoMs(remoteMeta.value?.updatedAtUtc || remoteMeta.value?.createdAtUtc || null)
)

const hasRemoteChanges = computed(
  () =>
    Boolean(remoteMeta.value?.exists) &&
    remoteBackupUpdatedAtMs.value > 0 &&
    remoteBackupUpdatedAtMs.value > lastRemoteRestoreAtMs.value
)

async function buildLocalBackup(): Promise<void> {
  clearMessages()
  buildBusy.value = true
  try {
    const result = await createBackupArchive()
    const fileName = `familyone_backup_${result.createdAtUtc.slice(0, 10)}.zip`
    downloadBlob(result.file, fileName)
    await addBackupAudit('local_export', JSON.stringify(result))
    await reloadAudit()
    status.value = `Локальный backup создан: ${result.membersCount} членов семьи, ${result.assetsCount} assets.`
  } catch (reason) {
    error.value = `Не удалось создать backup: ${(reason as Error).message}`
  } finally {
    buildBusy.value = false
  }
}

async function buildAndUploadRemote(): Promise<void> {
  clearMessages()

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  uploadBusy.value = true
  try {
    const backup = await createBackupArchive()
    const response = await backupUpload(auth.token, backup.file, auth.deviceId)
    remoteMeta.value = response
    await addBackupAudit('backup_upload', JSON.stringify({ upload: response, local: backup }))
    await reloadAudit()
    status.value = 'Серверный backup обновлён.'
  } catch (reason) {
    applyRemoteError('Не удалось загрузить backup', reason)
  } finally {
    uploadBusy.value = false
  }
}

function pickUploadFile(): void {
  backupInput.value?.click()
}

async function onUploadFile(event: Event): Promise<void> {
  clearMessages()
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  uploadBusy.value = true
  try {
    const response = await backupUpload(auth.token, file, auth.deviceId)
    remoteMeta.value = response
    await addBackupAudit('backup_upload', JSON.stringify({ uploadedFile: file.name, response }))
    await reloadAudit()
    status.value = 'ZIP backup загружен на сервер.'
  } catch (reason) {
    applyRemoteError('Ошибка загрузки ZIP', reason)
  } finally {
    uploadBusy.value = false
  }
}

async function downloadRemoteBackup(): Promise<void> {
  clearMessages()

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  downloadBusy.value = true
  try {
    const blob = await backupDownload(auth.token, auth.deviceId)
    const fileName = `familyone_backup_remote_${new Date().toISOString().slice(0, 10)}.zip`
    downloadBlob(blob, fileName)
    await addBackupAudit('backup_download', `remote:${blob.size}`)
    await reloadAudit()
    status.value = 'Серверный backup скачан.'
  } catch (reason) {
    applyRemoteError('Не удалось скачать backup', reason)
  } finally {
    downloadBusy.value = false
  }
}

function pickRestoreFile(): void {
  restoreInput.value?.click()
}

async function restoreFromBlob(source: Blob, sourceLabel: string): Promise<void> {
  restoreBusy.value = true
  try {
    const report = await restoreBackupArchive(source)
    await memberStore.refresh()
    const faceReport = await syncProfileFaces(appStore.settings.deviceId)
    await addBackupAudit(
      'backup_restore',
      JSON.stringify({ source: sourceLabel, restore: report, faceSync: faceReport })
    )
    await reloadAudit()
    status.value = `Восстановление завершено. Добавлено людей: ${report.membersInserted}, фото: ${report.photosAdded}, дубликатов: ${report.photosSkippedDuplicates}.`
  } catch (reason) {
    error.value = `Ошибка восстановления: ${(reason as Error).message}`
  } finally {
    restoreBusy.value = false
  }
}

async function onRestoreFile(event: Event): Promise<void> {
  clearMessages()
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return

  await restoreFromBlob(file, file.name)
}

async function restoreFromRemote(): Promise<void> {
  clearMessages()

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  downloadBusy.value = true
  try {
    const blob = await backupDownload(auth.token, auth.deviceId)
    await restoreFromBlob(blob, 'remote-download')
  } catch (reason) {
    applyRemoteError('Ошибка restore с сервера', reason)
  } finally {
    downloadBusy.value = false
  }
}

async function removeRemoteBackup(): Promise<void> {
  clearMessages()

  let auth: { token: string; deviceId: string }
  try {
    auth = getBackupAuthContext()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  if (!window.confirm('Удалить серверный backup?')) return

  deleteBusy.value = true
  try {
    const response = await backupDelete(auth.token, auth.deviceId)
    remoteMeta.value = null
    await addBackupAudit('backup_delete', JSON.stringify(response))
    await reloadAudit()
    status.value = response.deleted ? 'Серверный backup удалён.' : 'Серверный backup не найден.'
  } catch (reason) {
    applyRemoteError('Не удалось удалить backup', reason)
  } finally {
    deleteBusy.value = false
  }
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        title="Backup"
        subtitle="Локальный ZIP, серверный backup через Google OAuth и восстановление"
      />

      <article class="app-card block">
        <h2>Google OAuth</h2>
        <p class="status-line" v-if="!hasGoogleClientId">
          `VITE_GOOGLE_WEB_CLIENT_ID` не задан. Будет использован device auth режим.
        </p>

        <div class="btn-row">
          <button class="btn-action" @click="signInGoogle" :disabled="authBusy || !hasGoogleClientId">
            {{ authBusy ? 'Вход...' : isAuthorized ? 'Войти заново' : 'Войти через Google' }}
          </button>
          <button class="btn-action" @click="signOut" :disabled="!isAuthorized">Выйти</button>
          <button class="btn-action" @click="fetchRemoteMeta()" :disabled="!canUseServerBackup || metaBusy">
            {{ metaBusy ? 'Синхронизация...' : 'Синхронизировать статус' }}
          </button>
        </div>
      </article>

      <article class="app-card block">
        <h2>Локальный backup</h2>
        <div class="btn-row">
          <button class="btn-action" @click="buildLocalBackup" :disabled="buildBusy">
            {{ buildBusy ? 'Подготовка...' : 'Собрать и скачать ZIP' }}
          </button>
          <button class="btn-action" @click="pickRestoreFile" :disabled="restoreBusy">
            {{ restoreBusy ? 'Restore...' : 'Восстановить из ZIP' }}
          </button>
        </div>
      </article>

      <article class="app-card block">
        <h2>Серверный backup</h2>
        <p class="status-line" v-if="hasRemoteChanges">
          На сервере есть более новый backup. Нажмите «Синхронизировать из backup».
        </p>
        <div class="btn-row">
          <button class="btn-action primary" @click="buildAndUploadRemote" :disabled="!canUseServerBackup || uploadBusy">
            {{ uploadBusy ? 'Загрузка...' : 'Собрать и загрузить' }}
          </button>
          <button class="btn-action" @click="pickUploadFile" :disabled="!canUseServerBackup || uploadBusy">
            Загрузить ZIP файл
          </button>
          <button class="btn-action" @click="downloadRemoteBackup" :disabled="!canUseServerBackup || downloadBusy">
            {{ downloadBusy ? 'Скачивание...' : 'Скачать ZIP' }}
          </button>
          <button class="btn-action" @click="restoreFromRemote" :disabled="!canUseServerBackup || restoreBusy || downloadBusy">
            {{ restoreBusy ? 'Синхронизация...' : 'Синхронизировать из backup' }}
          </button>
          <button class="btn-action danger" @click="removeRemoteBackup" :disabled="!canUseServerBackup || deleteBusy">
            {{ deleteBusy ? 'Удаление...' : 'Удалить backup' }}
          </button>
        </div>

        <div class="meta-box" v-if="remoteMeta">
          <div class="meta-row"><strong>Exists:</strong> {{ remoteMeta.exists ? 'Да' : 'Нет' }}</div>
          <div class="meta-row" v-if="remoteMeta.createdAtUtc"><strong>Создан:</strong> {{ remoteMeta.createdAtUtc }}</div>
          <div class="meta-row" v-if="remoteMeta.updatedAtUtc"><strong>Обновлен:</strong> {{ remoteMeta.updatedAtUtc }}</div>
          <div class="meta-row" v-if="remoteMeta.sizeBytes"><strong>Размер:</strong> {{ remoteMeta.sizeBytes }} bytes</div>
          <div class="meta-row" v-if="remoteMeta.membersCount !== undefined">
            <strong>Людей:</strong> {{ remoteMeta.membersCount }}
          </div>
          <div class="meta-row" v-if="remoteMeta.memberPhotosCount !== undefined">
            <strong>Фото:</strong> {{ remoteMeta.memberPhotosCount }}
          </div>
          <div class="meta-row" v-if="remoteMeta.assetsCount !== undefined">
            <strong>Assets:</strong> {{ remoteMeta.assetsCount }}
          </div>
        </div>
      </article>

      <article class="app-card block">
        <h2>Журнал backup</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Действие</th>
                <th>Детали</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in audit" :key="entry.id">
                <td>{{ new Date(entry.timestamp).toLocaleString('ru-RU') }}</td>
                <td>{{ entry.action }}</td>
                <td class="details">{{ entry.details }}</td>
              </tr>
              <tr v-if="!audit.length">
                <td colspan="3" class="status-line">Журнал пока пуст.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="app-card block" v-if="status || error">
        <p v-if="status" class="status-line">{{ status }}</p>
        <p v-if="error" class="error">{{ error }}</p>
      </article>

      <input ref="backupInput" type="file" accept="application/zip,.zip" style="display: none" @change="onUploadFile" />
      <input
        ref="restoreInput"
        type="file"
        accept="application/zip,.zip"
        style="display: none"
        @change="onRestoreFile"
      />
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

.meta-box {
  margin-top: 14px;
  border: 1px dashed var(--color-glass-border);
  border-radius: 12px;
  padding: 12px;
  display: grid;
  gap: 6px;
}

.meta-row {
  font-size: 0.88rem;
}

.details {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error {
  color: var(--color-error);
}
</style>






