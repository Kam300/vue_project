<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import SyncProgress from '@/components/shared/SyncProgress.vue'
import YandexIdButton from '@/components/shared/YandexIdButton.vue'
import { useAppStore } from '@/stores/appStore'
import { useMemberStore } from '@/stores/memberStore'
import { addBackupAudit, getBackupAudit } from '@/db/repositories'
import { backupDelete, backupDownload, backupMeta, backupUpload } from '@/services/api'
import { createBackupArchive, restoreBackupArchive } from '@/services/backupArchive'
import { syncProfileFaces } from '@/services/familySync'
import { connectPortableIdentityAndSync } from '@/services/portableIdentitySync'
import { downloadBlob } from '@/utils/download'
import type { BackupMetaResponse } from '@/types/api'
import type { BackupAuditRecord } from '@/types/models'

const appStore = useAppStore()
const memberStore = useMemberStore()

const backupInput = ref<HTMLInputElement | null>(null)
const restoreInput = ref<HTMLInputElement | null>(null)

const audit = ref<BackupAuditRecord[]>([])
const remoteMeta = ref<BackupMetaResponse | null>(null)

const status = ref('')
const error = ref('')

const authBusy = ref<'yandex' | 'vk' | ''>('')
const authProgress = ref(0)
const authProgressLabel = ref('')
const metaBusy = ref(false)
const buildBusy = ref(false)
const uploadBusy = ref(false)
const downloadBusy = ref(false)
const deleteBusy = ref(false)
const restoreBusy = ref(false)
const autoSyncBusy = ref(false)
let autoSyncTimer = 0

const yandexConfigured = computed(() => Boolean(appStore.authProviders?.yandex?.configured))
const vkConfigured = computed(() => Boolean(appStore.authProviders?.vk?.configured))
const portableIdentity = computed(() => appStore.portableIdentity)
const canUseServerBackup = computed(() => Boolean(appStore.settings.deviceId))
const portableIdentitySummary = computed(() => {
  if (!portableIdentity.value) {
    return 'Сейчас работает локальная сессия. Чтобы восстанавливать backup на другом ПК, подключите Яндекс ID.'
  }

  const providerTitle = portableIdentity.value.provider === 'yandex' ? 'Яндекс ID подключен' : 'VK ID подключён'
  const name = portableIdentity.value.displayName || appStore.authUser?.displayName || ''
  return name ? `${providerTitle} — ${name}` : providerTitle
})

function clearMessages(): void {
  status.value = ''
  error.value = ''
}

function getBackupDeviceId(): string {
  const deviceId = String(appStore.settings.deviceId || '').trim()
  if (!deviceId) {
    throw new Error('Device ID не инициализирован. Перезапустите приложение.')
  }
  return deviceId
}

function applyRemoteError(prefix: string, reason: unknown): void {
  const message = (reason as Error).message || 'Unknown error'
  error.value = `${prefix}: ${message}`
}

async function reloadAudit(): Promise<void> {
  audit.value = await getBackupAudit()
}

