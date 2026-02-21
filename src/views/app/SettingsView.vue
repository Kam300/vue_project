<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useAppStore } from '@/stores/appStore'

const appStore = useAppStore()
const router = useRouter()

const form = reactive({
  apiBaseUrl: '/api',
  theme: 'system' as 'system' | 'light' | 'dark',
  treeTemplate: 'modern' as 'modern' | 'classic' | 'print',
  appLockBySession: false,
  pinEnabled: false,
  newPin: '',
  newPinConfirm: ''
})

const saving = ref(false)
const status = ref('')
const error = ref('')

function syncFromStore(): void {
  form.apiBaseUrl = appStore.settings.apiBaseUrl
  form.theme = appStore.settings.theme
  form.treeTemplate = appStore.settings.treeTemplate
  form.appLockBySession = appStore.settings.appLockBySession
  form.pinEnabled = appStore.settings.pinEnabled
  form.newPin = ''
  form.newPinConfirm = ''
}

onMounted(() => {
  syncFromStore()
})

function clearMessages(): void {
  status.value = ''
  error.value = ''
}

async function saveSettings(): Promise<void> {
  clearMessages()
  saving.value = true

  try {
    await appStore.updateSettings({
      apiBaseUrl: form.apiBaseUrl.trim() || '/api',
      theme: form.theme,
      treeTemplate: form.treeTemplate,
      appLockBySession: form.appLockBySession
    })

    const currentlyPinEnabled = appStore.settings.pinEnabled

    if (!form.pinEnabled && currentlyPinEnabled) {
      await appStore.setPin('')
    }

    if (form.pinEnabled) {
      if (!currentlyPinEnabled) {
        if (form.newPin.length < 4) {
          throw new Error('Введите новый PIN минимум из 4 символов')
        }
        if (form.newPin !== form.newPinConfirm) {
          throw new Error('PIN и подтверждение не совпадают')
        }
        await appStore.setPin(form.newPin)
      } else if (form.newPin || form.newPinConfirm) {
        if (form.newPin.length < 4) {
          throw new Error('Новый PIN слишком короткий')
        }
        if (form.newPin !== form.newPinConfirm) {
          throw new Error('PIN и подтверждение не совпадают')
        }
        await appStore.setPin(form.newPin)
      } else {
        await appStore.setPinToggle(true)
      }
    }

    syncFromStore()
    status.value = 'Настройки сохранены.'
  } catch (reason) {
    error.value = (reason as Error).message
  } finally {
    saving.value = false
  }
}

function lockNow(): void {
  appStore.lockSession()
  router.push('/app/lock')
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="Настройки" subtitle="Локальная конфигурация приложения и безопасность" />

      <article class="app-card settings-card">
        <div class="form-grid">
          <div class="field">
            <label>API base URL</label>
            <input v-model="form.apiBaseUrl" type="text" placeholder="/api" />
          </div>

          <div class="field">
            <label>Тема</label>
            <select v-model="form.theme">
              <option value="system">Системная</option>
              <option value="light">Светлая</option>
              <option value="dark">Темная</option>
            </select>
          </div>

          <div class="field">
            <label>Шаблон дерева по умолчанию</label>
            <select v-model="form.treeTemplate">
              <option value="modern">modern</option>
              <option value="classic">classic</option>
              <option value="print">print</option>
            </select>
          </div>

          <div class="field">
            <label>Блокировка по сессии</label>
            <select v-model="form.appLockBySession">
              <option :value="true">Включена</option>
              <option :value="false">Выключена</option>
            </select>
          </div>
        </div>

        <div class="security-box">
          <h2>PIN блокировка</h2>
          <label class="switch"><input v-model="form.pinEnabled" type="checkbox" /> Включить PIN</label>

          <div class="form-grid" v-if="form.pinEnabled">
            <div class="field">
              <label>{{ appStore.settings.pinEnabled ? 'Новый PIN' : 'PIN' }}</label>
              <input v-model="form.newPin" type="password" maxlength="32" />
            </div>
            <div class="field">
              <label>Подтверждение PIN</label>
              <input v-model="form.newPinConfirm" type="password" maxlength="32" />
            </div>
          </div>

          <div class="btn-row">
            <button class="btn-action" @click="lockNow" :disabled="!appStore.settings.pinEnabled">Заблокировать сейчас</button>
          </div>
        </div>

        <p v-if="status" class="status-line">{{ status }}</p>
        <p v-if="error" class="error">{{ error }}</p>

        <div class="btn-row submit-row">
          <button class="btn-action primary" @click="saveSettings" :disabled="saving">
            {{ saving ? 'Сохранение...' : 'Сохранить настройки' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.settings-card {
  padding: 16px;
}

.security-box {
  margin-top: 14px;
  border: 1px dashed var(--color-glass-border);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.security-box h2 {
  font-size: 1rem;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.88rem;
}

.submit-row {
  margin-top: 16px;
}

.error {
  color: var(--color-error);
}
</style>
