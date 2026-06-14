import { getApiBaseUrl } from '@/services/api'

type PortableProvider = 'yandex' | 'vk'

interface PopupAuthPayload {
  source?: string
  provider?: PortableProvider
  status?: 'success' | 'error'
  message?: string
  sessionToken?: string
}

const AUTH_SESSION_TOKEN_KEY = 'familyone_auth_session_token'

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function getAuthSessionToken(): string {
  const storage = getSessionStorage()
  if (!storage) return ''
  try {
    return storage.getItem(AUTH_SESSION_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function clearAuthSessionToken(): void {
  const storage = getSessionStorage()
  if (!storage) return
  try {
    storage.removeItem(AUTH_SESSION_TOKEN_KEY)
  } catch {
    // ignore storage cleanup failures
  }
}

function saveAuthSessionToken(token: string | undefined): void {
  const normalized = String(token || '').trim()
  if (!normalized) return
  const storage = getSessionStorage()
  if (!storage) return
  try {
    storage.setItem(AUTH_SESSION_TOKEN_KEY, normalized)
  } catch {
    // ignore storage write failures
  }
}

function openProviderPopup(url: string, provider: PortableProvider): Promise<string> {
  return new Promise((resolve, reject) => {
    const popup = window.open(
      url,
      `familyone-${provider}-auth`,
      'width=560,height=760,resizable=yes,scrollbars=yes'
    )

    if (!popup) {
      reject(new Error('Браузер заблокировал окно авторизации'))
      return
    }

    let finished = false
    const cleanup = () => {
      window.removeEventListener('message', onMessage)
      window.clearInterval(closeWatcher)
      window.clearTimeout(timeoutId)
    }

    const finish = (callback: () => void) => {
      if (finished) return
      finished = true
      cleanup()
      callback()
    }

    const onMessage = (event: MessageEvent<PopupAuthPayload>) => {
      const payload = event.data
      if (!payload || payload.source !== 'familyone-auth' || payload.provider !== provider) {
        return
      }

      finish(() => {
        if (payload.status === 'success') {
          saveAuthSessionToken(payload.sessionToken)
          resolve(payload.message || 'Авторизация завершена')
          return
        }
        reject(new Error(payload.message || 'Не удалось завершить вход'))
      })
    }

    const closeWatcher = window.setInterval(() => {
      if (popup.closed) {
        finish(() => reject(new Error('Окно авторизации закрыто до завершения входа')))
      }
    }, 400)

    const timeoutId = window.setTimeout(() => {
      finish(() => reject(new Error('Превышено время ожидания ответа от окна авторизации')))
    }, 180000)

    window.addEventListener('message', onMessage)
  })
}

export function connectYandexIdentity(deviceId: string | number): Promise<string> {
  const normalizedDeviceId = String(deviceId || '').trim()
  if (!normalizedDeviceId) {
    return Promise.reject(new Error('Device ID не инициализирован'))
  }
  const url = `${getApiBaseUrl()}/v2/auth/yandex/start?device_id=${encodeURIComponent(normalizedDeviceId)}`
  return openProviderPopup(url, 'yandex')
}

export function connectVkIdentity(): Promise<string> {
  return Promise.reject(new Error('VK ID пока не настроен на сервере'))
}