async function fetchRemoteMeta(options: { silent?: boolean } = {}): Promise<void> {
  if (!options.silent) {
    clearMessages()
  }

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    if (!options.silent) {
      error.value = (reason as Error).message
    }
    return
  }

  metaBusy.value = true
  try {
    remoteMeta.value = await backupMeta('', deviceId)
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

async function initializeScreen(): Promise<void> {
  await Promise.all([
    memberStore.refresh(),
    reloadAudit(),
    canUseServerBackup.value ? fetchRemoteMeta({ silent: true }) : Promise.resolve()
  ])
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

onMounted(() => {
  void initializeScreen()
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

async function connectProvider(provider: 'yandex' | 'vk'): Promise<void> {
  clearMessages()
  authBusy.value = provider
  authProgress.value = 0
  authProgressLabel.value = 'Подготовка…'

  try {
    status.value = await connectPortableIdentityAndSync(provider, {
      onProgress(step) {
        authProgress.value = step.progress
        authProgressLabel.value = step.message
      },
      afterSync: async () => {
        await Promise.all([
          appStore.refreshAuthState(),
          reloadAudit(),
          canUseServerBackup.value ? fetchRemoteMeta({ silent: true }) : Promise.resolve()
        ])
      }
    })
  } catch (reason) {
    error.value = `Не удалось завершить вход: ${(reason as Error).message || 'unknown error'}`
  } finally {
    authBusy.value = ''
  }
}

async function refreshPortableState(): Promise<void> {
  clearMessages()
  try {
    await appStore.refreshAuthState()
    if (canUseServerBackup.value) {
      await fetchRemoteMeta({ silent: true })
    }
    status.value = 'Статус переносимой учётной записи обновлён.'
  } catch (reason) {
    error.value = `Не удалось обновить статус: ${(reason as Error).message || 'unknown error'}`
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

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  uploadBusy.value = true
  try {
    const backup = await createBackupArchive()
    const response = await backupUpload('', backup.file, deviceId)
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

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  uploadBusy.value = true
  try {
    const response = await backupUpload('', file, deviceId)
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

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  downloadBusy.value = true
  try {
    const blob = await backupDownload('', deviceId)
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
    let faceReport = { registered: 0, skipped: 0, failed: 0 }
    let faceSyncError = ''
    try {
      faceReport = await syncProfileFaces(appStore.settings.deviceId)
    } catch (reason) {
      faceSyncError = (reason as Error).message || 'unknown sync error'
    }

    await addBackupAudit(
      'backup_restore',
      JSON.stringify({ source: sourceLabel, restore: report, faceSync: faceReport, faceSyncError })
    )
    await reloadAudit()
    status.value = `Восстановление завершено. Добавлено людей: ${report.membersInserted}, фото: ${report.photosAdded}, дубликатов: ${report.photosSkippedDuplicates}.`
    if (faceSyncError) {
      error.value = `Восстановление выполнено, но синхронизация лиц не завершена: ${faceSyncError}`
    }
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

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  downloadBusy.value = true
  try {
    const blob = await backupDownload('', deviceId)
    await restoreFromBlob(blob, 'remote-download')
  } catch (reason) {
    applyRemoteError('Ошибка restore с сервера', reason)
  } finally {
    downloadBusy.value = false
  }
}

async function removeRemoteBackup(): Promise<void> {
  clearMessages()

  let deviceId = ''
  try {
    deviceId = getBackupDeviceId()
  } catch (reason) {
    error.value = (reason as Error).message
    return
  }

  if (!window.confirm('Удалить серверный backup?')) return

  deleteBusy.value = true
  try {
    const response = await backupDelete('', deviceId)
    remoteMeta.value = response.deleted ? { success: true, exists: false, schemaVersion: response.schemaVersion } : remoteMeta.value
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
        icon="cloud"
        title="Резервные копии"
        subtitle="Локальный ZIP, серверное резервирование и перенос между устройствами"
      />

      <article class="app-card block">
        <h2>Перенос между устройствами</h2>
        <p class="status-line">{{ portableIdentitySummary }}</p>

        <div class="identity-pill" v-if="portableIdentity">
          {{ portableIdentity.provider === 'yandex' ? 'Яндекс ID подключен' : 'VK ID подключён' }}
          <span v-if="portableIdentity.displayName">{{ portableIdentity.displayName }}</span>
        </div>

        <div class="btn-row">
          <YandexIdButton
            @click="connectProvider('yandex')"
            :disabled="authBusy !== '' || !yandexConfigured"
            :loading="authBusy === 'yandex'"
          />
          <button
            class="btn-action"
            @click="connectProvider('vk')"
            :disabled="authBusy !== '' || !vkConfigured"
          >
            {{ authBusy === 'vk' ? 'Подключение…' : 'Войти с VK ID' }}
          </button>
          <button class="btn-action" @click="refreshPortableState" :disabled="authBusy !== '' || metaBusy">
            Обновить статус
          </button>
        </div>

        <SyncProgress
          :visible="Boolean(authBusy)"
          :progress="authProgress"
          :label="authProgressLabel"
        />
      </article>

      <article class="app-card block">
        <h2>Локальный backup</h2>
        <div class="btn-row">
          <button class="btn-action" @click="buildLocalBackup" :disabled="buildBusy">
            {{ buildBusy ? 'Подготовка…' : 'Собрать и скачать ZIP' }}
          </button>
          <button class="btn-action" @click="pickRestoreFile" :disabled="restoreBusy">
            {{ restoreBusy ? 'Восстановление…' : 'Восстановить из ZIP' }}
          </button>
        </div>
      </article>

      <article class="app-card block">
        <h2>Серверный backup</h2>
        <p class="status-line" v-if="hasRemoteChanges">
          На сервере есть более новый backup. Нажмите «Синхронизировать с сервера».
        </p>

        <div class="btn-row">
          <button class="btn-action primary" @click="buildAndUploadRemote" :disabled="!canUseServerBackup || uploadBusy">
            {{ uploadBusy ? 'Загрузка…' : 'Собрать и загрузить' }}
          </button>
          <button class="btn-action" @click="pickUploadFile" :disabled="!canUseServerBackup || uploadBusy">
            Загрузить ZIP файл
          </button>
          <button class="btn-action" @click="downloadRemoteBackup" :disabled="!canUseServerBackup || downloadBusy">
            {{ downloadBusy ? 'Скачивание…' : 'Скачать ZIP' }}
          </button>
          <button
            class="btn-action"
            @click="restoreFromRemote"
            :disabled="!canUseServerBackup || restoreBusy || downloadBusy"
          >
            {{ restoreBusy ? 'Синхронизация…' : 'Синхронизировать с сервера' }}
          </button>
          <button class="btn-action danger" @click="removeRemoteBackup" :disabled="!canUseServerBackup || deleteBusy">
            {{ deleteBusy ? 'Удаление…' : 'Удалить резервную копию' }}
          </button>
        </div>

        <div class="meta-box" v-if="remoteMeta">
          <div class="meta-row"><strong>Наличие:</strong> {{ remoteMeta.exists ? 'Да' : 'Нет' }}</div>
          <div class="meta-row" v-if="remoteMeta.createdAtUtc"><strong>Создан:</strong> {{ remoteMeta.createdAtUtc }}</div>
          <div class="meta-row" v-if="remoteMeta.updatedAtUtc"><strong>Обновлён:</strong> {{ remoteMeta.updatedAtUtc }}</div>
          <div class="meta-row" v-if="remoteMeta.sizeBytes"><strong>Размер:</strong> {{ remoteMeta.sizeBytes }} байт</div>
          <div class="meta-row" v-if="remoteMeta.membersCount !== undefined">
            <strong>Профили:</strong> {{ remoteMeta.membersCount }}
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
        <h2>Журнал резервирования</h2>
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
  padding: 20px;
}

.block + .block {
  margin-top: 14px;
}

.block h2 {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 12px;
}

.identity-pill {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  color: var(--color-text);
  background: rgba(255, 255, 255, 0.03);
}

.meta-box {
  margin-top: 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  padding: 14px;
  display: grid;
  gap: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.meta-row {
  font-size: 0.88rem;
  display: flex;
  gap: 8px;
}

.meta-row strong {
  color: var(--color-text-secondary);
  min-width: 100px;
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
