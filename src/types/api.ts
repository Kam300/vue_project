export interface HealthResponse {
  status: string
  service: string
  face_recognition: boolean
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
