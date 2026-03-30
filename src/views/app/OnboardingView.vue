<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'
import logoIcon from '@/assets/icon.png'
import AppIcon from '@/components/shared/AppIcon.vue'
import { ensureGoogleIdentityLoaded, getGoogleClientId, signInWithGooglePopup } from '@/services/googleIdentity'

const appStore = useAppStore()
const router = useRouter()

const page = ref(0)
const consent = ref(false)
const enablePin = ref(false)
const pin = ref('')
const pinConfirm = ref('')
const error = ref('')
const direction = ref<'next' | 'prev'>('next')
const authBusy = ref(false)
const authError = ref('')
const privacyContactUrl = 'https://t.me/TotalC0de'
const privacyPolicyItems = [
  {
    title: 'Какие данные обрабатываются',
    text: 'Приложение хранит только те данные, которые вы добавляете сами: ФИО, даты, семейные связи, фотографии и контактные данные членов семьи.'
  },
  {
    title: 'Где хранятся данные',
    text: 'По умолчанию данные хранятся локально на вашем устройстве.'
  },
  {
    title: 'Когда используется сервер',
    text: 'Сервер используется только по вашему действию: для распознавания лиц, генерации PDF и серверного backup/restore.'
  },
  {
    title: 'Резервное копирование',
    text: 'Доступны локальный экспорт/импорт и серверный backup. Серверный backup запускается только после авторизации и явного подтверждения.'
  },
  {
    title: 'Передача данных третьим лицам',
    text: 'Приложение не передает данные третьим лицам без вашего прямого действия.'
  },
  {
    title: 'Управление и удаление',
    text: 'Вы можете в любой момент удалить членов семьи и связанные фотографии как локально, так и на сервере через функции очистки.'
  },
  {
    title: 'Изменения политики',
    text: 'Политика может обновляться. Актуальная версия всегда доступна в приложении.'
  }
]

const pages = [
  {
    icon: 'waving_hand',
    title: 'Добро пожаловать в FamilyOne Web',
    text: 'Приложение хранит данные локально в браузере и работает как PWA. Ваши данные — только ваши.'
  },
  {
    icon: 'lock',
    title: 'Приватность и безопасность',
    text: 'Вы полностью управляете данными семьи: экспорт, backup, удаление и перенос — всё в ваших руках.'
  },
  {
    icon: 'shield',
    title: 'Опциональная блокировка',
    text: 'Можно включить PIN-экран для защиты доступа на этом устройстве.'
  }
]

const isLast = computed(() => page.value === pages.length - 1)
const progress = computed(() => ((page.value + 1) / pages.length) * 100)
const hasGoogleClientId = computed(() => Boolean(getGoogleClientId()))
const isAuthorized = computed(() => Boolean(appStore.googleIdToken))

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

async function signInGoogleOnboarding(): Promise<void> {
  authError.value = ''

  if (!hasGoogleClientId.value) {
    authError.value = 'Google OAuth не настроен. Укажите VITE_GOOGLE_WEB_CLIENT_ID.'
    return
  }

  authBusy.value = true
  try {
    await ensureGoogleIdentityLoaded()
    const token = await signInWithGooglePopup()
    appStore.setGoogleToken(token, 'Google account')
  } catch (reason) {
    authError.value = `Вход не выполнен: ${(reason as Error).message || 'Unknown error'}`
  } finally {
    authBusy.value = false
  }
}


</script>

<template>
  <section class="onboarding-page">
    <div class="onboarding-center">
      <div class="onboarding-brand">
        <img :src="logoIcon" alt="FamilyOne logo" class="onboarding-brand-logo" />
        <span>FamilyOne</span>
      </div>

      <!-- Progress bar -->
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
            <p class="policy-heading">Политика конфиденциальности FamilyOne</p>
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
              <AppIcon :name="isAuthorized ? 'verified_user' : 'backup'" :size="18" />
              <span>Google backup (необязательно)</span>
            </div>

            <p class="backup-auth-text">
              Можно подключить Google сейчас для облачного резервирования и восстановления. Либо нажать «Далее» и настроить позже в разделе «Резерв».
            </p>

            <button
              class="btn-action primary"
              @click="signInGoogleOnboarding"
              :disabled="authBusy || isAuthorized || !hasGoogleClientId"
              style="align-self: flex-start; margin-top: 4px;"
            >
              <svg v-if="!authBusy" width="16" height="16" viewBox="0 0 48 48" style="flex-shrink:0">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                <path fill="none" d="M0 0h48v48H0z"/>
              </svg>
              <AppIcon v-else name="hourglass_top" :size="16" />
              {{ authBusy ? 'Авторизация...' : 'Войти через Google' }}
            </button>

            <p v-if="isAuthorized" class="backup-auth-status ok">
              Google подключен. Повторный вход не требуется.
            </p>
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
  box-shadow: 0 5px 14px rgba(0, 0, 0, 0.18);
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
  box-shadow: 0 0 10px rgba(124, 92, 252, 0.3);
}

.step-dot.done {
  background: var(--color-accent);
  opacity: 0.5;
}

.step-content {
  margin-bottom: 20px;
}

.step-icon {
  display: block;
  font-size: 3rem;
  margin-bottom: 16px;
  line-height: 1;
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
  max-height: 260px;
  overflow: auto;
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

.policy-list li {
  color: var(--color-text-secondary);
}

.policy-list li strong {
  display: block;
  color: var(--color-text);
  font-size: 0.83rem;
  font-weight: 600;
}

.policy-list li span {
  display: block;
  font-size: 0.82rem;
  line-height: 1.45;
}

.policy-contact {
  margin: 10px 0 0;
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

.policy-contact a {
  color: var(--color-accent-light);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.policy-contact a:hover {
  color: var(--color-accent);
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
  color: var(--color-text);
}

.backup-auth-text {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.55;
}

.backup-auth-actions {
  margin-top: 4px;
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

.onboarding-actions {
  margin-top: 24px;
  justify-content: space-between;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.85rem;
  margin-top: 8px;
}

/* Slide transitions */
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

@media (max-width: 860px) {
  .onboarding-page {
    padding-top: 118px;
    padding-bottom: 88px;
  }
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
