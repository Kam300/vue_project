<script setup lang="ts">
withDefaults(
  defineProps<{
    disabled?: boolean
    loading?: boolean
    fullWidth?: boolean
  }>(),
  {
    disabled: false,
    loading: false,
    fullWidth: false
  }
)
</script>

<template>
  <button
    type="button"
    class="yandex-id-btn"
    :class="{ 'is-block': fullWidth, 'is-loading': loading }"
    :disabled="disabled || loading"
  >
    <span class="yandex-id-btn__logo" aria-hidden="true">Я</span>
    <span class="yandex-id-btn__label">
      {{ loading ? 'Подключение…' : 'Войти с Яндекс ID' }}
    </span>
  </button>
</template>

<style scoped>
.yandex-id-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 44px;
  padding: 0 18px;
  border: 1px solid rgba(17, 17, 17, 0.08);
  border-radius: 16px;
  background: #fff;
  color: #111;
  font: inherit;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.14);
  transition:
    transform var(--transition-fast),
    box-shadow var(--transition-fast),
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.yandex-id-btn.is-block {
  width: 100%;
}

.yandex-id-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  background: #f6f7f9;
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.18);
}

.yandex-id-btn:focus-visible {
  outline: 2px solid rgba(252, 63, 29, 0.45);
  outline-offset: 2px;
}

.yandex-id-btn:disabled {
  cursor: not-allowed;
  opacity: 0.58;
  box-shadow: none;
}

.yandex-id-btn__logo {
  flex: 0 0 auto;
  color: #fc3f1d;
  font-size: 1.2rem;
  font-weight: 800;
  line-height: 1;
}

.yandex-id-btn__label {
  white-space: nowrap;
}

@media (max-width: 680px) {
  .yandex-id-btn {
    width: 100%;
  }
}
</style>
