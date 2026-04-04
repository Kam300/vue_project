<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/shared/AppIcon.vue'
import SyncProgress from '@/components/shared/SyncProgress.vue'
import YandexIdButton from '@/components/shared/YandexIdButton.vue'
import { connectPortableIdentityAndSync } from '@/services/portableIdentitySync'
import { useAppStore } from '@/stores/appStore'
import { APP_LOGO_COMPACT_URL } from '@/constants/branding'

const appStore = useAppStore()
const router = useRouter()
const logoIcon = APP_LOGO_COMPACT_URL

const page = ref(0)
const consent = ref(false)
const enablePin = ref(false)
const pin = ref('')
const pinConfirm = ref('')
const error = ref('')
const direction = ref<'next' | 'prev'>('next')
const authBusy = ref<'yandex' | 'vk' | ''>('')
const authError = ref('')
const authStatus = ref('')
const authProgress = ref(0)
const authProgressLabel = ref('')
const privacyContactUrl = 'https://t.me/TotalC0de'

const privacyPolicyItems = [
  {
    title: 'Кратко о данных',
    text: 'В SQL-базе и локальном хранилище сохраняются профили людей, связи, фото, резервные копии и журнал действий.'
  },
  {
    title: 'Когда используется сервер',
    text: 'Сервер используется для резервного копирования, синхронизации между устройствами, PDF и AI-функций.'
  },
  {
    title: 'Перенос между устройствами',
    text: 'Для переноса backup между ПК и телефоном можно подключить Яндекс ID или VK ID.'
  }
]

const pages = [
  {
    icon: 'waving_hand',
    title: 'Добро пожаловать в Семейное древо',
    text: 'Приложение хранит данные локально в браузере и умеет переносить backup между устройствами.'
  },
  {
    icon: 'lock',
    title: 'Приватность и резервирование',
    text: 'Вы управляете своими данными сами: экспорт, серверный backup, перенос и удаление доступны в приложении.'
  },
  {
    icon: 'shield',
    title: 'Опциональная блокировка',
    text: 'Можно включить локальную блокировку по PIN для защиты доступа на этом устройстве.'
  }
]

const isLast = computed(() => page.value === pages.length - 1)
const progress = computed(() => ((page.value + 1) / pages.length) * 100)
const yandexConfigured = computed(() => Boolean(appStore.authProviders?.yandex?.configured))
const vkConfigured = computed(() => Boolean(appStore.authProviders?.vk?.configured))
const hasPortableIdentity = computed(() => Boolean(appStore.portableIdentity))

async function nextPage(): Promise<void> {
  error.value = ''
  direction.value = 'next'

  if (page.value === 1 && !consent.value) {
    error.value = 'Для продолжения примите политику конфиденциальности.'
    return
  }

  if (!isLast.value) {
    page.value += 1
    return
  }

  if (enablePin.value) {
    if (!pin.value || pin.value.length < 4) {
      error.value = 'PIN должен содержать минимум 4 символа.'
      return
    }
    if (pin.value !== pinConfirm.value) {
      error.value = 'PIN и подтверждение не совпадают.'
      return
    }
    await appStore.setPin(pin.value)
  } else {
    await appStore.setPinToggle(false)
  }

  await appStore.completeOnboarding()
  await router.replace('/app/members')
}

function prevPage(): void {
  error.value = ''
  direction.value = 'prev'
  page.value = Math.max(0, page.value - 1)
}

async function connectPortableIdentity(provider: 'yandex' | 'vk'): Promise<void> {
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
    await appStore.refreshAuthState()
  } catch (reason) {
    authError.value = `Не удалось завершить вход: ${(reason as Error).message || 'unknown error'}`
  } finally {
    authBusy.value = ''
  }
}
</script>

