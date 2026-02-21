import type {
  BackupMetaResponse,
  GeneratePdfResponse,
  HealthResponse,
  ListFacesResponse,
  RecognizeFaceResponse,
  RegisterFaceResponse
} from '@/types/api'

type HttpMethod = 'GET' | 'POST' | 'DELETE'

let apiBase = import.meta.env.VITE_API_BASE || '/api'

export function setApiBaseUrl(base: string): void {
  apiBase = base || '/api'
}

export function getApiBaseUrl(): string {
  return apiBase
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    const errorMessage =
      typeof payload === 'object' && payload && 'error' in payload
        ? String((payload as { error?: string }).error || '')
        : `HTTP ${response.status}`
    throw new Error(errorMessage || `HTTP ${response.status}`)
  }

  return payload as T
}

async function request<T>(
  endpoint: string,
  method: HttpMethod = 'GET',
  options: {
    body?: BodyInit
    headers?: Record<string, string>
  } = {}
): Promise<T> {
  const response = await fetch(`${apiBase}${endpoint}`, {
    method,
    body: options.body,
    headers: options.headers
  })
  return parseResponse<T>(response)
}

export function healthCheck(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export function listFaces(): Promise<ListFacesResponse> {
  return request<ListFacesResponse>('/list_faces')
}

export function registerFace(payload: {
  member_id: string
  member_name: string
  image: string
}): Promise<RegisterFaceResponse> {
  return request<RegisterFaceResponse>('/register_face', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
}

export function recognizeFace(payload: {
  image: string
  threshold?: number
}): Promise<RecognizeFaceResponse> {
  return request<RecognizeFaceResponse>('/recognize_face', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
}

export function deleteFace(memberId: string | number): Promise<RegisterFaceResponse> {
  return request<RegisterFaceResponse>(`/delete_face/${encodeURIComponent(String(memberId))}`, 'DELETE')
}

export function clearAllFaces(): Promise<RegisterFaceResponse> {
  return request<RegisterFaceResponse>('/clear_all', 'DELETE')
}

export function generatePdf(payload: {
  members: unknown[]
  format: string
  use_drive: boolean
  show_photos: boolean
  show_dates: boolean
  show_patronymic: boolean
  title: string
  photo_quality: string
}): Promise<GeneratePdfResponse> {
  return request<GeneratePdfResponse>('/generate_pdf', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
}

export function buildPdfDownloadUrl(driveId: string): string {
  return `${apiBase}/download_pdf/${encodeURIComponent(driveId)}`
}

function buildBackupHeaders(authToken = '', deviceId?: string | number): Record<string, string> {
  const headers: Record<string, string> = {}
  const normalizedToken = String(authToken || '').trim()
  if (normalizedToken) {
    headers.Authorization = `Bearer ${normalizedToken}`
  }
  if (deviceId !== undefined && deviceId !== null && String(deviceId).trim()) {
    headers['X-FamilyOne-Device'] = String(deviceId).trim()
  }
  return headers
}

export function backupMeta(authToken = '', deviceId?: string | number): Promise<BackupMetaResponse> {
  return request<BackupMetaResponse>('/backup/meta', 'GET', {
    headers: buildBackupHeaders(authToken, deviceId)
  })
}

export function backupUpload(
  authToken: string,
  zipFile: Blob,
  deviceId?: string | number
): Promise<BackupMetaResponse> {
  const formData = new FormData()
  formData.append('backup_file', zipFile, 'familyone_backup.zip')
  return request<BackupMetaResponse>('/backup/upload', 'POST', {
    body: formData,
    headers: buildBackupHeaders(authToken, deviceId)
  })
}

export async function backupDownload(authToken = '', deviceId?: string | number): Promise<Blob> {
  const response = await fetch(`${apiBase}/backup/download`, {
    headers: buildBackupHeaders(authToken, deviceId)
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.blob()
}

export function backupDelete(authToken = '', deviceId?: string | number): Promise<{
  success: boolean
  schemaVersion: number
  deleted: boolean
}> {
  return request('/backup', 'DELETE', {
    headers: buildBackupHeaders(authToken, deviceId)
  })
}
