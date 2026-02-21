<script setup lang="ts">
import { computed } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useAppStore } from '@/stores/appStore'

const appStore = useAppStore()

const appVersion = String(import.meta.env.VITE_APP_VERSION || '1.0.0')
const productionDomain = 'https://totalcode.indevs.in'

const links = computed(() =>
  [
    { label: 'Production сайт', href: productionDomain },
    { label: 'API health', href: `${productionDomain}/api/health` }
  ].filter((item) => Boolean(item.href))
)
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader title="О приложении" subtitle="FamilyOne Web (PWA) без update-checker в web-версии" />

      <article class="app-card about-card">
        <div class="kv-grid">
          <div class="kv-item">
            <strong>Версия</strong>
            <span>{{ appVersion }}</span>
          </div>
          <div class="kv-item">
            <strong>Язык</strong>
            <span>Русский (v1)</span>
          </div>
          <div class="kv-item">
            <strong>Хранение</strong>
            <span>Local-first (IndexedDB в браузере)</span>
          </div>
          <div class="kv-item">
            <strong>API base</strong>
            <span>{{ appStore.settings.apiBaseUrl }}</span>
          </div>
        </div>

        <section class="text-block">
          <h2>Приватность и обработка данных</h2>
          <p>
            Данные семьи по умолчанию хранятся локально. Сервер используется только для распознавания лиц,
            генерации PDF и серверного backup по явному действию пользователя.
          </p>
        </section>

        <section class="text-block">
          <h2>PWA режим</h2>
          <p>
            Приложение можно установить как standalone в Chromium-браузерах. Offline доступ обеспечивается для
            app-shell и локальных данных.
          </p>
        </section>

        <section class="text-block" v-if="links.length">
          <h2>Ссылки</h2>
          <div class="link-list">
            <a v-for="link in links" :key="link.href" :href="link.href" target="_blank" rel="noopener noreferrer">
              {{ link.label }}
            </a>
          </div>
        </section>
      </article>
    </div>
  </section>
</template>

<style scoped>
.about-card {
  padding: 16px;
}

.kv-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.kv-item {
  border: 1px solid var(--color-glass-border);
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kv-item strong {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
}

.text-block {
  margin-top: 14px;
}

.text-block h2 {
  font-size: 1rem;
  margin-bottom: 6px;
}

.text-block p {
  color: var(--color-text-secondary);
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.link-list a {
  color: var(--color-text);
  text-decoration: none;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  padding: 6px 10px;
}
</style>
