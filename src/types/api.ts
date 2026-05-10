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
  error?: string
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
  providers: AuthIdentityResponse[]
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
