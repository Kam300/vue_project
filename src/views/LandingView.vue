<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import LandingPage from '@/components/LandingPage.vue'
import YandexIdButton from '@/components/shared/YandexIdButton.vue'
import SyncProgress from '@/components/shared/SyncProgress.vue'
import { connectPortableIdentityAndSync } from '@/services/portableIdentitySync'
import { useAppStore } from '@/stores/appStore'

const appStore = useAppStore()
const router = useRouter()

const authBusy = ref<'yandex' | 'vk' | ''>('')
const authError = ref('')
const authStatus = ref('')
const authProgress = ref(0)
const authProgressLabel = ref('')
const authReady = ref(false)
const authInitBusy = ref(false)

const yandexConfigured = computed(() => Boolean(appStore.authProviders?.yandex?.configured))
const vkConfigured = computed(() => Boolean(appStore.authProviders?.vk?.configured))
const hasPortableIdentity = computed(() => Boolean(appStore.portableIdentity))
const portableIdentityTitle = computed(() => {
  if (!appStore.portableIdentity) return ''
  return appStore.portableIdentity.provider === 'yandex' ? 'Яндекс ID подключен' : 'VK ID подключён'
})
const portableIdentityName = computed(
  () => appStore.portableIdentity?.displayName || appStore.authUser?.displayName || ''
)

async function ensureLandingAuthReady(): Promise<void> {
  if (authReady.value || authInitBusy.value) return

  authInitBusy.value = true
  authError.value = ''
  try {
    if (!appStore.initialized) {
      await appStore.init()
    } else if (!appStore.authProviders) {
      await appStore.refreshAuthState()
    }
    authReady.value = true
  } catch (reason) {
    authError.value = `Не удалось подготовить вход: ${(reason as Error).message || 'unknown error'}`
  } finally {
    authInitBusy.value = false
  }
}

async function connectPortableIdentity(provider: 'yandex' | 'vk'): Promise<void> {
  await ensureLandingAuthReady()
  if (!authReady.value) return

  authBusy.value = provider
  authError.value = ''
  authStatus.value = ''
  authProgress.value = 0
  authProgressLabel.value = 'Подготовка…'

  try {
    authStatus.value = await connectPortableIdentityAndSync(provider, {
      onProgress(step) {
        authProgress.value = step.progress
        authProgressLabel.value = step.message
      }
    })
    await router.push('/app/backup')
  } catch (reason) {
    authError.value = `Не удалось завершить вход: ${(reason as Error).message || 'unknown error'}`
  } finally {
    authBusy.value = ''
  }
}

onMounted(() => {
  void ensureLandingAuthReady()
})
</script>

<template>
  <div class="landing-wrap">
    <LandingPage />

    <aside class="portable-auth-box">
      <p class="portable-auth-title">Подключите вход для переноса backup между устройствами</p>
      <p v-if="authInitBusy" class="portable-auth-hint">Проверяем доступные способы входа…</p>
      <p v-else-if="hasPortableIdentity" class="portable-auth-status ok">
        {{ portableIdentityTitle }}
        <span v-if="portableIdentityName">{{ portableIdentityName }}</span>
      </p>

      <span class="portable-auth-label">Войти с помощью</span>
      <div class="portable-auth-actions">
        <YandexIdButton
          class="portable-auth-btn portable-auth-btn-yandex"
          @click="connectPortableIdentity('yandex')"
          :disabled="authInitBusy || Boolean(authBusy) || !yandexConfigured"
          :loading="authBusy === 'yandex'"
        />
        <button
          class="portable-auth-btn portable-auth-btn-vk"
          @click="connectPortableIdentity('vk')"
          :disabled="authInitBusy || Boolean(authBusy) || !vkConfigured"
        >
          {{ authBusy === 'vk' ? 'Подключение…' : 'Войти с VK ID' }}
        </button>
      </div>

      <SyncProgress
        :visible="Boolean(authBusy)"
        :progress="authProgress"
        :label="authProgressLabel"
      />

      <p v-if="authStatus" class="portable-auth-status ok">{{ authStatus }}</p>
      <p v-if="authError" class="portable-auth-status err">{{ authError }}</p>
    </aside>

    <div class="floating-cta-stack">
      <a class="apk-download-btn" href="/app-debug.apk" download="app-debug.apk">
        Скачать Android APK
      </a>

      <RouterLink class="open-app-btn" to="/app/members">
        Открыть web-приложение
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.portable-auth-box {
  position: fixed;
  right: 16px;
  bottom: 132px;
  z-index: 320;
  width: min(420px, calc(100vw - 32px));
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid var(--color-glass-border);
  background: color-mix(in srgb, var(--color-bg-alt) 92%, transparent);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-elevated);
}

.portable-auth-label {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  font-size: 0.72rem;
  line-height: 1;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-text-muted);
}

.portable-auth-title {
  margin: 0;
  font-size: 0.95rem;
  line-height: 1.5;
  color: var(--color-text);
  font-weight: 600;
}

.portable-auth-hint,
.portable-auth-status {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.45;
}

.portable-auth-hint {
  color: var(--color-text-muted);
}

.portable-auth-status.ok {
  color: var(--color-success);
}

.portable-auth-status.err {
  color: var(--color-error);
}

.portable-auth-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.portable-auth-btn {
  min-height: 44px;
  border-radius: 16px;
  border: 1px solid var(--color-glass-border);
  background: color-mix(in srgb, var(--color-surface) 94%, transparent);
  color: var(--color-text);
  font: inherit;
  font-weight: 600;
  padding: 0 16px;
  cursor: pointer;
  transition:
    transform var(--transition-normal),
    border-color var(--transition-normal),
    background var(--transition-normal),
    box-shadow var(--transition-normal);
}

.portable-auth-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.16);
}

.portable-auth-btn-vk {
  color: rgba(244, 247, 255, 0.96);
}

.portable-auth-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.floating-cta-stack {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 300;
  width: min(260px, calc(100vw - 32px));
  display: grid;
  gap: 10px;
}

.apk-download-btn {
  text-decoration: none;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  min-height: 48px;
  padding: 12px 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 0.88rem;
  font-weight: 600;
  font-family: var(--font-sans);
  color: var(--color-text);
  background: color-mix(in srgb, var(--color-bg-alt) 88%, transparent);
  backdrop-filter: blur(12px);
  transition: all var(--transition-normal);
}

.apk-download-btn:hover {
  border-color: rgba(124, 92, 252, 0.45);
  background: color-mix(in srgb, var(--color-bg-alt) 95%, transparent);
  transform: translateY(-2px);
}

.open-app-btn {
  text-decoration: none;
  border-radius: 999px;
  border: none;
  min-height: 52px;
  padding: 14px 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 0.92rem;
  font-weight: 600;
  font-family: var(--font-sans);
  color: #fff;
  background: var(--gradient-accent);
  box-shadow: 0 4px 24px rgba(124, 92, 252, 0.4);
  transition: all var(--transition-normal);
}

.open-app-btn:hover {
  background: var(--gradient-accent-hover);
  box-shadow: 0 6px 32px rgba(124, 92, 252, 0.55);
  transform: translateY(-3px);
}

@media (max-width: 680px) {
  .portable-auth-box {
    right: 12px;
    left: 12px;
    bottom: 136px;
    width: auto;
    padding: 14px;
  }

  .portable-auth-actions {
    grid-template-columns: 1fr;
  }

  .floating-cta-stack {
    right: 12px;
    bottom: 12px;
    width: calc(100vw - 24px);
  }

  .apk-download-btn,
  .open-app-btn {
    padding: 10px 18px;
    font-size: 0.84rem;
  }
}
</style>
