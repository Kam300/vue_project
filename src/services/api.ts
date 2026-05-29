import type {
  AuthBootstrapResponse,
  AuthSettingsPatchResponse,
  AdminAuditResponse,
  AdminBackupsResponse,
  AdminFacesResponse,
  AdminStatsResponse,
  AdminUsersResponse,
  BackupMetaResponse,
  GeneratePdfResponse,
  PdfV2OptionsResponse,
  PdfV2Options,
  HealthResponse,
  ListFacesResponse,
  RecognizeFaceResponse,
  RegisterFaceResponse
} from '@/types/api'
import type { RecoveryStateRecord, RevokedReason } from '@/types/sync'
import { pendingChangesRepo, setRecoveryState } from '@/db/pendingChanges'

type HttpMethod = 'GET' | 'POST' | 'DELETE' | 'PATCH'

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

// ---------------------------------------------------------------------------
// 401 `session_revoked` middleware + recovery gate (design §4.7).
// Requirements: 7.1, 7.2, 7.3, 7.4, 18.3.
// ---------------------------------------------------------------------------

export class SessionRevokedError extends Error {
  readonly reason: RevokedReason
  constructor(reason: RevokedReason, message?: string) {
    super(message || `session_revoked: ${reason}`)
    this.name = 'SessionRevokedError'
    this.reason = reason
  }
}

export class HttpError extends Error {
  readonly status: number
  readonly payload: unknown
  constructor(status: number, message: string, payload?: unknown) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.payload = payload
  }
}

export interface RevokedToastInfo {
  reason: RevokedReason
  text: string
}

type RevokedToastListener = (info: RevokedToastInfo) => void

let isRecoveryShown = false
const recoveryAllowedPaths = new Set<string>([
  '/v2/auth/login',
  '/v2/auth/logout'
])

function isRecoveryAllowedEndpoint(endpoint: string): boolean {
  // Allow any /v2/auth/* cleanup endpoint plus the explicit allow-list.
  if (recoveryAllowedPaths.has(endpoint)) return true
  if (endpoint.startsWith('/v2/auth/')) return true
  return false
}

const revokedToastListeners = new Set<RevokedToastListener>()

export function onSessionRevokedToast(fn: RevokedToastListener): () => void {
  revokedToastListeners.add(fn)
  return () => revokedToastListeners.delete(fn)
}

// ---------------------------------------------------------------------------
// Recovery_Dialog request listener (design §4.4 / §4.7).
// Emitted after the middleware persists `recovery_state` for a buffer-non-empty
// 401 `session_revoked` response. Subscribed by `useRecoveryState`.
// ---------------------------------------------------------------------------

export interface RecoveryRequestInfo {
  userId: number
  reason: RevokedReason
  pendingCount: number
}

type RecoveryRequestListener = (info: RecoveryRequestInfo) => void

const recoveryRequestListeners = new Set<RecoveryRequestListener>()

export function onRecoveryRequest(fn: RecoveryRequestListener): () => void {
  recoveryRequestListeners.add(fn)
  return () => {
    recoveryRequestListeners.delete(fn)
  }
}

function emitRecoveryRequest(info: RecoveryRequestInfo): void {
  for (const fn of recoveryRequestListeners) {
    try {
      fn(info)
    } catch {
      // ignore listener failures
    }
  }
}

function showSessionRevokedToast(reason: RevokedReason): void {
  const text =
    reason === 'single_session_re_enabled'
      ? 'Single-session mode was re-enabled. Please sign in again'
      : 'Your session was ended because you signed in on another device'
  for (const fn of revokedToastListeners) {
    try {
      fn({ reason, text })
    } catch {
      // ignore listener failures
    }
  }
}

export function _setRecoveryShown(value: boolean): void {
  isRecoveryShown = value
}

export function _isRecoveryShown(): boolean {
  return isRecoveryShown
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    const text = await response.clone().text()
    if (!text) return null
    return JSON.parse(text)
  } catch {
    return null
  }
}

function normalizeRevokedReason(value: unknown): RevokedReason {
  return value === 'single_session_re_enabled'
    ? 'single_session_re_enabled'
    : 'signed_in_on_other_device'
}

async function getActiveUserId(): Promise<number | null> {
  try {
    // Lazy-imported to avoid a static import cycle (appStore -> api.ts -> appStore).
    const mod = await import('@/stores/appStore')
    const id = mod.useAppStore().authUser?.id
    return typeof id === 'number' ? id : null
  } catch {
    return null
  }
}

async function navigateToLogin(): Promise<void> {
  try {
    const routerMod = await import('@/router')
    await routerMod.default.push('/')
  } catch {
    // Router may be unavailable in non-browser test contexts.
  }
}