<template>
  <section class="onboarding-page">
    <div class="onboarding-center">
      <div class="onboarding-brand">
        <img :src="logoIcon" alt="Логотип Семейного древа" class="onboarding-brand-logo" width="30" height="30" decoding="async" fetchpriority="high" />
        <span>Семейное древо</span>
      </div>

      <div class="progress-bar onboarding-progress">
        <div class="progress-bar-fill" :style="{ width: progress + '%' }"></div>
      </div>

      <article class="onboarding-card">
        <div class="step-indicator">
          <span
            v-for="(item, index) in pages"
            :key="item.title"
            class="step-dot"
            :class="{ active: index === page, done: index < page }"
          ></span>
        </div>

        <Transition :name="direction === 'next' ? 'slide-right' : 'slide-left'" mode="out-in">
          <div :key="page" class="step-content">
            <span class="step-icon">
              <AppIcon :name="pages[page].icon" :size="44" />
            </span>
            <h2>{{ pages[page].title }}</h2>
            <p>{{ pages[page].text }}</p>
          </div>
        </Transition>

        <div v-if="page === 1" class="policy-block">
          <label class="toggle-switch">
            <input v-model="consent" type="checkbox" />
            <span class="toggle-track"></span>
            <span>Я принимаю политику конфиденциальности</span>
          </label>

          <div class="policy-text">
            <p class="policy-heading">Семейное древо</p>
            <ol class="policy-list">
              <li v-for="item in privacyPolicyItems" :key="item.title">
                <strong>{{ item.title }}</strong>
                <span>{{ item.text }}</span>
              </li>
            </ol>
            <p class="policy-contact">
              Связь:
              <a :href="privacyContactUrl" target="_blank" rel="noopener noreferrer">{{ privacyContactUrl }}</a>
            </p>
          </div>

          <div class="backup-auth-block">
            <div class="backup-auth-head">
              <AppIcon :name="hasPortableIdentity ? 'verified_user' : 'cloud'" :size="18" />
              <span>Перенос между устройствами</span>
            </div>

            <p class="backup-auth-text">
              Этот шаг необязателен. Можно подключить внешний вход сейчас или сделать это позже в разделе
              «Резервные копии».
            </p>

            <div class="btn-row backup-auth-actions">
              <YandexIdButton
                @click="connectPortableIdentity('yandex')"
                :disabled="authBusy !== '' || !yandexConfigured"
                :loading="authBusy === 'yandex'"
              />
              <button
                class="btn-action"
                @click="connectPortableIdentity('vk')"
                :disabled="authBusy !== '' || !vkConfigured"
              >
                {{ authBusy === 'vk' ? 'Подключение…' : 'Войти с VK ID' }}
              </button>
            </div>

            <SyncProgress
              :visible="Boolean(authBusy)"
              :progress="authProgress"
              :label="authProgressLabel"
            />

            <p v-if="hasPortableIdentity" class="backup-auth-status ok">
              Переносимая учётная запись уже подключена.
            </p>
            <p v-else class="backup-auth-status muted">
              Можно пропустить этот шаг и подключить вход позже.
            </p>
            <p v-if="authStatus" class="backup-auth-status ok">{{ authStatus }}</p>
            <p v-if="authError" class="backup-auth-status err">{{ authError }}</p>
          </div>
        </div>

        <div v-if="page === 2" class="pin-block">
          <label class="toggle-switch">
            <input v-model="enablePin" type="checkbox" />
            <span class="toggle-track"></span>
            <span>Включить локальную блокировку по PIN</span>
          </label>
          <Transition name="slide-right">
            <div class="form-grid" v-if="enablePin">
              <div class="field">
                <label>PIN</label>
                <input v-model="pin" type="password" maxlength="32" placeholder="Минимум 4 символа" />
              </div>
              <div class="field">
                <label>Подтверждение PIN</label>
                <input v-model="pinConfirm" type="password" maxlength="32" placeholder="Повторите PIN" />
              </div>
            </div>
          </Transition>
        </div>

        <p v-if="error" class="error-msg">{{ error }}</p>

        <div class="btn-row onboarding-actions">
          <button class="btn-action" @click="prevPage" :disabled="page === 0">
            ← Назад
          </button>
          <button class="btn-action primary" @click="nextPage">
            <AppIcon :name="isLast ? 'rocket_launch' : 'arrow_forward'" :size="18" />
            {{ isLast ? 'Начать работу' : 'Далее' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.onboarding-page {
  position: relative;
  z-index: 2;
  min-height: 100vh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 132px 16px 72px;
}

.onboarding-center {
  width: 100%;
  max-width: 520px;
}

.onboarding-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  color: var(--color-text);
  font-weight: 600;
  font-size: 1.02rem;
}

.onboarding-brand-logo {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--color-glass-border);
}

.onboarding-progress {
  margin-bottom: 20px;
}

.onboarding-card {
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-xl);
  padding: 32px 28px;
  box-shadow: var(--shadow-elevated);
}

.step-indicator {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
}

.step-dot {
  width: 32px;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  transition: all var(--transition-normal);
}

.step-dot.active {
  background: var(--gradient-accent);
}

.step-dot.done {
  background: var(--color-accent);
  opacity: 0.45;
}

.step-content {
  margin-bottom: 20px;
}

.step-icon {
  display: block;
  margin-bottom: 16px;
}

.step-content h2 {
  font-size: 1.35rem;
  font-weight: 700;
  margin-bottom: 10px;
}

.step-content p {
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.policy-block,
.pin-block {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.policy-text {
  border: 1px dashed var(--color-glass-border);
  border-radius: var(--radius-sm);
  padding: 14px;
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  line-height: 1.6;
}

.policy-heading {
  margin: 0 0 8px;
  color: var(--color-text);
  font-size: 0.9rem;
  font-weight: 700;
}

.policy-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
}

.policy-list li strong {
  display: block;
  color: var(--color-text);
  font-size: 0.83rem;
  font-weight: 600;
}

.policy-contact {
  margin: 10px 0 0;
  font-size: 0.82rem;
}

.policy-contact a {
  color: var(--color-accent-light);
}

.backup-auth-block {
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.backup-auth-head {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.backup-auth-text {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.55;
}

.backup-auth-actions .btn-action {
  flex: 1 1 180px;
}

.backup-auth-status {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.4;
}

.backup-auth-status.ok {
  color: var(--color-success);
}

.backup-auth-status.muted {
  color: var(--color-text-muted);
}

.backup-auth-status.err {
  color: var(--color-error);
}

.form-grid {
  display: grid;
  gap: 12px;
}

.field {
  display: grid;
  gap: 6px;
}

.field input {
  min-height: 46px;
  border-radius: 14px;
  border: 1px solid var(--color-glass-border);
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text);
  padding: 0 14px;
  font: inherit;
}

.onboarding-actions {
  margin-top: 24px;
  justify-content: space-between;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.85rem;
  margin-top: 8px;
}

.slide-right-enter-active,
.slide-right-leave-active,
.slide-left-enter-active,
.slide-left-leave-active {
  transition: all 0.3s ease;
}

.slide-right-enter-from {
  opacity: 0;
  transform: translateX(30px);
}

.slide-right-leave-to {
  opacity: 0;
  transform: translateX(-30px);
}

.slide-left-enter-from {
  opacity: 0;
  transform: translateX(-30px);
}

.slide-left-leave-to {
  opacity: 0;
  transform: translateX(30px);
}

@media (max-width: 480px) {
  .onboarding-page {
    padding: 110px 12px 94px;
  }

  .onboarding-card {
    padding: 24px 16px;
  }
}
</style>
