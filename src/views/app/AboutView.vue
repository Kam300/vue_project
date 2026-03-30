<script setup lang="ts">
import { computed } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { useAppStore } from '@/stores/appStore'
import logoIcon from '@/assets/icon.png'

const appStore = useAppStore()

const appVersion = String(import.meta.env.VITE_APP_VERSION || '1.0.0')
const productionDomain = 'https://totalcode.indevs.in'
const androidApkUrl = '/app-debug.apk'

const links = computed(() =>
  [
    { icon: 'language', label: 'Production сайт', href: productionDomain },
    { icon: 'favorite', label: 'API health', href: `${productionDomain}/api/health` }
  ].filter((item) => Boolean(item.href))
)

const infoItems = [
  { icon: 'inventory_2', label: 'Версия', value: appVersion },
  { icon: 'language', label: 'Язык', value: 'Русский (v1)' },
  { icon: 'database', label: 'Хранение', value: 'Local-first (IndexedDB)' },
]
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader icon="info" title="О проекте" subtitle="FamilyOne Web (PWA)" />

      <article class="app-card about-card">
        <!-- App info header -->
        <div class="about-hero">
          <div class="about-logo">
            <img :src="logoIcon" alt="FamilyOne logo" class="about-logo-img" />
          </div>
          <div>
            <h2 class="about-app-name">FamilyOne</h2>
            <p class="about-tagline">Семейное Древо — PWA</p>
            <div class="about-actions">
              <span class="android-note">Доступно Android-приложение</span>
              <a class="apk-link-btn" :href="androidApkUrl" download="app-debug.apk">
                <AppIcon name="android" :size="18" />
                Скачать app-debug.apk
              </a>
            </div>
          </div>
        </div>

        <div class="section-divider"></div>

        <!-- Info grid -->
        <div class="kv-grid">
          <div v-for="item in infoItems" :key="item.label" class="kv-item">
            <AppIcon :name="item.icon" :size="20" class="kv-icon" />
            <div>
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }}</span>
            </div>
          </div>
          <div class="kv-item">
            <AppIcon name="link" :size="20" class="kv-icon" />
            <div>
              <strong>API base</strong>
              <span>{{ appStore.settings.apiBaseUrl }}</span>
            </div>
          </div>
        </div>

        <div class="section-divider"></div>

        <section class="text-block">
          <h2 class="section-head">
            <AppIcon name="lock" :size="20" />
            Приватность и обработка данных
          </h2>
          <p>
            Данные семьи по умолчанию хранятся локально. Сервер используется только для распознавания лиц,
            генерации PDF и серверного backup по явному действию пользователя.
          </p>
        </section>

        <section class="text-block">
          <h2 class="section-head">
            <AppIcon name="phone_iphone" :size="20" />
            PWA режим
          </h2>
          <p>
            Приложение можно установить как standalone в Chromium-браузерах. Offline доступ обеспечивается для
            app-shell и локальных данных.
          </p>
        </section>

        <section class="text-block" v-if="links.length">
          <h2 class="section-head">
            <AppIcon name="link" :size="20" />
            Ссылки
          </h2>
          <div class="link-list">
            <a v-for="link in links" :key="link.href" :href="link.href" target="_blank" rel="noopener noreferrer" class="link-card">
              <AppIcon :name="link.icon" :size="18" />
              {{ link.label }}
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
          </div>
        </section>
      </article>
    </div>
  </section>
</template>

<style scoped>
.about-card {
  padding: 24px;
}

.about-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 4px;
}

.about-logo {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  background: rgba(124, 92, 252, 0.1);
  border: 1px solid rgba(124, 92, 252, 0.25);
}

.about-logo-img {
  width: 44px;
  height: 44px;
  object-fit: cover;
  border-radius: 50%;
}

.about-app-name {
  font-size: 1.5rem;
  font-weight: 700;
  background: var(--gradient-accent);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.about-tagline {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.about-actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.android-note {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}

.apk-link-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.82rem;
  color: var(--color-text);
  transition: all var(--transition-fast);
}

.apk-link-btn:hover {
  border-color: rgba(124, 92, 252, 0.4);
  background: var(--card-hover-bg);
}

.kv-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.kv-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  padding: 12px;
  transition: all var(--transition-fast);
}

.kv-item:hover {
  border-color: rgba(124, 92, 252, 0.2);
  background: var(--card-hover-bg);
}

.kv-icon {
  color: var(--color-accent-light);
  flex-shrink: 0;
}

.kv-item strong {
  display: block;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.kv-item span {
  font-size: 0.88rem;
}

.text-block {
  margin-top: 16px;
}

.text-block h2 {
  font-size: 1rem;
  margin-bottom: 8px;
  font-weight: 600;
}

.section-head {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.text-block p {
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.link-card {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text);
  text-decoration: none;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  padding: 8px 16px;
  font-size: 0.88rem;
  transition: all var(--transition-fast);
}

.link-card:hover {
  border-color: var(--color-accent);
  background: var(--card-hover-bg);
  transform: translateY(-1px);
}
</style>
