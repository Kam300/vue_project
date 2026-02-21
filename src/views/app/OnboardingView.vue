<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'
import PageHeader from '@/components/shared/PageHeader.vue'

const appStore = useAppStore()
const router = useRouter()

const page = ref(0)
const consent = ref(false)
const enablePin = ref(false)
const pin = ref('')
const pinConfirm = ref('')
const error = ref('')

const pages = [
  {
    title: 'Добро пожаловать в FamilyOne Web',
    text: 'Приложение хранит данные локально в браузере и работает как PWA.'
  },
  {
    title: 'Приватность и безопасность',
    text: 'Вы полностью управляете данными семьи: экспорт, backup, удаление и перенос.'
  },
  {
    title: 'Опциональная блокировка',
    text: 'Можно включить PIN-экран для защиты доступа на этом устройстве.'
  }
]

const isLast = computed(() => page.value === pages.length - 1)

async function nextPage(): Promise<void> {
  error.value = ''
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
  page.value = Math.max(0, page.value - 1)
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="Первый запуск" subtitle="Быстрая настройка FamilyOne Web" />
      <article class="app-card onboarding-card">
        <div class="steps">
          <span
            v-for="(item, index) in pages"
            :key="item.title"
            class="step-dot"
            :class="{ active: index === page }"
          ></span>
        </div>
        <h2>{{ pages[page].title }}</h2>
        <p>{{ pages[page].text }}</p>

        <div v-if="page === 1" class="policy-block">
          <label class="policy-check">
            <input v-model="consent" type="checkbox" />
            Я принимаю политику конфиденциальности и обработку персональных данных в рамках локального хранения.
          </label>
          <div class="policy-text">
            Данные членов семьи, фото и связи хранятся локально. Облачный backup выполняется только по явному действию
            пользователя через Google-вход.
          </div>
        </div>

        <div v-if="page === 2" class="pin-block">
          <label class="policy-check">
            <input v-model="enablePin" type="checkbox" />
            Включить локальную блокировку по PIN
          </label>
          <div class="form-grid" v-if="enablePin">
            <div class="field">
              <label>PIN</label>
              <input v-model="pin" type="password" maxlength="32" />
            </div>
            <div class="field">
              <label>Подтверждение PIN</label>
              <input v-model="pinConfirm" type="password" maxlength="32" />
            </div>
          </div>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div class="btn-row">
          <button class="btn-action" @click="prevPage" :disabled="page === 0">Назад</button>
          <button class="btn-action primary" @click="nextPage">
            {{ isLast ? 'Завершить и открыть приложение' : 'Далее' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.onboarding-card {
  padding: 24px;
  max-width: 760px;
}

.steps {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.step-dot {
  width: 28px;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
}

.step-dot.active {
  background: var(--color-accent);
}

h2 {
  font-size: 1.25rem;
  margin-bottom: 8px;
}

p {
  color: var(--color-text-secondary);
}

.policy-block,
.pin-block {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.policy-check {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 0.9rem;
}

.policy-text {
  border: 1px dashed var(--color-glass-border);
  border-radius: 10px;
  padding: 12px;
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}
</style>
