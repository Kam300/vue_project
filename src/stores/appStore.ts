import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AuthBootstrapResponse, AuthIdentityResponse } from '@/types/api'
import type { AppSettingsState } from '@/types/models'
import { DEFAULT_APP_SETTINGS, getAppSettings, patchAppSettings } from '@/db/repositories'
import { authBootstrap, setApiBaseUrl } from '@/services/api'
import { sha256FromString } from '@/utils/crypto'

const SESSION_STORAGE_KEYS = {
  lockUnlocked: 'familyone_lock_unlocked'
} as const

function getSessionStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function readSessionValue(key: string): string {
  const storage = getSessionStorage()
  if (!storage) return ''
  try {
    return storage.getItem(key) || ''
  } catch {
    return ''
  }
}

function writeSessionValue(key: string, value: string): void {
  const storage = getSessionStorage()
  if (!storage) return

  try {
    if (value) {
      storage.setItem(key, value)
      return
    }
    storage.removeItem(key)
  } catch {
    // ignore storage write failures
  }
}

export const useAppStore = defineStore('app', () => {
  const settings = ref<AppSettingsState>({ ...DEFAULT_APP_SETTINGS })
  const initialized = ref(false)
  const sessionUnlocked = ref(false)
  const authProviders = ref<AuthBootstrapResponse['providers'] | null>(null)
  const authUser = ref<AuthBootstrapResponse['auth']['user']>(null)

  const requiresOnboarding = computed(
    () => !settings.value.onboardingCompleted || !settings.value.privacyConsented
  )
  const requiresLock = computed(
    () => settings.value.pinEnabled && settings.value.appLockBySession && !sessionUnlocked.value
  )
  const portableIdentity = computed<AuthIdentityResponse | null>(() => {
    const providers = authUser.value?.providers || []
    return providers.find((provider) => provider.provider !== 'local') || null
  })

  function applyTheme(theme: AppSettingsState['theme']): void {
    const root = document.documentElement
    if (theme === 'system') {
      root.removeAttribute('data-theme')
      return
    }
    root.setAttribute('data-theme', theme)
  }

  function syncLockSessionStorage(): void {
    if (!settings.value.pinEnabled || !settings.value.appLockBySession) {
      writeSessionValue(SESSION_STORAGE_KEYS.lockUnlocked, '')
      return
    }
    writeSessionValue(SESSION_STORAGE_KEYS.lockUnlocked, sessionUnlocked.value ? '1' : '')
  }

  async function refreshAuthState(displayName = 'FamilyOne Web'): Promise<AuthBootstrapResponse | null> {
    const deviceId = String(settings.value.deviceId || '').trim()
    if (!deviceId) {
      authProviders.value = null
      authUser.value = null
      return null
    }

    const snapshot = await authBootstrap({
      deviceId,
      displayName
    })
    authProviders.value = snapshot.providers
    authUser.value = snapshot.auth.user
    return snapshot
  }

  async function init(): Promise<void> {
    settings.value = await getAppSettings()
    setApiBaseUrl(settings.value.apiBaseUrl || DEFAULT_APP_SETTINGS.apiBaseUrl)
    applyTheme(settings.value.theme)

    if (!settings.value.pinEnabled || !settings.value.appLockBySession) {
      sessionUnlocked.value = true
      syncLockSessionStorage()
    } else {
      sessionUnlocked.value = readSessionValue(SESSION_STORAGE_KEYS.lockUnlocked) === '1'
    }

    initialized.value = true

    try {
      await refreshAuthState()
    } catch {
      authProviders.value = null
      authUser.value = null
    }
  }

  async function updateSettings(patch: Partial<AppSettingsState>): Promise<void> {
    settings.value = await patchAppSettings(patch)
    if (patch.apiBaseUrl !== undefined) {
      setApiBaseUrl(settings.value.apiBaseUrl)
    }
    if (patch.theme !== undefined) {
      applyTheme(settings.value.theme)
    }
    syncLockSessionStorage()
  }

  async function completeOnboarding(): Promise<void> {
    await updateSettings({
      onboardingCompleted: true,
      privacyConsented: true
    })
  }

  async function setPin(pin: string): Promise<void> {
    const pinHash = pin ? await sha256FromString(pin) : ''
    await updateSettings({
      pinEnabled: Boolean(pin),
      pinHash,
      appLockBySession: Boolean(pin)
    })
    sessionUnlocked.value = Boolean(pin)
    syncLockSessionStorage()
  }

  async function setPinToggle(enabled: boolean): Promise<void> {
    await updateSettings({ pinEnabled: enabled, appLockBySession: enabled })
    if (!enabled) {
      sessionUnlocked.value = true
    }
    syncLockSessionStorage()
  }

  async function verifyPin(pin: string): Promise<boolean> {
    const hash = await sha256FromString(pin)
    const ok = hash === settings.value.pinHash
    if (ok) {
      sessionUnlocked.value = true
      syncLockSessionStorage()
    }
    return ok
  }

  function lockSession(): void {
    if (settings.value.pinEnabled && settings.value.appLockBySession) {
      sessionUnlocked.value = false
      syncLockSessionStorage()
    }
  }

  return {
    settings,
    initialized,
    sessionUnlocked,
    requiresOnboarding,
    requiresLock,
    authProviders,
    authUser,
    portableIdentity,
    init,
    refreshAuthState,
    updateSettings,
    completeOnboarding,
    setPin,
    setPinToggle,
    verifyPin,
    lockSession
  }
})
