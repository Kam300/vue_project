<script setup lang="ts">
// Recovery_Dialog modal — Web client.
// Spec: .kiro/specs/multi-device-sync-safety/design.md §4.4.
// Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9, 20.1, 20.2, 20.4.

import { computed } from 'vue'
import { useRecoveryState } from '@/composables/useRecoveryState'

const recovery = useRecoveryState()

const isOpen = computed(() => recovery.isOpen.value)
const headerText = computed(() => {
  const n = recovery.pendingCount.value
  return `Сессия завершена на этом устройстве. У вас ${n} несохранённых изменений.`
})

const reasonText = computed(() => {
  switch (recovery.revokedReason.value) {
    case 'single_session_re_enabled':
      return 'Включён режим единственной сессии. Войдите снова, чтобы продолжить.'
    case 'signed_in_on_other_device':
    default:
      return 'Вы вошли в аккаунт на другом устройстве.'
  }
})

const stateLabel = computed(() => {
  switch (recovery.state.value) {
    case 'ReAuthing':
      return 'Авторизация…'
    case 'Syncing':
      return 'Синхронизация…'
    case 'Conflict':
      return 'Конфликт версий — откройте диалог разрешения.'
    case 'Exporting':
      return 'Подготовка файла…'
    default:
      return ''
  }
})

const showConfirm = computed(() => recovery.confirmDiscardOpen.value)

async function onSignIn(): Promise<void> {
  await recovery.signInAgain()
}

async function onExport(): Promise<void> {
  await recovery.exportPending()
}

async function onDiscardClick(): Promise<void> {
  await recovery.discardAll()
}

async function onConfirmDiscard(): Promise<void> {
  await recovery.discardAll()
}

function onCancelDiscard(): void {
  recovery.cancelDiscard()
}
</script>

<template>
  <Transition name="recovery-fade">
    <div
      v-if="isOpen"
      class="recovery-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="recovery-title"
    >
      <div class="recovery-card">
        <header class="recovery-head">
          <h2 id="recovery-title" class="recovery-title">{{ headerText }}</h2>
          <p class="recovery-sub">{{ reasonText }}</p>
        </header>

        <p v-if="stateLabel" class="recovery-state" role="status">{{ stateLabel }}</p>
        <p v-if="recovery.error.value" class="recovery-error" role="alert">
          {{ recovery.error.value }}
        </p>

        <footer v-if="!showConfirm" class="recovery-actions">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="recovery.busy.value"
            @click="onSignIn"
          >
            Войти заново и загрузить
          </button>
          <button
            type="button"
            class="btn btn-ghost"
            :disabled="recovery.busy.value"
            @click="onExport"
          >
            Сохранить в файл
          </button>
          <button
            type="button"
            class="btn btn-danger"
            :disabled="recovery.busy.value"
            @click="onDiscardClick"
          >
            Удалить
          </button>
        </footer>

        <section v-else class="recovery-confirm">
          <p class="recovery-confirm-text">
            Удалить {{ recovery.pendingCount.value }} несохранённых изменений? Это действие
            необратимо.
          </p>
          <div class="recovery-actions">
            <button
              type="button"
              class="btn btn-danger"
              :disabled="recovery.busy.value"
              @click="onConfirmDiscard"
            >
              Удалить безвозвратно
            </button>
            <button
              type="button"
              class="btn btn-ghost"
              :disabled="recovery.busy.value"
              @click="onCancelDiscard"
            >
              Отмена
            </button>
          </div>
        </section>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.recovery-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(8, 12, 22, 0.7);
  backdrop-filter: blur(4px);
}

.recovery-card {
  width: min(560px, 100%);
  display: grid;
  gap: 16px;
  padding: 24px;
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--color-glass-border, rgba(255, 255, 255, 0.12));
  background: var(--color-surface, #161b29);
  color: var(--color-text, #ecedf3);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.recovery-head {
  display: grid;
  gap: 6px;
}

.recovery-title {
  margin: 0;
  font-size: 1.1rem;
  line-height: 1.35;
  font-weight: 700;
}

.recovery-sub {
  margin: 0;
  font-size: 0.9rem;
  color: var(--color-text-secondary, #a1a7b8);
  line-height: 1.45;
}

.recovery-state {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm, 8px);
  background: rgba(79, 128, 255, 0.12);
  color: #aac0ff;
  font-size: 0.86rem;
}

.recovery-error {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm, 8px);
  background: rgba(220, 53, 69, 0.12);
  color: #ff8a95;
  font-size: 0.86rem;
}

.recovery-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.recovery-confirm-text {
  margin: 0 0 12px;
  font-size: 0.92rem;
  color: var(--color-text, #ecedf3);
  line-height: 1.45;
}

.btn {
  appearance: none;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 9px 18px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 140ms ease, background 140ms ease, border-color 140ms ease;
}

.btn:disabled {
  opacity: 0.6;
  cursor: progress;
}

.btn-primary {
  background: var(--gradient-accent, linear-gradient(135deg, #4f80ff, #6a5cff));
  color: #fff;
}

.btn-danger {
  background: rgba(220, 53, 69, 0.18);
  border-color: rgba(220, 53, 69, 0.38);
  color: #ff8a95;
}

.btn-danger:hover:not(:disabled) {
  background: rgba(220, 53, 69, 0.26);
}

.btn-ghost {
  background: transparent;
  border-color: var(--color-glass-border, rgba(255, 255, 255, 0.18));
  color: var(--color-text, #ecedf3);
}

.btn-ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.recovery-fade-enter-active,
.recovery-fade-leave-active {
  transition: opacity 160ms ease;
}

.recovery-fade-enter-from,
.recovery-fade-leave-to {
  opacity: 0;
}
</style>
