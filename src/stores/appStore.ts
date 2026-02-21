import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AppSettingsState } from '@/types/models'
import { DEFAULT_APP_SETTINGS, getAppSettings, patchAppSettings } from '@/db/repositories'
import { setApiBaseUrl } from '@/services/api'
import { sha256FromString } from '@/utils/crypto'

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

  async function init(): Promise<void> {
    settings.value = await getAppSettings()
    setApiBaseUrl(settings.value.apiBaseUrl || DEFAULT_APP_SETTINGS.apiBaseUrl)
    applyTheme(settings.value.theme)
    initialized.value = true
    sessionUnlocked.value = !settings.value.pinEnabled || !settings.value.appLockBySession
  }

  async function updateSettings(patch: Partial<AppSettingsState>): Promise<void> {
    settings.value = await patchAppSettings(patch)
    if (patch.apiBaseUrl !== undefined) {
      setApiBaseUrl(settings.value.apiBaseUrl)
    }
    if (patch.theme !== undefined) {
      applyTheme(settings.value.theme)
    }
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
  }

  async function setPinToggle(enabled: boolean): Promise<void> {
    await updateSettings({ pinEnabled: enabled, appLockBySession: enabled })
    if (!enabled) {
      sessionUnlocked.value = true
    }
  }

  async function verifyPin(pin: string): Promise<boolean> {
    const hash = await sha256FromString(pin)
    const ok = hash === settings.value.pinHash
    if (ok) {
      sessionUnlocked.value = true
    }
    return ok
  }

  function lockSession(): void {
    if (settings.value.pinEnabled && settings.value.appLockBySession) {
      sessionUnlocked.value = false
    }
  }

  function setGoogleToken(token: string, accountLabel = ''): void {
    googleIdToken.value = token
    googleAccountLabel.value = accountLabel
  }

  function clearGoogleToken(): void {
    googleIdToken.value = ''
    googleAccountLabel.value = ''
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
