<script setup lang="ts">
// OfflineBanner.vue
//
// Design refs: §4.5 Offline detector, §4.6 Pending-changes badge.
// Requirements: 12.1, 12.2, 12.3, 12.4.
//
// Pinned-to-top banner shown while the Web client is in Offline_State.
// Reads `isOffline` from `@/services/offlineDetector` and toggles
// `document.body.dataset.offline` so descendants tagged with the
// `data-disable-offline` attribute can be visually + interactively disabled
// via the CSS rule emitted at the bottom of this component.
//
// Controls that should be auto-disabled while offline (e.g. anything that
// triggers POST /v2/backup/upload) just need to add:
//   <button data-disable-offline title="Невозможно загрузить в офлайне">
// and the global rule below will gray them out and block pointer events.

import { onBeforeUnmount, onMounted, watch } from 'vue'
import { isOffline } from '@/services/offlineDetector'

function useOfflineDataAttr(): void {
  function apply(value: boolean): void {
    if (typeof document === 'undefined') return
    if (value) {
      document.body.dataset.offline = 'true'
    } else {
      delete document.body.dataset.offline
    }
  }

  let stopWatch: (() => void) | null = null

  onMounted(() => {
    apply(isOffline.value)
    stopWatch = watch(isOffline, (next) => apply(next), { flush: 'post' })
  })

  onBeforeUnmount(() => {
    if (stopWatch !== null) {
      stopWatch()
      stopWatch = null
    }
    apply(false)
  })
}

useOfflineDataAttr()
</script>

<template>
  <div v-if="isOffline" class="offline-banner" role="status" aria-live="polite">
    Вы офлайн. Изменения не синхронизируются с сервером и могут быть перезаписаны другим устройством
  </div>
</template>

<style scoped>
.offline-banner {
  position: fixed;
  top: 110px;
  left: 0;
  right: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin: 0 auto;
  padding: 10px 20px;
  background: linear-gradient(135deg, #c0392b 0%, #e74c3c 100%);
  color: #ffffff;
  font-weight: 600;
  font-size: 0.95rem;
  line-height: 1.35;
  text-align: center;
  text-wrap: balance;
  box-shadow: 0 6px 18px rgba(192, 57, 43, 0.35);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.offline-banner::before {
  content: '⚠';
  font-size: 1.15rem;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .offline-banner {
    top: 56px;
    padding: 8px 14px;
    font-size: 0.86rem;
  }
}

@media (max-width: 480px) {
  .offline-banner {
    top: 60px;
  }
}
</style>

<style>
/* Offset .app-page so the fixed banner does not cover the page header. */
body[data-offline='true'] .app-page {
  padding-top: calc(124px + 56px);
}

@media (max-width: 768px) {
  body[data-offline='true'] .app-page {
    padding-top: calc(118px + 60px);
  }
}

@media (max-width: 480px) {
  body[data-offline='true'] .app-page {
    padding-top: calc(122px + 64px);
  }
}

@media (max-width: 360px) {
  body[data-offline='true'] .app-page {
    padding-top: calc(128px + 70px);
  }
}

/* Global: any control opting in via data-disable-offline becomes
   non-interactive while body[data-offline="true"]. Tooltip is supplied by
   the consumer via a `title` attribute (e.g. "Невозможно загрузить в офлайне"). */
body[data-offline='true'] [data-disable-offline] {
  pointer-events: none;
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
