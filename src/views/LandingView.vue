<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import LandingPage from '@/components/LandingPage.vue'
import YandexIdButton from '@/components/shared/YandexIdButton.vue'
import SyncProgress from '@/components/shared/SyncProgress.vue'
import { connectPortableIdentityAndSync } from '@/services/portableIdentitySync'
import { authLogout } from '@/services/api'
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
const logoutBusy = ref(false)
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
  authProgressLabel.value = 'Подготовка...'

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

async function disconnectPortableIdentity(): Promise<void> {
  if (!confirm('Отключить Яндекс ID? Локальные данные останутся, но пропадёт связка с серверным backup.')) return
  logoutBusy.value = true
  authError.value = ''
  authStatus.value = ''
  try {
    await authLogout().catch(() => {})
    await appStore.refreshAuthState()
    authStatus.value = 'Яндекс ID отключён'
  } catch (reason) {
    authError.value = `Не удалось отключить: ${(reason as Error).message || 'unknown error'}`
  } finally {
    logoutBusy.value = false
  }
}

onMounted(() => {
  void ensureLandingAuthReady()
})
</script>

<template>
  <div class="landing-wrap">
    <LandingPage>
      <template #hero-accessory>
        <aside class="portable-auth-box" :class="{ 'is-connected': hasPortableIdentity }">
          <template v-if="!hasPortableIdentity">
            <p class="portable-auth-title">Подключите вход для переноса backup между устройствами</p>
            <p v-if="authInitBusy" class="portable-auth-hint">Проверяем доступные способы входа...</p>

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
                {{ authBusy === 'vk' ? 'Подключение...' : 'Войти с VK ID' }}
              </button>
            </div>

            <SyncProgress
              :visible="Boolean(authBusy)"
              :progress="authProgress"
              :label="authProgressLabel"
            />
          </template>

          <template v-else>
            <div class="portable-auth-connected">
              <span class="portable-auth-check">✓</span>
              <div>
                <p class="portable-auth-title">{{ portableIdentityTitle }}</p>
                <p v-if="portableIdentityName" class="portable-auth-username">{{ portableIdentityName }}</p>
              </div>
            </div>

            <div class="portable-auth-actions">
              <RouterLink to="/app/members" class="portable-auth-btn portable-auth-btn-primary">
                Открыть приложение
              </RouterLink>
              <button
                class="portable-auth-btn portable-auth-btn-ghost"
                @click="disconnectPortableIdentity"
                :disabled="logoutBusy"
              >
                {{ logoutBusy ? 'Отключаем...' : 'Выйти' }}
              </button>
            </div>
          </template>

          <p v-if="authStatus" class="portable-auth-status ok">{{ authStatus }}</p>
          <p v-if="authError" class="portable-auth-status err">{{ authError }}</p>
        </aside>

        <div class="floating-cta-stack">
          <a class="apk-download-btn" href="/Семейное древо.apk" download="Семейное древо.apk">
            Скачать Семейное древо.apk
          </a>

          <RouterLink v-if="!hasPortableIdentity" class="open-app-btn" to="/app/members">
            Открыть web-приложение
          </RouterLink>
        </div>
      </template>
    </LandingPage>
  </div>
</template>

<style scoped>
.landing-wrap {
  overflow-x: clip;
}

.portable-auth-box {
  position: fixed;
  right: 16px;
  bottom: 132px;
  z-index: 320;
  width: min(404px, calc(100vw - 32px));
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid var(--color-glass-border);
  background: rgba(11, 14, 23, 0.92);
  background: color-mix(in srgb, var(--color-bg-alt) 92%, transparent);
  -webkit-backdrop-filter: blur(18px);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-elevated);
  transition: border-color 0.25s ease, background 0.25s ease;
}

.portable-auth-box.is-connected {
  right: 16px;
  bottom: 92px;
  width: min(360px, calc(100vw - 32px));
  padding: 14px;
  border-color: rgba(52, 211, 153, 0.4);
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--color-bg-alt) 92%, transparent),
    rgba(52, 211, 153, 0.08)
  );
}

.portable-auth-box.is-connected .portable-auth-actions {
  gap: 8px;
}

.portable-auth-box.is-connected .portable-auth-btn {
  min-height: 44px;
  border-radius: 14px;
  padding: 9px 12px;
  font-size: 0.86rem;
}

.portable-auth-box.is-connected .portable-auth-title {
  font-size: 0.9rem;
}

.portable-auth-connected {
  display: flex;
  align-items: center;
  gap: 12px;
}

.portable-auth-check {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
  font-weight: 700;
  font-size: 1.1rem;
  border: 1px solid rgba(52, 211, 153, 0.4);
}

.portable-auth-username {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.portable-auth-btn-primary {
  background: var(--gradient-accent);
  color: #fff;
  border-color: transparent;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.portable-auth-btn-primary:hover:not(:disabled) {
  background: var(--gradient-accent-hover);
  box-shadow: 0 6px 20px rgba(124, 92, 252, 0.35);
}

.portable-auth-btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
}

.portable-auth-btn-ghost:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.4);
  color: #f87171;
  background: rgba(248, 113, 113, 0.08);
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
  line-height: 1.45;
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
  align-items: stretch;
}

.portable-auth-btn {
  min-height: 48px;
  border-radius: 16px;
  border: 1px solid var(--color-glass-border);
  background: rgba(22, 27, 41, 0.94);
  background: color-mix(in srgb, var(--color-surface) 94%, transparent);
  color: var(--color-text);
  font: inherit;
  font-size: 0.92rem;
  font-weight: 600;
  padding: 10px 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  white-space: nowrap;
  line-height: 1.2;
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
  background: rgba(11, 14, 23, 0.88);
  background: color-mix(in srgb, var(--color-bg-alt) 88%, transparent);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
  transition: all var(--transition-normal);
}

.apk-download-btn:hover {
  border-color: rgba(124, 92, 252, 0.45);
  background: rgba(11, 14, 23, 0.95);
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
    position: relative;
    right: auto;
    left: auto;
    bottom: auto;
    z-index: auto;
    width: 100%;
    margin: 0;
    padding: 14px;
  }

  .portable-auth-actions {
    grid-template-columns: 1fr;
  }

  .floating-cta-stack {
    position: relative;
    right: auto;
    bottom: auto;
    z-index: auto;
    width: 100%;
    margin-top: 14px;
  }

  .apk-download-btn,
  .open-app-btn {
    padding: 10px 18px;
    font-size: 0.84rem;
  }
}
</style>
