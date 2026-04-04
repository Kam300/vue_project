<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  visible: boolean
  progress: number
  label: string
}>()

const percent = computed(() => Math.max(0, Math.min(100, Math.round(props.progress || 0))))
</script>

<template>
  <Transition name="sync-progress-fade">
    <div v-if="visible" class="sync-progress" role="status" aria-live="polite">
      <div class="sync-progress-head">
        <span class="sync-progress-label">{{ label || 'Синхронизация…' }}</span>
        <span class="sync-progress-value">{{ percent }}%</span>
      </div>
      <div class="sync-progress-track">
        <div class="sync-progress-fill" :style="{ width: `${percent}%` }"></div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.sync-progress {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: rgba(22, 27, 41, 0.94);
  background: color-mix(in srgb, var(--color-surface) 94%, transparent);
}

.sync-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sync-progress-label {
  color: var(--color-text);
  font-size: 0.84rem;
  line-height: 1.4;
}

.sync-progress-value {
  color: var(--color-text-secondary);
  font-size: 0.76rem;
  font-weight: 700;
}

.sync-progress-track {
  overflow: hidden;
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
}

.sync-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--gradient-accent);
  transition: width 180ms ease;
}

.sync-progress-fade-enter-active,
.sync-progress-fade-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.sync-progress-fade-enter-from,
.sync-progress-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