async function handleSessionRevoked(reason: RevokedReason): Promise<void> {
  const userId = await getActiveUserId()
  const bufferEmpty = userId === null ? true : await pendingChangesRepo.isEmpty(userId)

  if (bufferEmpty) {
    // Req 7.1, 7.2: clear local session, show toast, route to login.
    try {
      const mod = await import('@/stores/appStore')
      mod.useAppStore().clearLocalAuth()
    } catch {
      // ignore — store may not exist in non-Pinia contexts.
    }
    showSessionRevokedToast(reason)
    await navigateToLogin()
    isRecoveryShown = false
    return
  }

  // Req 7.3, 18.1, 18.2, 18.3: hand off to Recovery_Dialog.
  if (userId !== null) {
    const pending = await pendingChangesRepo.list(userId)
    const record: RecoveryStateRecord = {
      userId,
      revokedReason: reason,
      pendingCount: pending.length,
      openedAtUtc: new Date().toISOString(),
      state: 'Shown'
    }
    try {
      await setRecoveryState(record)
    } catch {
      // best-effort; the dialog will re-trigger on reload via watcher.
    }
    emitRecoveryRequest({
      userId,
      reason,
      pendingCount: pending.length
    })
  }
  isRecoveryShown = true
}

async function performAuthedFetch(
  endpoint: string,
  method: HttpMethod,
  options: InternalRequestOptions = {}
): Promise<Response> {
  // Req 7.4 / 18.3: while Recovery_Dialog is shown, block all authenticated calls
  // except the auth cleanup / re-login endpoints.
  if (isRecoveryShown && !isRecoveryAllowedEndpoint(endpoint)) {
    throw new SessionRevokedError(
      'signed_in_on_other_device',
      'authenticated request blocked while Recovery_Dialog is shown'
    )
  }

  const response = await performFetch(endpoint, method, options)

  if (response.status === 401) {
    const body = (await safeJson(response)) as { error?: string; reason?: string } | null
    if (body && body.error === 'session_revoked') {
      const reason = normalizeRevokedReason(body.reason)
      await handleSessionRevoked(reason)
      throw new SessionRevokedError(reason)
    }
  }

  return response
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

function isAuthenticatedEndpoint(endpoint: string): boolean {
  // Authenticated endpoints all live under /v2/* (or /api/v2/*).
  // Server-side, the middleware excludes the open set:
  //   /v2/auth/login, /v2/auth/yandex/*, /v2/auth/logout, /v2/presence/ping.
  // We mirror that on the client so those calls don't cause re-entrancy
  // when handleSessionRevoked() navigates to login.
  if (!endpoint.startsWith('/v2/')) return false
  if (endpoint === '/v2/auth/login') return false
  if (endpoint === '/v2/auth/logout') return false
  if (endpoint === '/v2/auth/bootstrap') return false
  if (endpoint === '/v2/auth/providers') return false
  if (endpoint.startsWith('/v2/auth/yandex')) return false
  if (endpoint.startsWith('/v2/presence/')) return false
  return true
}

async function request<T>(
  endpoint: string,
  method: HttpMethod = 'GET',
  options: InternalRequestOptions = {}
): Promise<T> {
  const response = isAuthenticatedEndpoint(endpoint)
    ? await performAuthedFetch(endpoint, method, options)
    : await performFetch(endpoint, method, options)
  return parseResponse<T>(response)
}

async function requestBlob(
  endpoint: string,
  method: HttpMethod = 'GET',
  options: InternalRequestOptions = {}
): Promise<Blob> {
  const response = isAuthenticatedEndpoint(endpoint)
    ? await performAuthedFetch(endpoint, method, options)
    : await performFetch(endpoint, method, options)
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

export function generatePdfV2(payload: {
  members: unknown[]
  page_format?: string
  use_drive?: boolean
  theme?: string
  card_style?: string
  layout?: string
  options?: PdfV2Options
}): Promise<GeneratePdfResponse> {
  return request<GeneratePdfResponse>('/generate_pdf_v2', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
}

export function fetchPdfV2Options(): Promise<PdfV2OptionsResponse> {
  return request<PdfV2OptionsResponse>('/pdf_v2/options', 'GET')
}

export interface PdfV3Node {
  id: string
  memberId?: string
  member?: Record<string, unknown>
  x: number
  y: number
  width: number
  height: number
  style?: Record<string, unknown>
}

export interface PdfV3Edge {
  from: string
  to: string
  from_side?: 'top' | 'bottom' | 'left' | 'right'
  to_side?: 'top' | 'bottom' | 'left' | 'right'
  style?: Record<string, unknown>
}

export function generatePdfV3(payload: {
  nodes: PdfV3Node[]
  edges?: PdfV3Edge[]
  members?: unknown[]
  page_format?: string
  background?: unknown
  title?: string
  show_header?: boolean
  show_footer?: boolean
  theme?: string
  font_family?: 'sans' | 'serif' | 'mono'
  defaults?: Record<string, unknown>
  use_drive?: boolean
}): Promise<GeneratePdfResponse> {
  return request<GeneratePdfResponse>('/generate_pdf_v3', 'POST', {
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' }
  })
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

/**
 * PATCH /v2/auth/settings — toggle Single_Session_Mode (design §4.8, Req 9.3, 9.4).
 *
 * On 2xx the server returns the new flag and the count of revoked sessions.
 * Non-2xx responses surface the server's `error` field via the standard
 * `parseResponse` path, so callers can revert the optimistic UI on failure.
 */
export function authSettingsPatch(
  body: { singleSessionEnabled: boolean },
  authToken = '',
  deviceId?: string | number
): Promise<AuthSettingsPatchResponse> {
  return request<AuthSettingsPatchResponse>('/v2/auth/settings', 'PATCH', {
    body: JSON.stringify(body),
    timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
    headers: {
      'Content-Type': 'application/json',
      ...buildDeviceHeaders(authToken, deviceId)
    }
  })
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
  // Legacy entry point. Routes through `backupUploadWithMatch()` with a
  // wildcard `If-Match: *` and `force=true` so existing call sites in
  // `BackupView.vue` keep working until syncTicker (task 6.2) takes over.
  return backupUploadWithMatch({
    authToken,
    deviceId,
    zipFile,
    ifMatch: '*',
    force: true,
    changeIds: []
  })
}

/**
 * Upload a backup archive with optimistic-concurrency headers (design §4.7).
 *
 * Sets `If-Match: <ifMatch>` (tag or `*`), the `force=true` query param when
 * applicable, and `X-Client-Capabilities: if-match-v1`. Resolves to the
 * `BackupMetaResponse` (which now includes `serverVersionTag` and, on `200`
 * responses, `previousServerVersionTag`).
 */
export function backupUploadWithMatch(opts: {
  authToken: string
  deviceId?: string | number
  zipFile: Blob
  /** `Server_Version_Tag` or `*`. */
  ifMatch: string
  force?: boolean
  /** Pending change ids being confirmed by this upload. */
  changeIds: string[]
  signal?: AbortSignal
  timeoutMs?: number
}): Promise<BackupMetaResponse> {
  const formData = new FormData()
  formData.append('backup_file', opts.zipFile, 'familyone_backup.zip')
  formData.append('change_ids', JSON.stringify(opts.changeIds || []))

  const endpoint = opts.force
    ? '/v2/backup/upload?force=true'
    : '/v2/backup/upload'

  return request<BackupMetaResponse>(endpoint, 'POST', {
    body: formData,
    timeoutMs: opts.timeoutMs ?? BACKUP_TRANSFER_TIMEOUT_MS,
    signal: opts.signal,
    headers: {
      'If-Match': opts.ifMatch,
      'X-Client-Capabilities': 'if-match-v1',
      ...buildDeviceHeaders(opts.authToken, opts.deviceId)
    }
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


// ============================================================
// ADMIN
// ============================================================

export function adminStats(deviceId?: string | number): Promise<AdminStatsResponse> {
  return request<AdminStatsResponse>('/v2/admin/stats', 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminUsers(deviceId?: string | number): Promise<AdminUsersResponse> {
  return request<AdminUsersResponse>('/v2/admin/users', 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminSetUserAdmin(
  userId: number,
  isAdmin: boolean,
  deviceId?: string | number
): Promise<{ success: boolean; error?: string }> {
  return request(`/v2/admin/users/${userId}/admin`, 'POST', {
    headers: {
      'Content-Type': 'application/json',
      ...buildDeviceHeaders('', deviceId)
    },
    body: JSON.stringify({ isAdmin })
  })
}

export function adminDeleteUser(
  userId: number,
  deviceId?: string | number
): Promise<{ success: boolean; error?: string }> {
  return request(`/v2/admin/users/${userId}`, 'DELETE', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminBulkDeleteUsers(
  userIds: number[],
  deviceId?: string | number
): Promise<{
  success: boolean
  deleted: number
  skipped: Array<{ id: number; reason: string }>
  error?: string
}> {
  return request('/v2/admin/users/bulk-delete', 'POST', {
    headers: {
      'Content-Type': 'application/json',
      ...buildDeviceHeaders('', deviceId)
    },
    body: JSON.stringify({ userIds })
  })
}

export function adminBackups(deviceId?: string | number): Promise<AdminBackupsResponse> {
  return request<AdminBackupsResponse>('/v2/admin/backups', 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminDeleteBackup(
  backupId: number,
  deviceId?: string | number
): Promise<{ success: boolean; deleted?: boolean; error?: string }> {
  return request(`/v2/admin/backups/${backupId}`, 'DELETE', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminAudit(limit = 100, deviceId?: string | number): Promise<AdminAuditResponse> {
  return request<AdminAuditResponse>(`/v2/admin/audit?limit=${limit}`, 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminFaces(deviceId?: string | number): Promise<AdminFacesResponse> {
  return request<AdminFacesResponse>('/v2/admin/faces', 'GET', {
    headers: buildDeviceHeaders('', deviceId)
  })
}

export function adminDeleteFace(
  faceId: number,
  deviceId?: string | number
): Promise<{ success: boolean; error?: string }> {
  return request(`/v2/admin/faces/${faceId}`, 'DELETE', {
    headers: buildDeviceHeaders('', deviceId)
  })
}


export function presencePing(deviceId?: string | number): Promise<{ success: boolean }> {
  return request('/v2/presence/ping', 'POST', {
    headers: buildDeviceHeaders('', deviceId),
    timeoutMs: 8000
  })
}
