import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { registerSW } from 'virtual:pwa-register'
import App from './App.vue'
import router from './router'
import './assets/main.css'
import './assets/app.css'

const CACHE_RESET_VERSION = '2026-04-03-restore-portable-auth-sync-1'
const CACHE_RESET_KEY = 'familyone_cache_reset_version'
const BROWSER_PROBE_KEY = 'familyone_browser_support_probe'
const INDEXED_DB_PROBE_NAME = 'familyone_browser_probe_db'

async function settlePromises(promises: Array<Promise<unknown>>): Promise<void> {
  await Promise.all(promises.map(async (promise) => {
    try {
      await promise
    } catch {
      // ignore one-off cleanup errors
    }
  }))
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function probeStorageAccess(storageName: 'localStorage' | 'sessionStorage'): boolean {
  try {
    const storage = window[storageName]
    storage.setItem(BROWSER_PROBE_KEY, '1')
    storage.removeItem(BROWSER_PROBE_KEY)
    return true
  } catch {
    return false
  }
}

async function probeIndexedDbAccess(): Promise<boolean> {
  if (typeof window === 'undefined' || !('indexedDB' in window)) {
    return false
  }

  return new Promise<boolean>((resolve) => {
    let finished = false
    const request = window.indexedDB.open(INDEXED_DB_PROBE_NAME)
    const timeoutId = window.setTimeout(() => {
      finish(false)
    }, 1500)

    const finish = (ok: boolean) => {
      if (finished) return
      finished = true
      window.clearTimeout(timeoutId)
      try {
        request.result?.close()
      } catch {
        // ignore cleanup errors
      }
      try {
        window.indexedDB.deleteDatabase(INDEXED_DB_PROBE_NAME)
      } catch {
        // ignore cleanup errors
      }
      resolve(ok)
    }

    request.onerror = () => finish(false)
    request.onblocked = () => finish(false)
    request.onsuccess = () => finish(true)
    request.onupgradeneeded = () => {}
  })
}

async function collectBrowserSupportIssues(): Promise<string[]> {
  const issues: string[] = []

  if (typeof window.fetch !== 'function') {
    issues.push('В браузере нет поддержки Fetch API для сетевых запросов.')
  }
  if (!probeStorageAccess('localStorage')) {
    issues.push('Недоступно localStorage. Проверьте настройки приватности или режим инкогнито.')
  }
  if (!probeStorageAccess('sessionStorage')) {
    issues.push('Недоступно sessionStorage. Без него не работают некоторые защитные сценарии приложения.')
  }
  if (!(await probeIndexedDbAccess())) {
    issues.push('Недоступно IndexedDB. Локальное хранение семейного древа и офлайн-режим не смогут работать.')
  }

  return issues
}

function renderUnsupportedBrowserScreen(issues: string[]): void {
  const root = document.querySelector<HTMLDivElement>('#app')
  if (!root) return

  const issueList = issues
    .map((issue) => `<li>${escapeHtml(issue)}</li>`)
    .join('')

  root.innerHTML = `
    <section style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;background:#0b0e17;color:#f4f7ff;font-family:Segoe UI,Arial,sans-serif;">
      <div style="width:min(680px,100%);padding:28px;border-radius:24px;border:1px solid rgba(255,255,255,0.08);background:rgba(17,22,34,0.96);box-shadow:0 24px 80px rgba(0,0,0,0.35);">
        <div style="display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(124,92,252,0.12);color:#bca8ff;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;">Проверка совместимости</div>
        <h1 style="margin:18px 0 10px;font-size:32px;line-height:1.15;">Браузер или его текущий режим не поддерживается</h1>
        <p style="margin:0 0 14px;color:rgba(244,247,255,0.78);font-size:16px;line-height:1.7;">
          Семейное древо использует современные браузерные API для локального хранения данных, резервных копий и стабильной работы при плохой сети.
        </p>
        <p style="margin:0 0 18px;color:rgba(244,247,255,0.7);font-size:15px;line-height:1.7;">
          Обновите браузер или откройте сайт в актуальном Chrome, Edge или Яндекс Браузере. Если у вас включён жёсткий приватный режим, попробуйте открыть сайт в обычном окне.
        </p>
        <ul style="margin:0 0 22px;padding-left:20px;color:rgba(244,247,255,0.88);line-height:1.65;">
          ${issueList}
        </ul>
        <button type="button" data-reload-browser-check style="padding:12px 18px;border:none;border-radius:14px;background:linear-gradient(135deg,#7c5cfc,#eb6fb7);color:white;font-size:15px;font-weight:600;cursor:pointer;">
          Повторить проверку
        </button>
      </div>
    </section>
  `

  root.querySelector<HTMLButtonElement>('[data-reload-browser-check]')?.addEventListener('click', () => {
    window.location.reload()
  })
}

async function ensureBrowserSupport(): Promise<boolean> {
  const issues = await collectBrowserSupportIssues()
  if (!issues.length) {
    return true
  }

  renderUnsupportedBrowserScreen(issues)
  return false
}

async function resetPwaCacheIfNeeded(): Promise<boolean> {
  try {
    const lastApplied = localStorage.getItem(CACHE_RESET_KEY)
    if (lastApplied === CACHE_RESET_VERSION) {
      return false
    }

    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations()
      await settlePromises(registrations.map((registration) => registration.unregister()))
    }

    if ('caches' in window) {
      const cacheNames = await caches.keys()
      await settlePromises(cacheNames.map((cacheName) => caches.delete(cacheName)))
    }

    localStorage.setItem(CACHE_RESET_KEY, CACHE_RESET_VERSION)
    window.location.reload()
    return true
  } catch {
    return false
  }
}

async function bootstrap(): Promise<void> {
  const browserSupported = await ensureBrowserSupport()
  if (!browserSupported) {
    return
  }

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
