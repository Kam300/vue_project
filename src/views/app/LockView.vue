<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'
import PageHeader from '@/components/shared/PageHeader.vue'

const router = useRouter()
const appStore = useAppStore()

const pin = ref('')
const error = ref('')
const loading = ref(false)

async function unlock(): Promise<void> {
  error.value = ''
  if (!pin.value) {
    error.value = 'Введите PIN'
    return
  }

  loading.value = true
  try {
    const ok = await appStore.verifyPin(pin.value)
    if (!ok) {
      error.value = 'Неверный PIN'
      return
    }
    await router.replace('/app/members')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="Локальная блокировка" subtitle="Введите PIN для доступа к приложению" />
      <article class="app-card lock-card">
        <div class="field">
          <label>PIN</label>
          <input v-model="pin" type="password" maxlength="32" @keyup.enter="unlock" />
          <span v-if="error" class="error">{{ error }}</span>
        </div>
        <div class="btn-row">
          <button class="btn-action primary" @click="unlock" :disabled="loading">
            {{ loading ? 'Проверка...' : 'Разблокировать' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.lock-card {
  max-width: 420px;
  padding: 20px;
}
</style>
