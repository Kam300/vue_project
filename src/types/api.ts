export interface HealthResponse {
  status: string
  service: string
  face_recognition: boolean
  face_recognition_error?: string
  pdf_generation: boolean
  backup: boolean
  members_count: number
  recent_events: Array<{
    ts: string
    icon: string
    message: string
    type: string
  }>
  gpu?: {
    requested_cuda: boolean
    active_cuda: boolean
    dlib_use_cuda: boolean
    cuda_devices: number
    face_model: string
    reason: string
  }
}

export interface RegisterFacePayload {
  member_id: string
  member_name: string
  image: string
}

export interface RegisterFaceResponse {
  success: boolean
  message?: string
  error?: string
  details?: string
}

export interface RecognitionResult {
  member_id: string
  member_name: string
  confidence: number
  distance?: number
  margin?: number
  ambiguous?: boolean
  location: {
    top: number
    right: number
    bottom: number
    left: number
  }
}

export interface RecognizeFaceResponse {
  success: boolean
  error?: string
  details?: string
  results?: RecognitionResult[]
  faces_count?: number
  recognized_count?: number
}

export interface ListFacesResponse {
  success: boolean
  count: number
  faces: Array<{
    member_id: string
    member_name: string
  }>
  error?: string
  details?: string
}

export interface GeneratePdfResponse {
  success: boolean
  error?: string
  filename?: string
  download_url?: string
  direct_drive_url?: string
  drive_id?: string
  view_url?: string
  size?: number
  storage?: 'google_drive' | 'base64'
  pdf_base64?: string
  version?: 'v2'
}

export interface PdfV2BackgroundConfig {
  type: 'color' | 'gradient' | 'image'
  color?: string
  from?: string
  to?: string
  direction?: 'vertical' | 'horizontal' | 'diagonal'
  src?: string
  opacity?: number
  fit?: 'cover' | 'contain' | 'stretch'
}

export interface PdfV2Options {
  title?: string
  subtitle?: string
  show_photos?: boolean
  show_dates?: boolean
  show_patronymic?: boolean
  show_social_roles?: boolean
  show_footer?: boolean
  show_subtitle?: boolean
  accent_color?: string
  text_color?: string
  border_color?: string
  line_color?: string
  card_bg?: string
  bg_from?: string
  bg_to?: string
  photo_shape?: 'circle' | 'rounded' | 'square'
  connection_style?: 'orthogonal' | 'curve' | 'straight'
  font_family?: 'sans' | 'serif' | 'mono'
  show_tree?: boolean
  show_leaves?: boolean
  show_corners?: boolean
  double_frame?: boolean
  background?: PdfV2BackgroundConfig
  page_format?: string
}

export interface PdfV2OptionsResponse {
  success: boolean
  error?: string
  themes?: string[]
  card_styles?: string[]
  layouts?: string[]
  photo_shapes?: string[]
  connection_styles?: string[]
  font_families?: string[]
  page_formats?: string[]
  background_types?: string[]
}

export interface BackupMetaResponse {
  success: boolean
  exists: boolean
  schemaVersion: number
  createdAtUtc?: string
  compression?: string
  sizeBytes?: number
  membersCount?: number
  memberPhotosCount?: number
  assetsCount?: number
  checksumSha256?: string
  updatedAtUtc?: string
  /** SHA-256 of `(updated_at || "|" || checksum)` (design §3.2). */
  serverVersionTag?: string
  /** Previous tag returned on `200 OK` upload responses (design §3.3). */
  previousServerVersionTag?: string
  error?: string
  /** `session_revoked`, `precondition_required`, etc. (design §3.3). */
  reason?: string
}

export interface AuthProviderConfig {
  configured: boolean
}

export interface AuthIdentityResponse {
  provider: string
  providerUserId?: string
  displayName?: string | null
  email?: string | null
  phone?: string | null
  avatarUrl?: string | null
  connected?: boolean
}

export interface AuthUserResponse {
  id: number
  displayName: string
  email?: string | null
  preferredAuthProvider?: string | null
  isAdmin?: boolean
  /**
   * Single-session mode flag (Req 9.1, design §3.5). `true` means the server
   * will revoke other active sessions on login; `false` means multi-device
   * mode is enabled. The settings toggle in `SettingsView` is bound to the
   * inverse of this value.
   */
  singleSessionEnabled?: boolean
  providers: AuthIdentityResponse[]
}

export interface AuthSettingsPatchResponse {
  success: boolean
  singleSessionEnabled: boolean
  revokedSessions: number
  error?: string
}

export interface AuthBootstrapResponse {
  success: boolean
  providers: {
    yandex: AuthProviderConfig
    vk: AuthProviderConfig
  }
  auth: {
    authenticated: boolean
    user: AuthUserResponse | null
  }
}


// ============================================================
// ADMIN
// ============================================================

export interface AdminStatsResponse {
  success: boolean
  users: { total: number; admins: number }
  persons: number
  photos: number
  relationships: number
  family_trees: number
  backups: { count: number; total_bytes: number; files: number }
  database: { path: string; size_bytes: number }
  audit_logs: number
  face_encodings: number
  presence?: {
    total: number
    authorized: number
    window_seconds: number
  }
  error?: string
}

export interface AdminUserItem {
  id: number
  displayName: string
  email: string | null
  phone: string | null
  preferredAuthProvider: string | null
  isAdmin: boolean
  lastLoginAt: string | null
  createdAt: string | null
  providers: string[]
  personsCount: number
  backupsCount: number
}

export interface AdminUsersResponse {
  success: boolean
  users: AdminUserItem[]
  error?: string
}

export interface AdminBackupItem {
  id: number
  treeId: number
  treeTitle: string | null
  ownerUserId: number | null
  ownerName: string | null
  ownerEmail: string | null
  storagePath: string
  fileExists: boolean
  sizeBytes: number | null
  membersCount: number
  memberPhotosCount: number
  assetsCount: number
  compression: string | null
  checksumSha256: string | null
  source: string
  createdAt: string
  updatedAt: string
}

export interface AdminBackupsResponse {
  success: boolean
  backups: AdminBackupItem[]
  error?: string
}

export interface AdminAuditLogItem {
  id: number
  treeId: number
  userId: number | null
  userName: string | null
  action: string
  entityType: string | null
  entityId: string | null
  detailsJson: string | null
  createdAt: string
}

export interface AdminAuditResponse {
  success: boolean
  logs: AdminAuditLogItem[]
  error?: string
}

export interface AdminFaceItem {
  id: number
  personId: number
  personName: string | null
  externalMemberId: string | null
  modelVersion: string
  isActive: boolean
  referencePhotoPath: string | null
  createdAt: string
}

export interface AdminFacesResponse {
  success: boolean
  count: number
  encodings: AdminFaceItem[]
  error?: string
}
