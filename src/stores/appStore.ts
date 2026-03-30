import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AppSettingsState } from '@/types/models'
import { DEFAULT_APP_SETTINGS, getAppSettings, patchAppSettings } from '@/db/repositories'
import { setApiBaseUrl } from '@/services/api'
import { sha256FromString } from '@/utils/crypto'

const SESSION_STORAGE_KEYS = {
  lockUnlocked: 'familyone_lock_unlocked',
  googleToken: 'familyone_google_token',
  googleAccountLabel: 'familyone_google_account_label'
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
    // ignore storage write failures (private mode, blocked storage)
  }
}

export const useAppStore = defineStore('app', () => {
  const settings = ref<AppSettingsState>({ ...DEFAULT_APP_SETTINGS })
  const initialized = ref(false)
  const sessionUnlocked = ref(false)
  const googleIdToken = ref('')
  const googleAccountLabel = ref('')

  const requiresOnboarding = computed(
    () => !settings.value.onboardingCompleted || !settings.value.privacyConsented
  )
  const requiresLock = computed(
    () => settings.value.pinEnabled && settings.value.appLockBySession && !sessionUnlocked.value
  )

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

  function syncGoogleSessionStorage(): void {
    writeSessionValue(SESSION_STORAGE_KEYS.googleToken, googleIdToken.value)
    writeSessionValue(SESSION_STORAGE_KEYS.googleAccountLabel, googleAccountLabel.value)
  }

  async function init(): Promise<void> {
    settings.value = await getAppSettings()
    setApiBaseUrl(settings.value.apiBaseUrl || DEFAULT_APP_SETTINGS.apiBaseUrl)
    applyTheme(settings.value.theme)
    googleIdToken.value = readSessionValue(SESSION_STORAGE_KEYS.googleToken)
    googleAccountLabel.value = readSessionValue(SESSION_STORAGE_KEYS.googleAccountLabel)

    if (!settings.value.pinEnabled || !settings.value.appLockBySession) {
      sessionUnlocked.value = true
      syncLockSessionStorage()
    } else {
      sessionUnlocked.value = readSessionValue(SESSION_STORAGE_KEYS.lockUnlocked) === '1'
    }

    initialized.value = true
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

  function setGoogleToken(token: string, accountLabel = ''): void {
    googleIdToken.value = String(token || '').trim()
    googleAccountLabel.value = accountLabel
    syncGoogleSessionStorage()
  }

  function clearGoogleToken(): void {
    googleIdToken.value = ''
    googleAccountLabel.value = ''
    syncGoogleSessionStorage()
  }

  return {
    settings,
    initialized,
    sessionUnlocked,
    requiresOnboarding,
    requiresLock,
    googleIdToken,
    googleAccountLabel,
    init,
    updateSettings,
    completeOnboarding,
    setPin,
    setPinToggle,
    verifyPin,
    lockSession,
    setGoogleToken,
    clearGoogleToken
  }
})
