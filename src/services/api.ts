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

export interface ApiRequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

interface InternalRequestOptions extends ApiRequestOptions {
  body?: BodyInit
  headers?: Record<string, string>
}

const DEFAULT_REQUEST_TIMEOUT_MS = 15_000
const HEALTH_REQUEST_TIMEOUT_MS = 8_000
const LIST_FACES_TIMEOUT_MS = 10_000
const AUTH_REQUEST_TIMEOUT_MS = 15_000
const BACKUP_META_TIMEOUT_MS = 20_000
const BACKUP_TRANSFER_TIMEOUT_MS = 120_000
const TIMEOUT_MARKER = '__familyone_timeout__'

let apiBase = import.meta.env.VITE_API_BASE || '/api'

export function setApiBaseUrl(base: string): void {
  apiBase = base || '/api'
}

export function getApiBaseUrl(): string {
  return apiBase
}

function isOfflineHintNeeded(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false
}

function formatTimeout(timeoutMs: number): string {
  const seconds = Math.max(1, Math.ceil(timeoutMs / 1000))
  return `${seconds} сек.`
}

function buildFriendlyNetworkError(reason: unknown, timeoutMs: number, externalSignal?: AbortSignal): Error {
  if (reason instanceof Error && reason.message === TIMEOUT_MARKER) {
    return new Error(
      `Сервер не ответил за ${formatTimeout(timeoutMs)}. ${
        isOfflineHintNeeded()
          ? 'Похоже, устройство сейчас офлайн.'
          : 'Проверьте интернет и попробуйте снова.'
      }`
    )
  }

  if (reason instanceof DOMException && reason.name === 'AbortError') {
    if (externalSignal?.aborted) {
      return new Error('Запрос был отменён.')
    }
    return new Error(
      `Сервер не ответил за ${formatTimeout(timeoutMs)}. ${
        isOfflineHintNeeded()
          ? 'Похоже, устройство сейчас офлайн.'
          : 'Проверьте интернет и попробуйте снова.'
      }`
    )
  }

  if (reason instanceof TypeError) {
    return new Error(
      isOfflineHintNeeded()
        ? 'Нет подключения к сети. Проверьте интернет и повторите попытку.'
        : 'Не удалось выполнить сетевой запрос. Проверьте интернет и доступность сервера.'
    )
  }

  if (reason instanceof Error) {
    return reason
  }

  return new Error('Не удалось выполнить сетевой запрос.')
}

function buildErrorMessage(response: Response, payload: unknown): string {
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

  if (typeof payload === 'string') {
    const text = payload.trim()
    if (text && !/^<!doctype html/i.test(text) && !/^<html/i.test(text)) {
      return text
    }
  }

  return `HTTP ${response.status}`
}

function createLinkedAbortSignal(externalSignal?: AbortSignal): {
  signal?: AbortSignal
  abort: () => void
  cleanup: () => void
} {
  if (typeof AbortController === 'undefined') {
    return {
      signal: externalSignal,
      abort: () => {},
      cleanup: () => {}
    }
  }

  const controller = new AbortController()
  const abortFromOutside = () => controller.abort()

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort()
    } else {
      externalSignal.addEventListener('abort', abortFromOutside, { once: true })
    }
  }

  return {
    signal: controller.signal,
    abort: () => controller.abort(),
    cleanup: () => {
      externalSignal?.removeEventListener('abort', abortFromOutside)
    }
  }
}

async function performFetch(
  endpoint: string,
  method: HttpMethod,
  options: InternalRequestOptions = {}
): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS
  const { signal, abort, cleanup } = createLinkedAbortSignal(options.signal)
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  const fetchPromise = fetch(`${apiBase}${endpoint}`, {
    method,
    body: options.body,
    headers: options.headers,
    credentials: 'same-origin',
    signal
  })

  const timeoutPromise =
    timeoutMs > 0
      ? new Promise<never>((_, reject) => {
          timeoutId = setTimeout(() => {
            abort()
            reject(new Error(TIMEOUT_MARKER))
          }, timeoutMs)
        })
      : null

  try {
    if (!timeoutPromise) {
      return await fetchPromise
    }
    return await Promise.race([fetchPromise, timeoutPromise])
  } catch (reason) {
    throw buildFriendlyNetworkError(reason, timeoutMs, options.signal)
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
    }
    cleanup()
  }
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
    throw new Error(buildErrorMessage(response, payload))
  }

  return payload as T
}

async function parseBlobResponse(response: Response): Promise<Blob> {
  if (!response.ok) {
    const text = await response.text()
    let payload: unknown = text
    if (text) {
      try {
        payload = JSON.parse(text)
      } catch {
        payload = text
      }
    }
    throw new Error(buildErrorMessage(response, payload))
  }

  return response.blob()
}

async function request<T>(
  endpoint: string,
  method: HttpMethod = 'GET',
  options: InternalRequestOptions = {}
): Promise<T> {
  const response = await performFetch(endpoint, method, options)
  return parseResponse<T>(response)
}

async function requestBlob(
  endpoint: string,
  method: HttpMethod = 'GET',
  options: InternalRequestOptions = {}
): Promise<Blob> {
  const response = await performFetch(endpoint, method, options)
  return parseBlobResponse(response)
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

export function healthCheck(options: ApiRequestOptions = {}): Promise<HealthResponse> {
  return request<HealthResponse>('/health', 'GET', {
    timeoutMs: HEALTH_REQUEST_TIMEOUT_MS,
    ...options
  })
}

export function listFaces(options: ApiRequestOptions = {}): Promise<ListFacesResponse> {
  return request<ListFacesResponse>('/list_faces', 'GET', {
    timeoutMs: LIST_FACES_TIMEOUT_MS,
    ...options
  })
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
    timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
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
    timeoutMs: BACKUP_META_TIMEOUT_MS,
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
    timeoutMs: BACKUP_TRANSFER_TIMEOUT_MS,
    headers: buildDeviceHeaders(authToken, deviceId)
  })
}

export function backupDownload(authToken = '', deviceId?: string | number): Promise<Blob> {
  return requestBlob('/v2/backup/download', 'GET', {
    timeoutMs: BACKUP_TRANSFER_TIMEOUT_MS,
    headers: buildDeviceHeaders(authToken, deviceId)
  })
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
