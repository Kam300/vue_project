<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import LandingPage from '@/components/LandingPage.vue'
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

      <div class="portable-auth-actions">
        <button
          class="portable-auth-btn"
          @click="connectPortableIdentity('yandex')"
          :disabled="authInitBusy || Boolean(authBusy) || !yandexConfigured"
        >
          {{ authBusy === 'yandex' ? 'Подключение…' : 'Подключить Яндекс ID' }}
        </button>
        <button
          class="portable-auth-btn secondary"
          @click="connectPortableIdentity('vk')"
          :disabled="authInitBusy || Boolean(authBusy) || !vkConfigured"
        >
          {{ authBusy === 'vk' ? 'Подключение…' : 'Подключить VK ID' }}
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

    <a class="apk-download-btn" href="/app-debug.apk" download="app-debug.apk">
      Скачать Android APK
    </a>

    <RouterLink class="open-app-btn" to="/app/members">
      Открыть web-приложение
    </RouterLink>
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
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.portable-auth-btn {
  flex: 1 1 180px;
  min-height: 46px;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  background: color-mix(in srgb, var(--color-surface) 90%, transparent);
  color: var(--color-text);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: transform var(--transition-normal), border-color var(--transition-normal),
    background var(--transition-normal);
}

.portable-auth-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(124, 92, 252, 0.45);
}

.portable-auth-btn.secondary {
  opacity: 0.92;
}

.portable-auth-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.apk-download-btn {
  position: fixed;
  right: 16px;
  bottom: 70px;
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
    bottom: 116px;
    width: auto;
    padding: 14px;
  }

  .apk-download-btn {
    right: 12px;
    bottom: 64px;
    padding: 10px 16px;
  }

  .open-app-btn {
    right: 12px;
    bottom: 12px;
    padding: 10px 18px;
    font-size: 0.84rem;
  }
}
</style>
