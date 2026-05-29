// Multi-device sync safety domain types.
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.1, §8 Web data models.

export type EditKind =
  | 'member.create'
  | 'member.update'
  | 'member.delete'
  | 'relationship.create'
  | 'relationship.update'
  | 'relationship.delete'
  | 'note.create'
  | 'note.update'
  | 'note.delete'
  | 'event.create'
  | 'event.update'
  | 'event.delete'
  | 'tree.metadata.update'

export const EDIT_KINDS: ReadonlyArray<EditKind> = [
  'member.create',
  'member.update',
  'member.delete',
  'relationship.create',
  'relationship.update',
  'relationship.delete',
  'note.create',
  'note.update',
  'note.delete',
  'event.create',
  'event.update',
  'event.delete',
  'tree.metadata.update'
]

/** Maximum allowed size of `payloadJson` in bytes (Req 16.5). */
export const PAYLOAD_JSON_MAX_BYTES = 262144

/** A single durable buffered edit (Req 16.1, 16.3, 16.4). */
export interface PendingChange {
  /** UUID v4. Acts as the primary key (`keyPath`). */
  changeId: string
  userId: number
  /** Strictly monotonic per `userId`, starting at 1. */
  sequenceNumber: number
  /** ISO 8601 UTC timestamp. */
  createdAtUtc: string
  editKind: EditKind
  /** Entity id, or empty string for tree-level metadata. */
  targetId: string
  /** Serialized diff. Must be ≤ `PAYLOAD_JSON_MAX_BYTES`. */
  payloadJson: string
}

export type LocalAuditAction =
  | 'pending_change_uploaded'
  | 'pending_change_exported'
  | 'pending_change_discarded'

/** Local audit log row (Req 20.4). */
export interface LocalAuditRecord {
  changeId: string
  action: LocalAuditAction
  atUtc: string
}

export type RevokedReason =
  | 'signed_in_on_other_device'
  | 'single_session_re_enabled'

export type RecoveryDialogState =
  | 'Idle'
  | 'Shown'
  | 'ReAuthing'
  | 'Syncing'
  | 'Conflict'
  | 'Exporting'
  | 'Confirming'

/** Persisted recovery dialog state (Req 18.8). */
export interface RecoveryStateRecord {
  userId: number
  revokedReason: RevokedReason
  pendingCount: number
  openedAtUtc: string
  state: RecoveryDialogState
}
