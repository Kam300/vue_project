<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/appStore'
import AppIcon from '@/components/shared/AppIcon.vue'
import { APP_LOGO_COMPACT_URL } from '@/constants/branding'

const appStore = useAppStore()
const router = useRouter()
const route = useRoute()
const logoIcon = APP_LOGO_COMPACT_URL
const mobileMenuOpen = ref(false)
const themeAnimating = ref(false)

const themes = ['system', 'light', 'dark'] as const
type Theme = typeof themes[number]

const themeLabels: Record<Theme, string> = {
  system: 'Системная',
  light: 'Светлая',
  dark: 'Тёмная'
}

async function cycleTheme(): Promise<void> {
  const cur = appStore.settings.theme as Theme
  const next = themes[(themes.indexOf(cur) + 1) % themes.length]
  themeAnimating.value = true
  await appStore.updateSettings({ theme: next })
  setTimeout(() => { themeAnimating.value = false }, 500)
}

const navItems = [
  { to: '/app/members', label: 'Семья', icon: 'members', mobileNav: true },
  { to: '/app/tree', label: 'Древо', icon: 'tree', mobileNav: true },
  { to: '/app/photos', label: 'Фото + ИИ', icon: 'photos', mobileNav: true },
  { to: '/app/export', label: 'Экспорт', icon: 'export', mobileNav: false },
  { to: '/app/backup', label: 'Резерв', icon: 'backup', mobileNav: true },
  { to: '/app/server', label: 'Сервер', icon: 'server', mobileNav: false },
  { to: '/app/settings', label: 'Настройки', icon: 'settings', mobileNav: true },
  { to: '/app/about', label: 'О проекте', icon: 'about', mobileNav: false },
]

const mobileNavItems = computed(() => navItems.filter(item => item.mobileNav))

const currentThemeIcon = computed(() => {
  if (appStore.settings.theme === 'dark') return 'dark_mode'
  if (appStore.settings.theme === 'light') return 'light_mode'
  return 'computer'
})

function lockApp(): void {
  appStore.lockSession()
  router.push('/app/lock')
}

function toggleMobileMenu(): void {
  mobileMenuOpen.value = !mobileMenuOpen.value
}

function closeMobileMenu(): void {
  mobileMenuOpen.value = false
}

