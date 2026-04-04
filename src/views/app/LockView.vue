<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'
import AppIcon from '@/components/shared/AppIcon.vue'
import { APP_LOGO_STANDARD_URL } from '@/constants/branding'

const router = useRouter()
const appStore = useAppStore()
const logoIcon = APP_LOGO_STANDARD_URL

const pin = ref('')
const error = ref('')
const loading = ref(false)
const shake = ref(false)

async function unlock(): Promise<void> {
  error.value = ''
  if (!pin.value) {
    error.value = 'Введите PIN'
    triggerShake()
    return
  }

  loading.value = true
  try {
    const ok = await appStore.verifyPin(pin.value)
    if (!ok) {
      error.value = 'Неверный PIN'
      pin.value = ''
      triggerShake()
      return
    }
    await router.replace('/app/members')
  } finally {
    loading.value = false
  }
}

function triggerShake(): void {
  shake.value = true
  setTimeout(() => { shake.value = false }, 500)
}
</script>

<template>
  <section class="lock-page">
    <div class="lock-center">
      <div class="lock-icon-wrap" :class="{ shake }">
        <svg class="lock-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
          <rect x="3" y="11" width="18" height="11" rx="2"/>
          <path d="M7 11V7a5 5 0 0110 0v4"/>
          <circle cx="12" cy="16" r="1"/>
        </svg>
      </div>

      <img :src="logoIcon" alt="Логотип Семейного древа" class="lock-brand-logo" width="72" height="72" decoding="async" loading="eager" fetchpriority="high" />
      <h1 class="lock-title">Семейное древо</h1>
      <p class="lock-subtitle">Введите PIN для доступа</p>

      <div class="lock-form" :class="{ shake }">
        <input
          v-model="pin"
          type="password"
          maxlength="32"
          placeholder="••••"
          class="lock-input"
          @keyup.enter="unlock"
          autofocus
        />
        <Transition name="fade">
          <span v-if="error" class="lock-error">{{ error }}</span>
        </Transition>
        <button class="btn-action primary lock-btn" @click="unlock" :disabled="loading">
          <AppIcon v-if="!loading" name="lock_open" :size="18" />
          {{ loading ? 'Проверка...' : 'Разблокировать' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.lock-page {
  position: relative;
  z-index: 2;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
}

.lock-center {
  text-align: center;
  max-width: 380px;
  width: 100%;
}

.lock-icon-wrap {
  width: 80px;
  height: 80px;
  margin: 0 auto 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(124, 92, 252, 0.1);
  border: 2px solid rgba(124, 92, 252, 0.3);
}

.lock-svg {
  width: 36px;
  height: 36px;
  color: var(--color-accent-light);
}

.lock-brand-logo {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.2);
  margin: 0 auto 14px;
}

.lock-title {
  font-family: var(--font-display);
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 6px;
  background: var(--gradient-accent);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.lock-subtitle {
  color: var(--color-text-secondary);
  margin-bottom: 32px;
}

.lock-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.lock-input {
  width: 100%;
  text-align: center;
  font-size: 1.5rem;
  letter-spacing: 0.5em;
  padding: 16px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.03);
  color: var(--color-text);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.lock-input:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(124, 92, 252, 0.18);
}

.lock-error {
  color: var(--color-error);
  font-size: 0.85rem;
}

.lock-btn {
  width: 100%;
  justify-content: center;
  padding: 14px;
  font-size: 1rem;
}

/* Shake animation */
.shake {
  animation: shake-anim 0.4s ease-in-out;
}

@keyframes shake-anim {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-8px); }
  40% { transform: translateX(8px); }
  60% { transform: translateX(-6px); }
  80% { transform: translateX(6px); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
