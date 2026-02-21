<script setup lang="ts">
import { RouterLink } from 'vue-router'
import LandingPage from '@/components/LandingPage.vue'
</script>

<template>
  <div class="landing-wrap">
    <LandingPage />
    <RouterLink class="open-app-btn" to="/app/members">Открыть web-приложение</RouterLink>
  </div>
</template>

<style scoped>
.open-app-btn {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 300;
  text-decoration: none;
  border-radius: 999px;
  border: 1px solid var(--color-glass-border);
  background: var(--gradient-accent);
  color: #fff;
  padding: 10px 14px;
  font-weight: 600;
}
</style>