watch(
  () => route.fullPath,
  () => {
    closeMobileMenu()
  }
)
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
          <RouterLink to="/" class="brand-link">
            <img :src="logoIcon" alt="Логотип Семейного древа" class="brand-logo" width="30" height="30" decoding="async" fetchpriority="high" />
            <span class="brand-text">Семейное древо</span>
          </RouterLink>
          <button
            class="theme-toggle-btn"
            @click="cycleTheme"
            :title="themeLabels[appStore.settings.theme as Theme]"
            :class="{ spinning: themeAnimating }"
          >
            <!-- System -->
            <svg v-if="appStore.settings.theme === 'system'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <rect x="2" y="3" width="20" height="14" rx="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            <!-- Light -->
            <svg v-else-if="appStore.settings.theme === 'light'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="4"/>
              <line x1="12" y1="2" x2="12" y2="5"/>
              <line x1="12" y1="19" x2="12" y2="22"/>
              <line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/>
              <line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/>
              <line x1="2" y1="12" x2="5" y2="12"/>
              <line x1="19" y1="12" x2="22" y2="12"/>
              <line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/>
              <line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/>
            </svg>
            <!-- Dark -->
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
            </svg>
          </button>
        </div>
        <div class="app-actions">
          <button class="btn-icon-action" @click="lockApp" :disabled="!appStore.settings.pinEnabled" title="Блокировка">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <rect x="3" y="11" width="18" height="11" rx="2"/>
              <path d="M7 11V7a5 5 0 0110 0v4"/>
            </svg>
          </button>
          <button class="btn-icon-action mobile-menu-btn" @click="toggleMobileMenu" :class="{ active: mobileMenuOpen }">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <template v-if="!mobileMenuOpen">
                <line x1="3" y1="6" x2="21" y2="6"/>
                <line x1="3" y1="12" x2="21" y2="12"/>
                <line x1="3" y1="18" x2="21" y2="18"/>
              </template>
              <template v-else>
                <line x1="6" y1="6" x2="18" y2="18"/>
                <line x1="6" y1="18" x2="18" y2="6"/>
              </template>
            </svg>
          </button>
        </div>
      </div>

      <!-- Desktop nav -->
      <div class="app-container desktop-nav-wrap">
        <nav class="app-nav">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav-link"
          >
            <!-- Members -->
            <svg v-if="item.icon === 'members'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 014-4h4a4 4 0 014 4v2"/><circle cx="19" cy="9" r="2.5"/><path d="M19 15a3 3 0 013 3v3"/>
            </svg>
            <!-- Tree -->
            <svg v-if="item.icon === 'tree'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="5" r="2.5"/><line x1="12" y1="7.5" x2="12" y2="11"/><line x1="6" y1="11" x2="18" y2="11"/><circle cx="6" cy="14" r="2"/><circle cx="18" cy="14" r="2"/><line x1="6" y1="11" x2="6" y2="12"/><line x1="18" y1="11" x2="18" y2="12"/><line x1="6" y1="16" x2="6" y2="19"/><line x1="18" y1="16" x2="18" y2="19"/>
            </svg>
            <!-- Photos -->
            <svg v-if="item.icon === 'photos'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>
            </svg>
            <!-- Export -->
            <svg v-if="item.icon === 'export'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            <!-- Backup -->
            <svg v-if="item.icon === 'backup'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M12 2a7 7 0 017 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 017-7z"/><circle cx="12" cy="9" r="2.5"/>
            </svg>
            <!-- Server -->
            <svg v-if="item.icon === 'server'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/>
            </svg>
            <!-- Settings -->
            <svg v-if="item.icon === 'settings'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
            </svg>
            <!-- About -->
            <svg v-if="item.icon === 'about'" class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </nav>
      </div>

      <!-- Mobile dropdown menu -->
      <Transition name="dropdown">
        <div v-if="mobileMenuOpen" class="mobile-dropdown" @click="closeMobileMenu">
          <nav class="mobile-dropdown-nav">
            <RouterLink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              class="mobile-dropdown-link"
            >
              {{ item.label }}
            </RouterLink>
          </nav>
        </div>
      </Transition>
    </header>

    <!-- Mobile bottom nav -->
    <nav class="mobile-bottom-nav">
      <RouterLink
        v-for="item in mobileNavItems"
        :key="item.to"
        :to="item.to"
        class="bottom-nav-item"
      >
        <!-- Members -->
        <svg v-if="item.icon === 'members'" class="bottom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 014-4h4a4 4 0 014 4v2"/>
        </svg>
        <!-- Tree -->
        <svg v-if="item.icon === 'tree'" class="bottom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <circle cx="12" cy="5" r="2.5"/><line x1="12" y1="7.5" x2="12" y2="11"/><line x1="6" y1="11" x2="18" y2="11"/><circle cx="6" cy="14" r="2"/><circle cx="18" cy="14" r="2"/>
        </svg>
        <!-- Photos -->
        <svg v-if="item.icon === 'photos'" class="bottom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>
        </svg>
        <!-- Backup -->
        <svg v-if="item.icon === 'backup'" class="bottom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M19 11H5a4 4 0 00-4 4v0a4 4 0 004 4h14a4 4 0 004-4v0a4 4 0 00-4-4z"/><path d="M8 11V7a4 4 0 118 0v4"/>
        </svg>
        <!-- Settings -->
        <svg v-if="item.icon === 'settings'" class="bottom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
        <span class="bottom-label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <main>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  overflow-x: clip;
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
  background: var(--orb1-color);
  left: -80px;
  top: -80px;
  animation: float 22s ease-in-out infinite;
}

.orb-2 {
  width: 300px;
  height: 300px;
  background: var(--orb2-color);
  right: -60px;
  top: 30%;
  animation: float 28s ease-in-out infinite reverse;
}

.orb-3 {
  width: 260px;
  height: 260px;
  background: var(--orb3-color);
  left: 30%;
  bottom: -100px;
  animation: float 18s ease-in-out infinite 5s;
}

/* ===== HEADER ===== */
.app-header {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 200;
  background: rgba(11, 14, 23, 0.82);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
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
  min-width: 0;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text);
  text-decoration: none;
  font-weight: 700;
  letter-spacing: 0.02em;
  transition: opacity var(--transition-fast);
  min-width: 0;
}

.brand-link:hover {
  opacity: 0.85;
}

.brand-logo {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border: 1px solid color-mix(in srgb, var(--color-glass-border) 75%, transparent);
}

.brand-text {
  background: var(--gradient-accent);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-size: 1.1rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(54vw, 260px);
}

.theme-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--color-glass-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast),
              border-color var(--transition-fast), transform var(--transition-fast);
  flex-shrink: 0;
}

.theme-toggle-btn svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  transition: transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.theme-toggle-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-accent-light);
  border-color: rgba(124, 92, 252, 0.4);
  transform: scale(1.08);
}

