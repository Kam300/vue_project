import { addBackupAudit } from '@/db/repositories'
import { backupDownload, backupMeta } from '@/services/api'
import { restoreBackupArchive } from '@/services/backupArchive'
import { connectVkIdentity, connectYandexIdentity } from '@/services/authIdentity'
import { syncProfileFaces } from '@/services/familySync'
import { useAppStore } from '@/stores/appStore'
import { useMemberStore } from '@/stores/memberStore'

export type PortableIdentityProvider = 'yandex' | 'vk'

export interface PortableIdentityProgress {
  progress: number
  message: string
}

export async function connectPortableIdentityAndSync(
  provider: PortableIdentityProvider,
  options: {
    onProgress?: (progress: PortableIdentityProgress) => void
    afterSync?: () => Promise<void>
  } = {}
): Promise<string> {
  const appStore = useAppStore()
  const memberStore = useMemberStore()
  const deviceId = String(appStore.settings.deviceId || '').trim()

  if (!deviceId) {
    throw new Error('Device ID не инициализирован. Перезапустите приложение.')
  }

  const report = (progress: number, message: string) => {
    options.onProgress?.({ progress, message })
  }

  report(12, 'Открываем окно авторизации…')
  if (provider === 'yandex') {
    await connectYandexIdentity(deviceId)
  } else {
    await connectVkIdentity()
  }

  report(42, 'Обновляем сеанс и привязку аккаунта…')
  await appStore.refreshAuthState()

  report(74, 'Загружаем данные семьи из серверной БД…')
  const remoteMeta = await backupMeta('', deviceId)
  if (remoteMeta.exists) {
    const blob = await backupDownload('', deviceId)
    const restoreReport = await restoreBackupArchive(blob)
    await addBackupAudit(
      'backup_restore',
      JSON.stringify({
        source: 'remote-auto-sync',
        restore: restoreReport
      })
    )

    try {
      const faceSync = await syncProfileFaces(appStore.settings.deviceId)
      await addBackupAudit('face_sync', JSON.stringify(faceSync))
    } catch {
      // face sync errors should not break auth sync
    }
  }
  await memberStore.refresh()

  if (options.afterSync) {
    report(88, 'Обновляем резервные копии и журнал…')
    await options.afterSync()
  }

  report(100, 'Синхронизация завершена.')

  if (!remoteMeta.exists) {
    return provider === 'yandex'
      ? 'Яндекс ID подключен. Удалённый backup пока не найден.'
      : 'VK ID подключён. Удалённый backup пока не найден.'
  }

  return provider === 'yandex'
    ? 'Яндекс ID подключен. Данные синхронизированы с серверной БД.'
    : 'VK ID подключён. Данные синхронизированы с серверной БД.'
}
