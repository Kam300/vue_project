<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import LandingPage from '@/components/LandingPage.vue'
import { useAppStore } from '@/stores/appStore'
import { ensureGoogleIdentityLoaded, getGoogleClientId, signInWithGooglePopup } from '@/services/googleIdentity'

const appStore = useAppStore()
const router = useRouter()

const authBusy = ref(false)
const authError = ref('')
const authStatus = ref('')

const hasGoogleClientId = computed(() => Boolean(getGoogleClientId()))
const isAuthorized = computed(() => Boolean(appStore.googleIdToken))

async function signInGoogleFromLanding(): Promise<void> {
  authError.value = ''
  authStatus.value = ''

  if (!hasGoogleClientId.value) {
    authError.value = 'Google OAuth не настроен. Укажите VITE_GOOGLE_WEB_CLIENT_ID.'
    return
  }

  authBusy.value = true
  try {
    await ensureGoogleIdentityLoaded()
    const token = await signInWithGooglePopup()
    appStore.setGoogleToken(token, 'Google account')
    authStatus.value = 'Авторизация выполнена. Можно делать backup и восстановление.'
    await router.push('/app/backup')
  } catch (reason) {
    authError.value = `Вход не выполнен: ${(reason as Error).message || 'Unknown error'}`
  } finally {
    authBusy.value = false
  }
}
</script>

<template>
  <div class="landing-wrap">
    <LandingPage />

    <button
      v-if="!isAuthorized"
      class="google-auth-btn"
      @click="signInGoogleFromLanding"
      :disabled="authBusy || !hasGoogleClientId"
    >
      <span class="google-mark">G</span>
      {{
        authBusy ? 'Авторизация...' : 'Авторизоваться для backup'
      }}
    </button>

    <p v-if="authStatus" class="auth-state ok">{{ authStatus }}</p>
    <p v-else-if="authError" class="auth-state err">{{ authError }}</p>

    <a class="apk-download-btn" href="/app-debug.apk" download="app-debug.apk">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <rect x="7" y="2" width="10" height="20" rx="2" />
        <line x1="12" y1="18" x2="12.01" y2="18" />
      </svg>
      Скачать Android APK
    </a>

    <RouterLink class="open-app-btn" to="/app/members">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
      Открыть web-приложение
    </RouterLink>
  </div>
</template>

<style scoped>
.google-auth-btn {
  position: fixed;
  right: 16px;
  bottom: 140px;
  z-index: 320;
  text-decoration: none;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  padding: 12px 18px;
  font-size: 0.88rem;
  font-weight: 600;
  font-family: var(--font-sans);
  color: var(--color-text);
  background: color-mix(in srgb, var(--color-bg-alt) 92%, transparent);
  backdrop-filter: blur(12px);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all var(--transition-normal);
  cursor: pointer;
}

.google-auth-btn:hover:not(:disabled) {
  border-color: rgba(124, 92, 252, 0.45);
  background: color-mix(in srgb, var(--color-bg-alt) 98%, transparent);
  transform: translateY(-2px);
}

.google-auth-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.google-mark {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #fff;
  color: #4285f4;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  font-weight: 700;
  line-height: 1;
}

.auth-state {
  position: fixed;
  right: 16px;
  bottom: 194px;
  z-index: 320;
  max-width: min(480px, calc(100vw - 32px));
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 0.8rem;
  line-height: 1.35;
  border: 1px solid var(--color-glass-border);
  background: color-mix(in srgb, var(--color-bg-alt) 94%, transparent);
}

.auth-state.ok {
  color: var(--color-success);
}

.auth-state.err {
  color: var(--color-error);
}

.apk-download-btn {
  position: fixed;
  right: 16px;
  bottom: 78px;
  z-index: 300;
  text-decoration: none;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  padding: 12px 20px;
  font-size: 0.88rem;
  font-weight: 600;
  font-family: var(--font-sans);
  color: var(--color-text);
  background: color-mix(in srgb, var(--color-bg-alt) 88%, transparent);
  backdrop-filter: blur(12px);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all var(--transition-normal);
}

.apk-download-btn:hover {
  border-color: rgba(124, 92, 252, 0.45);
  background: color-mix(in srgb, var(--color-bg-alt) 95%, transparent);
  transform: translateY(-2px);
}

.open-app-btn {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 300;
  text-decoration: none;
  border-radius: 999px;
  border: none;
  padding: 14px 26px;
  font-size: 0.92rem;
  font-weight: 600;
  font-family: var(--font-sans);
  color: #fff;
  background: var(--gradient-accent);
  box-shadow: 0 4px 24px rgba(124, 92, 252, 0.4);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all var(--transition-normal);
  animation: pulse-glow 3s ease-in-out infinite;
}

.open-app-btn:hover {
  background: var(--gradient-accent-hover);
  box-shadow: 0 6px 32px rgba(124, 92, 252, 0.55);
  transform: translateY(-3px);
}

@media (max-width: 680px) {
  .google-auth-btn {
    right: 12px;
    bottom: 122px;
    padding: 9px 14px;
    font-size: 0.8rem;
    gap: 6px;
  }

  .apk-download-btn {
    right: 12px;
    bottom: 70px;
    padding: 9px 14px;
    font-size: 0.8rem;
    gap: 6px;
  }

  .open-app-btn {
    right: 12px;
    bottom: 12px;
    padding: 10px 18px;
    font-size: 0.84rem;
    gap: 6px;
  }

  .google-mark {
    width: 17px;
    height: 17px;
    font-size: 0.76rem;
  }

  .auth-state {
    right: 12px;
    bottom: 170px;
    left: auto;
    max-width: min(280px, calc(100vw - 24px));
  }
}

@media (max-width: 400px) {
  /* На очень узких экранах — только иконка + короткий текст */
  .google-auth-btn .btn-text::after {
    content: 'Google';
  }
}
</style>

