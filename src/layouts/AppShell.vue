<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'

const appStore = useAppStore()
const router = useRouter()

const navItems = [
  { to: '/app/members', label: 'Семья' },
  { to: '/app/tree', label: 'Древо' },
  { to: '/app/photos', label: 'Фото + AI' },
  { to: '/app/export', label: 'Экспорт' },
  { to: '/app/backup', label: 'Backup' },
  { to: '/app/server', label: 'Сервер' },
  { to: '/app/settings', label: 'Настройки' },
  { to: '/app/about', label: 'О проекте' }
]

const currentThemeLabel = computed(() => {
  if (appStore.settings.theme === 'dark') return 'Темная'
  if (appStore.settings.theme === 'light') return 'Светлая'
  return 'Системная'
})

function lockApp(): void {
  appStore.lockSession()
  router.push('/app/lock')
}
</script>

<template>
  <div class="app-shell">
    <div class="bg-effects">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>

    <header class="app-header">
      <div class="app-container app-header-inner">
        <div class="brand-wrap">
          <RouterLink to="/" class="brand-link">FamilyOne</RouterLink>
          <span class="chip">{{ currentThemeLabel }}</span>
        </div>
        <div class="app-actions">
          <button class="btn-action" @click="lockApp" :disabled="!appStore.settings.pinEnabled">
            Блокировка
          </button>
        </div>
      </div>
      <div class="app-container">
        <nav class="app-nav">
          <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="nav-link">
            {{ item.label }}
          </RouterLink>
        </nav>
      </div>
    </header>

    <main>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.bg-effects {
  position: fixed;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  z-index: 0;
}

.orb {
  position: absolute;
  border-radius: 999px;
  filter: blur(90px);
}

.orb-1 {
  width: 360px;
  height: 360px;
  background: rgba(124, 92, 252, 0.16);
  left: -80px;
  top: -80px;
}

.orb-2 {
  width: 300px;
  height: 300px;
  background: rgba(244, 114, 182, 0.13);
  right: -60px;
  top: 30%;
}

.orb-3 {
  width: 260px;
  height: 260px;
  background: rgba(34, 211, 238, 0.1);
  left: 30%;
  bottom: -100px;
}

.app-header {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 200;
  backdrop-filter: blur(16px);
  background: color-mix(in srgb, var(--color-bg-alt) 82%, transparent);
  border-bottom: 1px solid var(--color-glass-border);
}

.app-header-inner {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-link {
  color: var(--color-text);
  text-decoration: none;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.app-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 0 12px;
}

.nav-link {
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  text-decoration: none;
  padding: 6px 12px;
  font-size: 0.83rem;
  transition: all 0.2s ease;
}

.nav-link.router-link-active {
  color: var(--color-text);
  border-color: rgba(124, 92, 252, 0.7);
  background: rgba(124, 92, 252, 0.12);
}

@media (max-width: 680px) {
  .app-nav {
    overflow-x: auto;
    flex-wrap: nowrap;
    padding-bottom: 8px;
  }
}
</style>
