import Dexie, { type EntityTable } from 'dexie'
import type {
  AppSetting,
  BackupAuditRecord,
  FamilyMember,
  MemberPhoto
} from '@/types/models'

export class FamilyOneDatabase extends Dexie {
  members!: EntityTable<FamilyMember, 'id'>
  member_photos!: EntityTable<MemberPhoto, 'id'>
  app_settings!: EntityTable<AppSetting, 'key'>
  backup_audit!: EntityTable<BackupAuditRecord, 'id'>

  constructor() {
    super('familyone_web_db')

    this.version(1).stores({
      members: '++id, lastName, role, fatherId, motherId, birthDate',
      member_photos: '++id, memberId, dateAdded, imageHash, isProfilePhoto',
      app_settings: 'key',
      backup_audit: '++id, action, timestamp'
    })
  }
}

export const db = new FamilyOneDatabase()
