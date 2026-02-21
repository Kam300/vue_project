import { db } from '@/db/database'
import type {
  AppSettingsState,
  BackupAuditAction,
  BackupAuditRecord,
  FamilyMember,
  MemberPhoto
} from '@/types/models'
import { normalizeDateToDisplayFormat } from '@/utils/date'

const SETTINGS_KEYS = {
  onboardingCompleted: 'onboarding_completed',
  privacyConsented: 'privacy_consented',
  pinEnabled: 'pin_enabled',
  pinHash: 'pin_hash',
  treeTemplate: 'tree_template',
  apiBaseUrl: 'api_base_url',
  theme: 'theme',
  deviceId: 'device_id',
  appLockBySession: 'app_lock_by_session'
} as const

export const DEFAULT_APP_SETTINGS: AppSettingsState = {
  onboardingCompleted: false,
  privacyConsented: false,
  pinEnabled: false,
  pinHash: '',
  treeTemplate: 'modern',
  apiBaseUrl: import.meta.env.VITE_API_BASE || '/api',
  theme: 'system',
  deviceId: 0,
  appLockBySession: false
}

function parseBoolean(raw: string | undefined, fallback: boolean): boolean {
  if (raw === undefined) return fallback
  return raw === 'true'
}

function parseNumber(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback
  const value = Number(raw)
  return Number.isFinite(value) ? value : fallback
}

export async function ensureDeviceId(): Promise<number> {
  const saved = await db.app_settings.get(SETTINGS_KEYS.deviceId)
  const parsed = parseNumber(saved?.value, 0)
  if (parsed > 0) return parsed

  const generated = Math.max(1, Math.floor(Date.now() % 1_000_000))
  await db.app_settings.put({ key: SETTINGS_KEYS.deviceId, value: String(generated) })
  return generated
}

export async function getAppSettings(): Promise<AppSettingsState> {
  const rows = await db.app_settings.toArray()
  const map = new Map(rows.map((row) => [row.key, row.value]))

  const deviceId = parseNumber(map.get(SETTINGS_KEYS.deviceId), 0) || (await ensureDeviceId())

  return {
    onboardingCompleted: parseBoolean(
      map.get(SETTINGS_KEYS.onboardingCompleted),
      DEFAULT_APP_SETTINGS.onboardingCompleted
    ),
    privacyConsented: parseBoolean(
      map.get(SETTINGS_KEYS.privacyConsented),
      DEFAULT_APP_SETTINGS.privacyConsented
    ),
    pinEnabled: parseBoolean(map.get(SETTINGS_KEYS.pinEnabled), DEFAULT_APP_SETTINGS.pinEnabled),
    pinHash: map.get(SETTINGS_KEYS.pinHash) || DEFAULT_APP_SETTINGS.pinHash,
    treeTemplate:
      (map.get(SETTINGS_KEYS.treeTemplate) as AppSettingsState['treeTemplate']) ||
      DEFAULT_APP_SETTINGS.treeTemplate,
    apiBaseUrl: map.get(SETTINGS_KEYS.apiBaseUrl) || DEFAULT_APP_SETTINGS.apiBaseUrl,
    theme: (map.get(SETTINGS_KEYS.theme) as AppSettingsState['theme']) || DEFAULT_APP_SETTINGS.theme,
    deviceId,
    appLockBySession: parseBoolean(
      map.get(SETTINGS_KEYS.appLockBySession),
      DEFAULT_APP_SETTINGS.appLockBySession
    )
  }
}

export async function patchAppSettings(
  patch: Partial<AppSettingsState>
): Promise<AppSettingsState> {
  const current = await getAppSettings()
  const next = { ...current, ...patch }

  await db.app_settings.bulkPut([
    { key: SETTINGS_KEYS.onboardingCompleted, value: String(next.onboardingCompleted) },
    { key: SETTINGS_KEYS.privacyConsented, value: String(next.privacyConsented) },
    { key: SETTINGS_KEYS.pinEnabled, value: String(next.pinEnabled) },
    { key: SETTINGS_KEYS.pinHash, value: String(next.pinHash || '') },
    { key: SETTINGS_KEYS.treeTemplate, value: next.treeTemplate },
    { key: SETTINGS_KEYS.apiBaseUrl, value: next.apiBaseUrl },
    { key: SETTINGS_KEYS.theme, value: next.theme },
    { key: SETTINGS_KEYS.deviceId, value: String(next.deviceId) },
    { key: SETTINGS_KEYS.appLockBySession, value: String(next.appLockBySession) }
  ])

  return next
}

export async function getAllMembers(): Promise<FamilyMember[]> {
  return db.members.orderBy('lastName').toArray()
}

export async function getMemberById(memberId: number): Promise<FamilyMember | undefined> {
  return db.members.get(memberId)
}

export async function upsertMember(payload: FamilyMember): Promise<number> {
  const now = new Date().toISOString()
  const normalizedPayload: FamilyMember = {
    ...payload,
    birthDate: normalizeDateToDisplayFormat(payload.birthDate),
    weddingDate: payload.weddingDate ? normalizeDateToDisplayFormat(payload.weddingDate) : null,
    updatedAt: now
  }

  if (normalizedPayload.id) {
    await db.members.update(normalizedPayload.id, normalizedPayload)
    return normalizedPayload.id
  }

  const insertedId = await db.members.add({
    ...normalizedPayload,
    createdAt: now
  })
  if (typeof insertedId !== 'number') {
    throw new Error('Не удалось сохранить члена семьи')
  }
  return insertedId
}

export async function deleteMember(memberId: number): Promise<void> {
  await db.transaction('rw', db.members, db.member_photos, async () => {
    await db.members.delete(memberId)
    await db.member_photos.where('memberId').equals(memberId).delete()
  })
}

export async function deleteAllMembers(): Promise<void> {
  await db.transaction('rw', db.members, db.member_photos, async () => {
    await db.members.clear()
    await db.member_photos.clear()
  })
}

export async function getMemberPhotos(memberId: number): Promise<MemberPhoto[]> {
  return db.member_photos.where('memberId').equals(memberId).reverse().sortBy('dateAdded')
}

export async function getAllPhotos(): Promise<MemberPhoto[]> {
  return db.member_photos.reverse().sortBy('dateAdded')
}

export async function addMemberPhoto(photo: Omit<MemberPhoto, 'id'>): Promise<number> {
  const insertedId = await db.member_photos.add(photo)
  if (typeof insertedId !== 'number') {
    throw new Error('Не удалось сохранить фото')
  }
  return insertedId
}

export async function deleteMemberPhoto(photoId: number): Promise<void> {
  await db.member_photos.delete(photoId)
}

export async function clearMemberPhotos(memberId: number): Promise<void> {
  await db.member_photos.where('memberId').equals(memberId).delete()
}

export async function addBackupAudit(
  action: BackupAuditAction,
  details: string
): Promise<BackupAuditRecord> {
  const payload: BackupAuditRecord = {
    action,
    details,
    timestamp: new Date().toISOString()
  }

  payload.id = await db.backup_audit.add(payload)
  return payload
}

export async function getBackupAudit(): Promise<BackupAuditRecord[]> {
  return db.backup_audit.reverse().sortBy('timestamp')
}
