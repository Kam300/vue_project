export type Gender = 'MALE' | 'FEMALE'

export type FamilyRole =
  | 'GRANDFATHER'
  | 'GRANDMOTHER'
  | 'FATHER'
  | 'MOTHER'
  | 'SON'
  | 'DAUGHTER'
  | 'GRANDSON'
  | 'GRANDDAUGHTER'
  | 'BROTHER'
  | 'SISTER'
  | 'UNCLE'
  | 'AUNT'
  | 'NEPHEW'
  | 'NIECE'
  | 'OTHER'

export interface FamilyMember {
  id?: number
  firstName: string
  lastName: string
  patronymic?: string | null
  gender: Gender
  birthDate: string
  phoneNumber?: string | null
  role: FamilyRole
  photoUri?: string | null
  maidenName?: string | null
  fatherId?: number | null
  motherId?: number | null
  weddingDate?: string | null
  createdAt?: string
  updatedAt?: string
}

export interface MemberPhoto {
  id?: number
  memberId: number
  photoUri: string
  dateAdded: number
  description?: string | null
  isProfilePhoto: boolean
  imageHash?: string | null
}

export interface AppSetting {
  key: string
  value: string
}

export type BackupAuditAction =
  | 'local_export'
  | 'local_import_merge'
  | 'local_import_replace'
  | 'backup_upload'
  | 'backup_download'
  | 'backup_restore'
  | 'backup_delete'
  | 'face_sync'

export interface BackupAuditRecord {
  id?: number
  action: BackupAuditAction
  timestamp: string
  details: string
}

export interface AppSettingsState {
  onboardingCompleted: boolean
  privacyConsented: boolean
  pinEnabled: boolean
  pinHash: string
  treeTemplate: 'modern' | 'classic' | 'print'
  apiBaseUrl: string
  theme: 'system' | 'light' | 'dark'
  deviceId: number
  appLockBySession: boolean
}

export interface SelectOption<T> {
  value: T
  label: string
}

export const GENDER_OPTIONS: SelectOption<Gender>[] = [
  { value: 'MALE', label: 'Мужской' },
  { value: 'FEMALE', label: 'Женский' }
]

export const ROLE_OPTIONS: SelectOption<FamilyRole>[] = [
  { value: 'GRANDFATHER', label: 'Дедушка' },
  { value: 'GRANDMOTHER', label: 'Бабушка' },
  { value: 'FATHER', label: 'Отец' },
  { value: 'MOTHER', label: 'Мать' },
  { value: 'SON', label: 'Сын' },
  { value: 'DAUGHTER', label: 'Дочь' },
  { value: 'GRANDSON', label: 'Внук' },
  { value: 'GRANDDAUGHTER', label: 'Внучка' },
  { value: 'BROTHER', label: 'Брат' },
  { value: 'SISTER', label: 'Сестра' },
  { value: 'UNCLE', label: 'Дядя' },
  { value: 'AUNT', label: 'Тетя' },
  { value: 'NEPHEW', label: 'Племянник' },
  { value: 'NIECE', label: 'Племянница' },
  { value: 'OTHER', label: 'Другое' }
]

export const ROLE_LABELS: Record<FamilyRole, string> = Object.fromEntries(
  ROLE_OPTIONS.map((option) => [option.value, option.label])
) as Record<FamilyRole, string>
