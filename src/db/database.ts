import Dexie, { type EntityTable } from 'dexie'
import type {
  AppSetting,
  BackupAuditRecord,
  FamilyMember,
  MemberPhoto
} from '@/types/models'
import type {
  PendingChange,
  LocalAuditRecord,
  RecoveryStateRecord
} from '@/types/sync'

export class FamilyOneDatabase extends Dexie {
  members!: EntityTable<FamilyMember, 'id'>
  member_photos!: EntityTable<MemberPhoto, 'id'>
  app_settings!: EntityTable<AppSetting, 'key'>
  backup_audit!: EntityTable<BackupAuditRecord, 'id'>
  pending_changes!: EntityTable<PendingChange, 'changeId'>
  pending_seq_counters!: EntityTable<{ userId: number; nextSeq: number }, 'userId'>
  local_audit!: EntityTable<LocalAuditRecord, 'changeId'>
  recovery_state!: EntityTable<RecoveryStateRecord, 'userId'>

  constructor(name: string = 'familyone_web_db') {
    super(name)

    this.version(1).stores({
      members: '++id, lastName, role, fatherId, motherId, birthDate',
      member_photos: '++id, memberId, dateAdded, imageHash, isProfilePhoto',
      app_settings: 'key',
      backup_audit: '++id, action, timestamp'
    })

    // Multi-device sync safety stores (Req 16.x, 18.8, 20.4).
    this.version(2).stores({
      members: '++id, lastName, role, fatherId, motherId, birthDate',
      member_photos: '++id, memberId, dateAdded, imageHash, isProfilePhoto',
      app_settings: 'key',
      backup_audit: '++id, action, timestamp',
      pending_changes:
        'changeId, userId, &[userId+sequenceNumber], [userId+createdAtUtc]',
      pending_seq_counters: 'userId',
      local_audit: 'changeId, action, atUtc',
      recovery_state: 'userId'
    })
  }
}

export const db = new FamilyOneDatabase()