.theme-toggle-btn.spinning svg {
  animation: theme-spin 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes theme-spin {
  0%   { transform: rotate(0deg) scale(0.6); opacity: 0.4; }
  60%  { transform: rotate(200deg) scale(1.15); opacity: 1; }
  100% { transform: rotate(180deg) scale(1); opacity: 1; }
}

.app-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-icon-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid var(--color-glass-border);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-icon-action svg {
  width: 18px;
  height: 18px;
}

.btn-icon-action:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
  border-color: rgba(255, 255, 255, 0.2);
}

.btn-icon-action:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.mobile-menu-btn {
  display: none;
}

/* ===== DESKTOP NAV ===== */
.desktop-nav-wrap {
  overflow-x: auto;
  scrollbar-width: thin;
}

.desktop-nav-wrap::-webkit-scrollbar {
  height: 6px;
}

.desktop-nav-wrap::-webkit-scrollbar-thumb {
  border-radius: 999px;
}

.desktop-nav-wrap::-webkit-scrollbar-track {
  background: transparent;
}

.app-nav {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  padding: 8px 0 10px;
  min-width: max-content;
}

.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  text-decoration: none;
  padding: 6px 14px;
  font-size: 0.83rem;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.nav-link:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
  border-color: rgba(255, 255, 255, 0.18);
  transform: translateY(-1px);
}

.nav-link.router-link-active {
  color: var(--color-text);
  border-color: rgba(124, 92, 252, 0.7);
  background: rgba(124, 92, 252, 0.12);
  box-shadow: 0 0 16px rgba(124, 92, 252, 0.15);
}

.nav-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* ===== MOBILE DROPDOWN ===== */
.mobile-dropdown {
  position: fixed;
  top: 58px;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  z-index: 199;
}

.mobile-dropdown-nav {
  background: var(--color-bg-alt);
  border-bottom: 1px solid var(--color-glass-border);
  box-shadow: var(--shadow-elevated);
  display: flex;
  flex-direction: column;
  padding: 8px 8px max(8px, env(safe-area-inset-bottom));
  gap: 2px;
  max-height: calc(100vh - 58px);
  overflow-y: auto;
}

.mobile-dropdown-link {
  display: flex;
  align-items: center;
  min-height: 48px;
  padding: 10px 16px;
  color: var(--color-text-secondary);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.95rem;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.mobile-dropdown-link:hover,
.mobile-dropdown-link.router-link-active {
  background: rgba(124, 92, 252, 0.1);
  color: var(--color-text);
}

.dropdown-enter-active {
  animation: fadeIn 0.2s ease-out;
}

.dropdown-leave-active {
  animation: fadeIn 0.15s ease-in reverse;
}

/* ===== MOBILE BOTTOM NAV ===== */
.mobile-bottom-nav {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 200;
  background: rgba(11, 14, 23, 0.92);
  background: color-mix(in srgb, var(--color-bg-alt) 92%, transparent);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
  border-top: 1px solid var(--color-glass-border);
  padding: 4px 8px;
  padding-bottom: max(4px, env(safe-area-inset-bottom));
}

.bottom-nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 4px;
  text-decoration: none;
  color: var(--color-text-muted);
  font-size: 0.65rem;
  font-weight: 500;
  border-radius: 10px;
  transition: all var(--transition-fast);
  flex: 1;
  min-width: 0;
  min-height: 52px;
  justify-content: center;
}

.bottom-nav-item.router-link-active {
  color: var(--color-accent-light);
}

.bottom-nav-item.router-link-active .bottom-icon {
  filter: drop-shadow(0 0 6px rgba(124, 92, 252, 0.5));
}

.bottom-icon {
  width: 23px;
  height: 23px;
  flex-shrink: 0;
}

.bottom-nav-item:active {
  transform: scale(0.97);
}

.bottom-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

main {
  position: relative;
  z-index: 1;
  padding-bottom: calc(74px + env(safe-area-inset-bottom));
}

/* ===== RESPONSIVE ===== */
@media (max-width: 768px) {
  .desktop-nav-wrap {
    display: none;
  }

  .mobile-menu-btn {
    display: flex;
  }

  .mobile-bottom-nav {
    display: flex;
    justify-content: space-around;
  }

  /* Увеличиваем тап-зону кнопок до рекомендованных 44px */
  .btn-icon-action {
    width: 44px;
    height: 44px;
    border-radius: 12px;
  }
}

@media (min-width: 769px) {
  main {
    padding-bottom: 0;
  }
}

@media (max-width: 480px) {
  .app-header-inner {
    gap: 10px;
  }

  .brand-text {
    font-size: 0.95rem;
    max-width: min(46vw, 180px);
  }

  .bottom-label {
    font-size: 0.6rem;
  }

  /* На очень мальких экранах подписи навигации скрываем */
  .bottom-label {
    display: none;
  }

  .bottom-icon {
    width: 26px;
    height: 26px;
  }
}
</style>
