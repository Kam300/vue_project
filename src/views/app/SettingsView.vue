<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { useAppStore } from '@/stores/appStore'
import { useMemberStore } from '@/stores/memberStore'
import { clearAllFaces } from '@/services/api'

const appStore = useAppStore()
const memberStore = useMemberStore()
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
const autoSaving = ref(false)
const clearingAll = ref(false)
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

// Auto-save безопасных полей: тема и шаблон дерева
watch(
  () => [form.theme, form.treeTemplate],
  async ([theme, treeTemplate]) => {
    if (saving.value) return   // не дублируем manual save
    autoSaving.value = true
    try {
      await appStore.updateSettings({
        theme: theme as typeof form.theme,
        treeTemplate: treeTemplate as typeof form.treeTemplate
      })
    } finally {
      autoSaving.value = false
    }
  }
)

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

async function clearAllData(): Promise<void> {
  clearMessages()
  const confirmed = window.confirm(
    'Удалить все данные? Будут удалены все члены семьи и фото локально, а также все зарегистрированные лица на сервере для этого устройства.'
  )
  if (!confirmed) return

  const deviceId = appStore.settings.deviceId
  if (!deviceId) {
    error.value = 'Не найден device_id. Повторите после перезапуска приложения.'
    return
  }

  clearingAll.value = true
  try {
    const serverResponse = await clearAllFaces(deviceId)
    if (!serverResponse.success) {
      throw new Error(serverResponse.error || 'Не удалось очистить лица на сервере')
    }

    await memberStore.removeAllMembers()
    status.value = 'Все локальные данные и зарегистрированные лица на сервере удалены.'
  } catch (reason) {
    error.value = (reason as Error).message || 'Ошибка удаления данных'
  } finally {
    clearingAll.value = false
  }
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader icon="settings" title="Настройки" subtitle="Локальная конфигурация приложения и безопасность" />

      <article class="app-card settings-card">
        <!-- General settings -->
        <div class="settings-group">
          <h2 class="group-title">
            <span class="group-icon"><AppIcon name="language" :size="20" /></span> Общие
          </h2>
          <div class="form-grid">
            <div class="field">
              <label>API base URL</label>
              <input v-model="form.apiBaseUrl" type="text" placeholder="/api" />
            </div>

            <div class="field">
              <label>Тема</label>
              <div class="theme-selector">
                <button
                  v-for="opt in [{ value: 'system', label: 'Системная', icon: 'computer' }, { value: 'light', label: 'Светлая', icon: 'light_mode' }, { value: 'dark', label: 'Тёмная', icon: 'dark_mode' }]"
                  :key="opt.value"
                  type="button"
                  class="btn-action"
                  :class="{ primary: form.theme === opt.value }"
                  @click="form.theme = opt.value as any"
                >
                  <AppIcon :name="opt.icon" :size="16" />
                  {{ opt.label }}
                </button>
              </div>
            </div>

            <div class="field">
              <label>Шаблон дерева</label>
              <select v-model="form.treeTemplate">
                <option value="modern">Modern</option>
                <option value="classic">Classic</option>
                <option value="print">Print</option>
              </select>
            </div>

            <div class="field">
              <label>Блокировка по сессии</label>
              <label class="toggle-switch">
                <input v-model="form.appLockBySession" type="checkbox" />
                <span class="toggle-track"></span>
                <span>{{ form.appLockBySession ? 'Включена' : 'Выключена' }}</span>
              </label>
            </div>
          </div>
        </div>

        <div class="section-divider"></div>

        <!-- Security -->
        <div class="settings-group">
          <h2 class="group-title">
            <span class="group-icon"><AppIcon name="lock" :size="20" /></span> PIN блокировка
          </h2>

          <label class="toggle-switch">
            <input v-model="form.pinEnabled" type="checkbox" />
            <span class="toggle-track"></span>
            <span>Включить PIN</span>
          </label>

          <Transition name="slide-down">
            <div class="form-grid" v-if="form.pinEnabled" style="margin-top: 14px">
              <div class="field">
                <label>{{ appStore.settings.pinEnabled ? 'Новый PIN' : 'PIN' }}</label>
                <input v-model="form.newPin" type="password" maxlength="32" placeholder="Минимум 4 символа" />
              </div>
              <div class="field">
                <label>Подтверждение PIN</label>
                <input v-model="form.newPinConfirm" type="password" maxlength="32" placeholder="Повторите PIN" />
              </div>
            </div>
          </Transition>

          <div class="btn-row" style="margin-top: 12px">
            <button class="btn-action" @click="lockNow" :disabled="!appStore.settings.pinEnabled">
              <AppIcon name="lock" :size="16" />
              Заблокировать сейчас
            </button>
          </div>
        </div>

        <div class="section-divider"></div>

        <div class="settings-group danger-zone">
          <h2 class="group-title">
            <span class="group-icon"><AppIcon name="delete" :size="20" /></span> Удаление данных
          </h2>
          <p class="danger-note">
            Очистка удалит все локальные записи и фотографии, а также лица на сервере для текущего устройства.
          </p>
          <div class="btn-row">
            <button class="btn-action danger" @click="clearAllData" :disabled="clearingAll">
              {{ clearingAll ? 'Удаление...' : 'Удалить всё (локально + сервер)' }}
            </button>
          </div>
        </div>

        <div class="section-divider"></div>

        <!-- Save -->
        <p v-if="status" class="status-success with-icon">
          <AppIcon name="check_circle" :size="18" />
          {{ status }}
        </p>
        <p v-if="error" class="error-msg with-icon">
          <AppIcon name="warning" :size="18" />
          {{ error }}
        </p>

        <div class="btn-row">
          <button class="btn-action primary" @click="saveSettings" :disabled="saving">
            <AppIcon :name="saving ? 'hourglass_top' : 'save'" :size="16" />
            {{ saving ? 'Сохранение...' : 'Сохранить настройки' }}
          </button>
          <Transition name="autosave-fade">
            <span v-if="autoSaving" class="autosave-chip">
              <AppIcon name="sync" :size="14" class="autosave-spin" />
              Сохраняется...
            </span>
          </Transition>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.settings-card {
  padding: 24px;
}

.settings-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.danger-zone {
  border: 1px solid rgba(244, 63, 94, 0.35);
  border-radius: var(--radius-sm);
  padding: 14px;
  background: rgba(244, 63, 94, 0.08);
}

.danger-note {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.35;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.05rem;
  font-weight: 600;
}

.group-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.theme-selector {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.theme-selector .btn-action {
  width: 100%;
  min-width: 0;
  padding: 10px 8px;
}

.toggle-switch {
  width: 100%;
  justify-content: space-between;
  gap: 12px;
}

.toggle-switch span:last-child {
  text-align: right;
  overflow-wrap: anywhere;
}

.status-success {
  color: var(--color-success);
  font-size: 0.9rem;
  margin-bottom: 8px;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.9rem;
  margin-bottom: 8px;
  overflow-wrap: anywhere;
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  max-height: 0;
  transform: translateY(-10px);
}

.slide-down-enter-to,
.slide-down-leave-from {
  opacity: 1;
  max-height: 300px;
}

@media (max-width: 860px) {
  .settings-card {
    padding: 20px 16px;
  }
}

@media (max-width: 640px) {
  .theme-selector {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .settings-card {
    padding: 16px 12px;
  }

  .theme-selector {
    grid-template-columns: 1fr;
  }
}

/* Auto-save chip */
.autosave-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  background: var(--input-bg);
}

@keyframes autosave-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.autosave-spin {
  animation: autosave-rotate 1s linear infinite;
  display: inline-flex;
}

.autosave-fade-enter-active,
.autosave-fade-leave-active {
  transition: opacity 0.25s;
}
.autosave-fade-enter-from,
.autosave-fade-leave-to {
  opacity: 0;
}
</style>
