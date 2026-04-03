import type {
  AuthBootstrapResponse,
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
    const errorMessage = (() => {
      if (typeof payload === 'object' && payload) {
        const error = 'error' in payload ? String((payload as { error?: string }).error || '') : ''
        const details = 'details' in payload ? String((payload as { details?: string }).details || '') : ''
        if (error && details && details !== error) {
          return `${error}: ${details}`
        }
        if (error) {
          return error
        }
      }
      return `HTTP ${response.status}`
    })()
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
    headers: options.headers,
    credentials: 'same-origin'
  })
  return parseResponse<T>(response)
}

function buildDeviceHeaders(authToken = '', deviceId?: string | number): Record<string, string> {
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
  device_id?: string | number
}): Promise<RecognizeFaceResponse> {
  return request<RecognizeFaceResponse>('/recognize_face', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
}

export function deleteFace(memberId: string | number): Promise<RegisterFaceResponse> {
  return request<RegisterFaceResponse>(`/delete_face/${encodeURIComponent(String(memberId))}`, 'DELETE')
}

export function clearAllFaces(deviceId?: string | number): Promise<RegisterFaceResponse> {
  const normalizedDeviceId =
    deviceId !== undefined && deviceId !== null ? String(deviceId).trim() : ''
  const endpoint = normalizedDeviceId
    ? `/clear_all?device_id=${encodeURIComponent(normalizedDeviceId)}`
    : '/clear_all'
  return request<RegisterFaceResponse>(endpoint, 'DELETE')
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

export function authBootstrap(payload: {
  deviceId: string | number
  displayName?: string
}): Promise<AuthBootstrapResponse> {
  return request<AuthBootstrapResponse>('/v2/auth/bootstrap', 'POST', {
    body: JSON.stringify(payload),
    headers: {
      'Content-Type': 'application/json',
      ...buildDeviceHeaders('', payload.deviceId)
    }
  })
}

export function authProviders(): Promise<AuthBootstrapResponse['providers']> {
  return request<{ success: boolean; providers: AuthBootstrapResponse['providers'] }>('/v2/auth/providers').then(
    (response) => response.providers
  )
}

export function authMe(deviceId?: string | number): Promise<AuthBootstrapResponse> {
  return request<AuthBootstrapResponse>('/v2/auth/me', 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function authLogout(): Promise<{ success: boolean }> {
  return request<{ success: boolean }>('/v2/auth/logout', 'POST')
}

export function backupMeta(authToken = '', deviceId?: string | number): Promise<BackupMetaResponse> {
  return request<BackupMetaResponse>('/v2/backup/meta', 'GET', {
    headers: buildDeviceHeaders(authToken, deviceId)
  })
}

export function backupUpload(
  authToken: string,
  zipFile: Blob,
  deviceId?: string | number
): Promise<BackupMetaResponse> {
  const formData = new FormData()
  formData.append('backup_file', zipFile, 'familyone_backup.zip')
  return request<BackupMetaResponse>('/v2/backup/upload', 'POST', {
    body: formData,
    headers: buildDeviceHeaders(authToken, deviceId)
  })
}

export async function backupDownload(authToken = '', deviceId?: string | number): Promise<Blob> {
  const response = await fetch(`${apiBase}/v2/backup/download`, {
    headers: buildDeviceHeaders(authToken, deviceId),
    credentials: 'same-origin'
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
  return request('/v2/backup', 'DELETE', {
    headers: buildDeviceHeaders(authToken, deviceId)
  })
}
