<script setup lang="ts">
import AppIcon from '@/components/shared/AppIcon.vue'

defineProps<{
  title: string
  subtitle?: string
  icon?: string
}>()
</script>

<template>
  <header class="page-header">
    <div class="page-header-row">
      <AppIcon v-if="icon" :name="icon" :size="30" class="page-header-icon" />
      <div>
        <h1 class="app-section-title">{{ title }}</h1>
        <p v-if="subtitle" class="app-section-subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div class="page-header-accent"></div>
  </header>
</template>

<style scoped>
.page-header {
  margin-bottom: 24px;
}

.page-header-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.page-header-icon {
  color: var(--color-accent-light);
  opacity: 0.95;
}

.page-header-accent {
  height: 3px;
  width: 60px;
  margin-top: 12px;
  border-radius: 999px;
  background: var(--gradient-accent);
  animation: gradientShift 3s ease infinite;
  background-size: 200% 200%;
}
</style>
