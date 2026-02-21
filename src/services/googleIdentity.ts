interface OAuthPopupMessage {
  type: string
  id_token?: string
  access_token?: string
  state?: string
  error?: string
  error_description?: string
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        oauth2?: {
          revoke(token: string, callback?: () => void): void
        }
      }
    }
  }
}

const GOOGLE_SCRIPT_ID = 'google-identity-services-script'
const GOOGLE_SCRIPT_URL = 'https://accounts.google.com/gsi/client'
const OAUTH_POPUP_MESSAGE = 'familyone_google_oauth_popup'
const OAUTH_POPUP_PATH = '/google-oauth-popup.html'

let loaded = false

export function getGoogleClientId(): string {
  return String(import.meta.env.VITE_GOOGLE_WEB_CLIENT_ID || '').trim()
}

export async function ensureGoogleIdentityLoaded(): Promise<void> {
  if (loaded) return

  await new Promise<void>((resolve, reject) => {
    const existing = document.getElementById(GOOGLE_SCRIPT_ID) as HTMLScriptElement | null
    if (existing) {
      loaded = true
      resolve()
      return
    }

    const script = document.createElement('script')
    script.id = GOOGLE_SCRIPT_ID
    script.src = GOOGLE_SCRIPT_URL
    script.async = true
    script.defer = true
    script.onload = () => {
      loaded = true
      resolve()
    }
    script.onerror = () => reject(new Error('Не удалось загрузить Google Identity Services'))

    document.head.appendChild(script)
  })
}

function randomState(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes)
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

function buildOAuthPopupUrl(clientId: string, state: string, nonce: string): string {
  const redirectUri = `${window.location.origin}${OAUTH_POPUP_PATH}`
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'id_token token',
    scope: 'openid email profile',
    prompt: 'select_account',
    include_granted_scopes: 'true',
    state,
    nonce
  })
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`
}

function withFallbackReason(base: string, fallbackReason: string): string {
  if (!fallbackReason) return base
  return `${base}. Причина fallback: ${fallbackReason}`
}

function signInWithOAuthRedirect(clientId: string, fallbackReason: string): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const state = randomState()
    const nonce = randomState()

    const popup = window.open(
      buildOAuthPopupUrl(clientId, state, nonce),
      'familyone_google_oauth',
      'width=520,height=720,menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes'
    )

    if (!popup) {
      reject(new Error(withFallbackReason('Браузер заблокировал popup авторизации Google', fallbackReason)))
      return
    }

    let settled = false
    let closeWatcher = 0
    let timeout = 0

    const cleanup = (): void => {
      if (closeWatcher) window.clearInterval(closeWatcher)
      if (timeout) window.clearTimeout(timeout)
      window.removeEventListener('message', onMessage)
    }

    const fail = (message: string): void => {
      if (settled) return
      settled = true
      cleanup()
      reject(new Error(withFallbackReason(message, fallbackReason)))
    }

    const onMessage = (event: MessageEvent): void => {
      if (event.origin !== window.location.origin) return
      const payload = event.data as OAuthPopupMessage | undefined
      if (!payload || payload.type !== OAUTH_POPUP_MESSAGE) return

      if (payload.state !== state) {
        fail('Google OAuth отклонён из-за state mismatch')
        return
      }

      if (payload.error) {
        const details = payload.error_description || payload.error
        if (payload.error === 'redirect_uri_mismatch') {
          fail(
            `Google OAuth ошибка: redirect_uri_mismatch. Добавьте ${window.location.origin}${OAUTH_POPUP_PATH} в Authorized redirect URIs`
          )
          return
        }

        fail(`Google OAuth ошибка: ${details}`)
        return
      }

      const token = payload.id_token || payload.access_token
      if (!token) {
        fail('Google OAuth popup не вернул id/access token')
        return
      }

      settled = true
      cleanup()
      resolve(token)
    }

    window.addEventListener('message', onMessage)

    closeWatcher = window.setInterval(() => {
      try {
        if (popup.closed && !settled) {
          fail('Окно Google OAuth закрыто до завершения входа')
        }
      } catch {
        // COOP может блокировать popup.closed, продолжаем ждать postMessage.
      }
    }, 400)

    timeout = window.setTimeout(() => {
      fail('Google OAuth popup timeout')
    }, 120000)
  })
}

export async function signInWithGooglePopup(): Promise<string> {
  const clientId = getGoogleClientId()
  if (!clientId) {
    throw new Error('VITE_GOOGLE_WEB_CLIENT_ID не задан')
  }

  try {
    await ensureGoogleIdentityLoaded()
  } catch {
    // GIS script не обязателен для popup OAuth.
  }

  return signInWithOAuthRedirect(clientId, '')
}

export function signOutGoogle(token = ''): void {
  if (token && window.google?.accounts?.oauth2?.revoke) {
    window.google.accounts.oauth2.revoke(token, () => undefined)
  }
}
