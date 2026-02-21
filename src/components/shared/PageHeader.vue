<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="page-header">
    <h1 class="app-section-title">{{ title }}</h1>
    <p v-if="subtitle" class="app-section-subtitle">{{ subtitle }}</p>
  </header>
</template>

<style scoped>
.page-header {
  margin-bottom: 18px;
}
</style>
