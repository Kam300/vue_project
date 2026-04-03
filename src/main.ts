import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { registerSW } from 'virtual:pwa-register'
import App from './App.vue'
import router from './router'
import './assets/main.css'
import './assets/app.css'

const CACHE_RESET_VERSION = '2026-04-03-restore-portable-auth-sync-1'
const CACHE_RESET_KEY = 'familyone_cache_reset_version'

async function resetPwaCacheIfNeeded(): Promise<boolean> {
  try {
    const lastApplied = localStorage.getItem(CACHE_RESET_KEY)
    if (lastApplied === CACHE_RESET_VERSION) {
      return false
    }

    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations()
      await Promise.allSettled(registrations.map((registration) => registration.unregister()))
    }

    if ('caches' in window) {
      const cacheNames = await caches.keys()
      await Promise.allSettled(cacheNames.map((cacheName) => caches.delete(cacheName)))
    }

    localStorage.setItem(CACHE_RESET_KEY, CACHE_RESET_VERSION)
    window.location.reload()
    return true
  } catch {
    return false
  }
}

async function bootstrap(): Promise<void> {
  const resetTriggered = await resetPwaCacheIfNeeded()
  if (resetTriggered) {
    return
  }

  const updateSW = registerSW({
    immediate: true
  })
  updateSW(true)

  const app = createApp(App)
  app.use(createPinia())
  app.use(router)
  app.mount('#app')
}

void bootstrap()
