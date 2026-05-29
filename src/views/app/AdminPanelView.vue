<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAppStore } from '@/stores/appStore'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import {
  adminAudit,
  adminBackups,
  adminBulkDeleteUsers,
  adminDeleteBackup,
  adminDeleteFace,
  adminDeleteUser,
  adminFaces,
  adminSetUserAdmin,
  adminStats,
  adminUsers,
  healthCheck
} from '@/services/api'
import type {
  AdminAuditLogItem,
  AdminBackupItem,
  AdminFaceItem,
  AdminStatsResponse,
  AdminUserItem,
  HealthResponse
} from '@/types/api'

const appStore = useAppStore()
const deviceId = computed(() => appStore.settings.deviceId || '')

type Tab = 'overview' | 'users' | 'backups' | 'audit' | 'faces'
const activeTab = ref<Tab>('overview')

// Users filters
const userSearch = ref('')
type UserFilter = 'all' | 'authorized' | 'admins' | 'inactive'
const userFilter = ref<UserFilter>('all')

// Bulk selection (users)
const selectedUserIds = ref<Set<number>>(new Set())

const stats = ref<AdminStatsResponse | null>(null)
const health = ref<HealthResponse | null>(null)
const users = ref<AdminUserItem[]>([])
const backups = ref<AdminBackupItem[]>([])
const audit = ref<AdminAuditLogItem[]>([])
const faces = ref<AdminFaceItem[]>([])

const busy = ref(false)
const errorMsg = ref('')
const infoMsg = ref('')

function formatBytes(bytes?: number | null): string {
  if (!bytes && bytes !== 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  try {
    const d = new Date(value)
    if (isNaN(d.getTime())) return value
    return d.toLocaleString('ru-RU')
  } catch {
    return value
  }
}

function providerChips(providers: string[]): Array<{ name: string; count: number }> {
  const counts = new Map<string, number>()
  for (const p of providers) {
    if (!p) continue
    counts.set(p, (counts.get(p) || 0) + 1)
  }
  return Array.from(counts.entries()).map(([name, count]) => ({ name, count }))
}

async function loadOverview(): Promise<void> {
  busy.value = true
  errorMsg.value = ''
  try {
    const [statsResp, healthResp] = await Promise.all([
      adminStats(deviceId.value),
      healthCheck({ timeoutMs: 8000 }).catch(() => null)
    ])
    stats.value = statsResp
    health.value = healthResp
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  } finally {
    busy.value = false
  }
}

async function loadUsers(): Promise<void> {
  busy.value = true
  errorMsg.value = ''
  try {
    const resp = await adminUsers(deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Не удалось загрузить пользователей')
    users.value = resp.users
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  } finally {
    busy.value = false
  }
}

const filteredUsers = computed<AdminUserItem[]>(() => {
  const search = userSearch.value.trim().toLowerCase()
  return users.value.filter((u) => {
    const isAuthorized = u.providers.some((p) => p && p !== 'local')
    const isInactive = !isAuthorized && u.personsCount === 0 && u.backupsCount === 0

    if (userFilter.value === 'authorized' && !isAuthorized) return false
    if (userFilter.value === 'admins' && !u.isAdmin) return false
    if (userFilter.value === 'inactive' && !isInactive) return false

    if (search) {
      const haystack = [
        u.displayName,
        u.email || '',
        u.phone || '',
        String(u.id),
        u.providers.join(' ')
      ]
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(search)) return false
    }

    return true
  })
})

const userStats = computed(() => {
  const total = users.value.length
  const authorized = users.value.filter((u) => u.providers.some((p) => p && p !== 'local')).length
  const admins = users.value.filter((u) => u.isAdmin).length
  const inactive = users.value.filter(
    (u) =>
      !u.providers.some((p) => p && p !== 'local') &&
      u.personsCount === 0 &&
      u.backupsCount === 0
  ).length
  return { total, authorized, admins, inactive }
})

// --- Bulk-selection helpers ---
const selectableUsers = computed<AdminUserItem[]>(() =>
  filteredUsers.value.filter((u) => !u.isAdmin)
)

const allSelected = computed<boolean>(() =>
  selectableUsers.value.length > 0 &&
  selectableUsers.value.every((u) => selectedUserIds.value.has(u.id))
)

const someSelected = computed<boolean>(() =>
  selectableUsers.value.some((u) => selectedUserIds.value.has(u.id))
)

function toggleUser(id: number): void {
  const next = new Set(selectedUserIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedUserIds.value = next
}

function toggleAllVisible(): void {
  const next = new Set(selectedUserIds.value)
  if (allSelected.value) {
    selectableUsers.value.forEach((u) => next.delete(u.id))
  } else {
    selectableUsers.value.forEach((u) => next.add(u.id))
  }
  selectedUserIds.value = next
}

function clearSelection(): void {
  selectedUserIds.value = new Set()
}

async function bulkDeleteSelected(): Promise<void> {
  const ids = Array.from(selectedUserIds.value)
  if (!ids.length) return
  if (!confirm(
    `Удалить ${ids.length} пользователей со всеми их данными? Действие необратимо.`
  )) return

  try {
    const resp = await adminBulkDeleteUsers(ids, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Ошибка массового удаления')
    const skippedCount = resp.skipped?.length || 0
    infoMsg.value = `Удалено: ${resp.deleted}` + (skippedCount ? `, пропущено: ${skippedCount}` : '')
    clearSelection()
    await loadUsers()
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  }
}

async function loadBackups(): Promise<void> {
  busy.value = true
  errorMsg.value = ''
  try {
    const resp = await adminBackups(deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Не удалось загрузить бэкапы')
    backups.value = resp.backups
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  } finally {
    busy.value = false
  }
}

async function loadAudit(): Promise<void> {
  busy.value = true
  errorMsg.value = ''
  try {
    const resp = await adminAudit(200, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Не удалось загрузить журнал')
    audit.value = resp.logs
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  } finally {
    busy.value = false
  }
}

async function loadFaces(): Promise<void> {
  busy.value = true
  errorMsg.value = ''
  try {
    const resp = await adminFaces(deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Не удалось загрузить базу лиц')
    faces.value = resp.encodings
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  } finally {
    busy.value = false
  }
}

async function setTab(tab: Tab): Promise<void> {
  activeTab.value = tab
  infoMsg.value = ''
  errorMsg.value = ''
  if (tab === 'overview') await loadOverview()
  else if (tab === 'users') await loadUsers()
  else if (tab === 'backups') await loadBackups()
  else if (tab === 'audit') await loadAudit()
  else if (tab === 'faces') await loadFaces()
}

async function toggleAdmin(user: AdminUserItem): Promise<void> {
  if (!confirm(
    user.isAdmin
      ? `Снять права администратора у «${user.displayName}»?`
      : `Сделать «${user.displayName}» администратором?`
  )) return

  try {
    const resp = await adminSetUserAdmin(user.id, !user.isAdmin, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Ошибка')
    infoMsg.value = 'Права обновлены'
    await loadUsers()
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  }
}

async function removeUser(user: AdminUserItem): Promise<void> {
  if (!confirm(
    `Удалить пользователя «${user.displayName}» и все его данные? Действие необратимо.`
  )) return

  try {
    const resp = await adminDeleteUser(user.id, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Ошибка удаления')
    infoMsg.value = 'Пользователь удалён'
    await loadUsers()
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  }
}

async function removeBackup(backup: AdminBackupItem): Promise<void> {
  if (!confirm(`Удалить бэкап #${backup.id} (${backup.ownerName || 'без владельца'})?`)) return

  try {
    const resp = await adminDeleteBackup(backup.id, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Ошибка удаления')
    infoMsg.value = 'Бэкап удалён'
    await loadBackups()
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  }
}

async function removeFace(face: AdminFaceItem): Promise<void> {
  const name = face.personName || `#${face.personId}`
  if (!confirm(`Удалить эталонное лицо «${name}»? Распознавание перестанет работать для этой персоны.`)) return

  try {
    const resp = await adminDeleteFace(face.id, deviceId.value)
    if (!resp.success) throw new Error(resp.error || 'Ошибка удаления')
    infoMsg.value = 'Эталонное лицо удалено'
    await loadFaces()
  } catch (reason) {
    errorMsg.value = (reason as Error).message
  }
}

onMounted(() => {
  void loadOverview()
})

let refreshTimer: number | null = null

watch(activeTab, (tab) => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (tab === 'overview') {
    refreshTimer = window.setInterval(() => {
      void loadOverview()
    }, 15_000)
  }
}, { immediate: true })

onUnmounted(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="shield_person"
        title="Панель администратора"
        subtitle="Управление пользователями, бэкапами, журналом и системой"
      />

      <article class="app-card admin-card">
        <div class="tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'overview' }"
            @click="setTab('overview')"
          >
            <AppIcon name="dashboard" :size="16" /> Обзор
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'users' }"
            @click="setTab('users')"
          >
            <AppIcon name="group" :size="16" /> Пользователи
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'backups' }"
            @click="setTab('backups')"
          >
            <AppIcon name="save" :size="16" /> Бэкапы
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'audit' }"
            @click="setTab('audit')"
          >
            <AppIcon name="list_alt" :size="16" /> Аудит
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'faces' }"
            @click="setTab('faces')"
          >
            <AppIcon name="face" :size="16" /> Лица
          </button>
        </div>

        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
        <p v-if="infoMsg" class="info-msg">{{ infoMsg }}</p>
        <div v-if="busy" class="loading">Загрузка...</div>

        <!-- ============= OVERVIEW ============= -->
        <div v-if="activeTab === 'overview' && stats" class="overview">
          <div v-if="stats.presence" class="presence-card">
            <div class="presence-pulse"></div>
            <div class="presence-info">
              <div class="presence-title">Сейчас на сайте</div>
              <div class="presence-value">{{ stats.presence.total }}</div>
              <div class="presence-meta">
                <span><AppIcon name="verified_user" :size="14" /> авторизованных: {{ stats.presence.authorized }}</span>
                <span><AppIcon name="public" :size="14" /> гостей: {{ stats.presence.anonymous }}</span>
              </div>
            </div>
          </div>

          <div class="metric-grid">
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="group" :size="22" /></div>
              <div class="metric-label">Пользователи</div>
              <div class="metric-value">{{ stats.users.total }}</div>
              <div class="metric-sub">админов: {{ stats.users.admins }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="account_tree" :size="22" /></div>
              <div class="metric-label">Деревья</div>
              <div class="metric-value">{{ stats.family_trees }}</div>
              <div class="metric-sub">персон: {{ stats.persons }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="image" :size="22" /></div>
              <div class="metric-label">Фотографии</div>
              <div class="metric-value">{{ stats.photos }}</div>
              <div class="metric-sub">связей: {{ stats.relationships }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="save" :size="22" /></div>
              <div class="metric-label">Бэкапы</div>
              <div class="metric-value">{{ stats.backups.count }}</div>
              <div class="metric-sub">{{ formatBytes(stats.backups.total_bytes) }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="storage" :size="22" /></div>
              <div class="metric-label">База данных</div>
              <div class="metric-value">{{ formatBytes(stats.database.size_bytes) }}</div>
              <div class="metric-sub">аудит: {{ stats.audit_logs }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-icon"><AppIcon name="face" :size="22" /></div>
              <div class="metric-label">Распознавание</div>
              <div class="metric-value">{{ stats.face_encodings }}</div>
              <div class="metric-sub">эталонов лиц</div>
            </div>
          </div>

          <h3 class="section-title">Состояние сервера</h3>
          <div v-if="health" class="server-status">
            <div class="status-row">
              <span class="status-key">Статус</span>
              <span class="chip success">Онлайн</span>
            </div>
            <div class="status-row">
              <span class="status-key">Версия</span>
              <span>{{ health.service }}</span>
            </div>
            <div class="status-row">
              <span class="status-key">Распознавание лиц</span>
              <span class="chip" :class="{ success: health.face_recognition }">
                {{ health.face_recognition ? 'Активно' : 'Выключено' }}
              </span>
            </div>
            <div class="status-row">
              <span class="status-key">PDF-генерация</span>
              <span class="chip" :class="{ success: health.pdf_generation }">
                {{ health.pdf_generation ? 'Активно' : 'Выключено' }}
              </span>
            </div>
            <div class="status-row">
              <span class="status-key">Backup API</span>
              <span class="chip" :class="{ success: health.backup }">
                {{ health.backup ? 'Активно' : 'Выключено' }}
              </span>
            </div>
            <div class="status-row" v-if="health.gpu">
              <span class="status-key">Вычисления</span>
              <span>{{ health.gpu.active_cuda ? 'CUDA (GPU)' : 'CPU/HOG' }} · {{ health.gpu.face_model }}</span>
            </div>
          </div>
          <div v-else class="status-row">
            <span class="chip error">Сервер недоступен</span>
          </div>

          <button class="btn-action" @click="loadOverview" :disabled="busy">
            <AppIcon name="refresh" :size="16" />
            Обновить
          </button>
        </div>

        <!-- ============= USERS ============= -->
        <div v-if="activeTab === 'users'" class="users-list">
          <div class="filter-bar">
            <input
              type="text"
              class="filter-input"
              placeholder="Поиск по имени, email, телефону, ID..."
              v-model="userSearch"
            />
            <div class="filter-pills">
              <button
                class="pill"
                :class="{ active: userFilter === 'all' }"
                @click="userFilter = 'all'"
              >
                Все ({{ userStats.total }})
              </button>
              <button
                class="pill"
                :class="{ active: userFilter === 'authorized' }"
                @click="userFilter = 'authorized'"
              >
                Авторизованные ({{ userStats.authorized }})
              </button>
              <button
                class="pill"
                :class="{ active: userFilter === 'admins' }"
                @click="userFilter = 'admins'"
              >
                Админы ({{ userStats.admins }})
              </button>
              <button
                class="pill"
                :class="{ active: userFilter === 'inactive' }"
                @click="userFilter = 'inactive'"
              >
                Неактивные ({{ userStats.inactive }})
              </button>
            </div>
          </div>

          <div v-if="someSelected" class="bulk-bar">
            <span class="bulk-count">Выбрано: {{ selectedUserIds.size }}</span>
            <button class="btn-action" @click="clearSelection">
              <AppIcon name="close" :size="16" /> Снять выбор
            </button>
            <button class="btn-action danger" @click="bulkDeleteSelected">
              <AppIcon name="delete" :size="16" /> Удалить выбранных
            </button>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th class="cell-check">
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    :indeterminate.prop="someSelected && !allSelected"
                    :disabled="!selectableUsers.length"
                    @change="toggleAllVisible"
                    title="Выбрать всех видимых (кроме админов)"
                  />
                </th>
                <th>ID</th>
                <th>Имя</th>
                <th>Email</th>
                <th>Провайдеры</th>
                <th>Персон</th>
                <th>Бэкапов</th>
                <th>Создан</th>
                <th>Admin</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="u in filteredUsers"
                :key="u.id"
                :class="{ 'row-selected': selectedUserIds.has(u.id) }"
              >
                <td class="cell-check">
                  <input
                    type="checkbox"
                    :checked="selectedUserIds.has(u.id)"
                    :disabled="u.isAdmin"
                    @change="toggleUser(u.id)"
                  />
                </td>
                <td>{{ u.id }}</td>
                <td>{{ u.displayName }}</td>
                <td>{{ u.email || '—' }}</td>
                <td>
                  <span
                    v-for="p in providerChips(u.providers)"
                    :key="p.name"
                    class="chip mini"
                  >
                    {{ p.name }}<span v-if="p.count > 1" class="chip-count"> × {{ p.count }}</span>
                  </span>
                </td>
                <td>{{ u.personsCount }}</td>
                <td>{{ u.backupsCount }}</td>
                <td>{{ formatDate(u.createdAt) }}</td>
                <td>
                  <span class="chip" :class="{ success: u.isAdmin }">
                    {{ u.isAdmin ? 'Да' : 'Нет' }}
                  </span>
                </td>
                <td class="actions">
                  <button class="btn-icon" :title="u.isAdmin ? 'Снять права админа' : 'Назначить админом'" @click="toggleAdmin(u)">
                    <AppIcon :name="u.isAdmin ? 'remove_moderator' : 'shield_person'" :size="18" />
                  </button>
                  <button class="btn-icon danger" :disabled="u.isAdmin" title="Удалить пользователя" @click="removeUser(u)">
                    <AppIcon name="delete" :size="18" />
                  </button>
                </td>
              </tr>
              <tr v-if="!filteredUsers.length && !busy">
                <td colspan="10" class="empty">Ничего не найдено</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ============= BACKUPS ============= -->
        <div v-if="activeTab === 'backups'" class="backups-list">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Владелец</th>
                <th>Дерево</th>
                <th>Размер</th>
                <th>Записей</th>
                <th>Файл</th>
                <th>Обновлён</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in backups" :key="b.id">
                <td>{{ b.id }}</td>
                <td>{{ b.ownerName || '—' }} <small v-if="b.ownerEmail">({{ b.ownerEmail }})</small></td>
                <td>{{ b.treeTitle || `#${b.treeId}` }}</td>
                <td>{{ formatBytes(b.sizeBytes) }}</td>
                <td>{{ b.membersCount }} / {{ b.memberPhotosCount }} / {{ b.assetsCount }}</td>
                <td>
                  <span class="chip" :class="{ success: b.fileExists, error: !b.fileExists }">
                    {{ b.fileExists ? 'OK' : 'Отсутствует' }}
                  </span>
                </td>
                <td>{{ formatDate(b.updatedAt) }}</td>
                <td class="actions">
                  <button class="btn-icon danger" title="Удалить бэкап" @click="removeBackup(b)">
                    <AppIcon name="delete" :size="18" />
                  </button>
                </td>
              </tr>
              <tr v-if="!backups.length && !busy">
                <td colspan="8" class="empty">Бэкапов нет</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ============= AUDIT ============= -->
        <div v-if="activeTab === 'audit'" class="audit-list">
          <table class="data-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Пользователь</th>
                <th>Действие</th>
                <th>Детали</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in audit" :key="log.id">
                <td>{{ formatDate(log.createdAt) }}</td>
                <td>{{ log.userName || `#${log.userId}` || '—' }}</td>
                <td><span class="chip mini">{{ log.action }}</span></td>
                <td><code class="audit-details">{{ log.detailsJson || '—' }}</code></td>
              </tr>
              <tr v-if="!audit.length && !busy">
                <td colspan="4" class="empty">Журнал пуст</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ============= FACES ============= -->
        <div v-if="activeTab === 'faces'" class="faces-list">
          <div class="btn-row" style="margin-bottom: 12px">
            <button class="btn-action" @click="loadFaces" :disabled="busy">
              <AppIcon name="refresh" :size="16" />
              Обновить
            </button>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Персона</th>
                <th>External ID</th>
                <th>Модель</th>
                <th>Активен</th>
                <th>Создан</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in faces" :key="f.id">
                <td>{{ f.id }}</td>
                <td>{{ f.personName || `#${f.personId}` }}</td>
                <td><code>{{ f.externalMemberId || '—' }}</code></td>
                <td>{{ f.modelVersion }}</td>
                <td>
                  <span class="chip" :class="{ success: f.isActive }">
                    {{ f.isActive ? 'Да' : 'Нет' }}
                  </span>
                </td>
                <td>{{ formatDate(f.createdAt) }}</td>
                <td class="actions">
                  <button class="btn-icon danger" title="Удалить эталонное лицо" @click="removeFace(f)">
                    <AppIcon name="delete" :size="18" />
                  </button>
                </td>
              </tr>
              <tr v-if="!faces.length && !busy">
                <td colspan="7" class="empty">Эталонных лиц нет</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.admin-card {
  padding: 20px;
  overflow: hidden;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--color-glass-border);
  padding-bottom: 12px;
}

@media (max-width: 600px) {
  .admin-card {
    padding: 14px;
    border-radius: 14px;
  }
  .tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 14px;
    margin-bottom: 12px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
  }
  .tab-btn {
    flex: 0 0 auto;
    white-space: nowrap;
    padding: 10px 14px;
    font-size: 0.92rem;
  }
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 0.88rem;
}

.tab-btn:hover {
  background: var(--card-hover-bg);
  color: var(--color-text);
}

.tab-btn.active {
  background: rgba(124, 92, 252, 0.15);
  border-color: rgba(124, 92, 252, 0.4);
  color: var(--color-text);
}

.error-msg {
  color: var(--color-error);
  font-size: 0.9rem;
  margin: 8px 0;
}

.info-msg {
  color: var(--color-success);
  font-size: 0.9rem;
  margin: 8px 0;
}

.loading {
  padding: 24px;
  text-align: center;
  color: var(--color-text-muted);
}

.metric-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  margin-bottom: 24px;
}

.presence-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.12), rgba(124, 92, 252, 0.10));
  border: 1px solid rgba(52, 211, 153, 0.35);
  margin-bottom: 16px;
}

.presence-pulse {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6);
  animation: presence-pulse 1.8s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes presence-pulse {
  0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6); }
  70% { box-shadow: 0 0 0 14px rgba(52, 211, 153, 0); }
  100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
}

.presence-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.presence-title {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}

.presence-value {
  font-size: 2rem;
  font-weight: 700;
  line-height: 1.1;
}

.presence-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.presence-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.metric-card {
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  padding: 16px;
  background: var(--input-bg);
}

.metric-icon {
  margin-bottom: 8px;
  color: var(--color-text-secondary);
}

.metric-label {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.metric-value {
  font-size: 1.6rem;
  font-weight: 700;
  margin: 4px 0;
}

.metric-sub {
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

.section-title {
  font-size: 1rem;
  margin: 16px 0 8px;
}

.server-status {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
}

.status-key {
  color: var(--color-text-muted);
}

.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  margin-right: 4px;
}

.chip.mini {
  font-size: 0.72rem;
  padding: 1px 6px;
}

.chip-count {
  opacity: 0.7;
  font-weight: 600;
}

.chip.success {
  background: rgba(52, 211, 153, 0.15);
  border-color: rgba(52, 211, 153, 0.4);
  color: #34d399;
}

.chip.error {
  background: rgba(248, 113, 113, 0.15);
  border-color: rgba(248, 113, 113, 0.4);
  color: #f87171;
}

.users-list,
.backups-list,
.audit-list,
.faces-list {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.data-table th,
.data-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--color-glass-border);
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.data-table tbody tr:hover {
  background: var(--card-hover-bg);
}

.data-table td:nth-child(5) {
  max-width: 240px;
}

.data-table td:nth-child(5) .chip {
  margin-bottom: 2px;
}

.actions {
  display: flex;
  gap: 4px;
  white-space: nowrap;
}

.btn-icon {
  background: transparent;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  padding: 6px;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
}

.btn-icon:hover:not(:disabled) {
  background: var(--card-hover-bg);
  color: var(--color-text);
}

.btn-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon.danger:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.5);
  color: #f87171;
}

.empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 24px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}

.filter-input {
  flex: 1;
  min-width: 240px;
  padding: 8px 12px;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-size: 0.88rem;
}

.filter-input:focus {
  outline: none;
  border-color: rgba(124, 92, 252, 0.5);
}

.filter-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pill {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 0.82rem;
  transition: all var(--transition-fast);
}

.pill:hover {
  background: var(--card-hover-bg);
  color: var(--color-text);
}

.pill.active {
  background: rgba(124, 92, 252, 0.15);
  border-color: rgba(124, 92, 252, 0.4);
  color: var(--color-text);
}

.bulk-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: rgba(124, 92, 252, 0.08);
  border: 1px solid rgba(124, 92, 252, 0.3);
  border-radius: var(--radius-sm);
}

.bulk-count {
  font-weight: 600;
  color: var(--color-text);
}

.btn-action.danger {
  background: rgba(248, 113, 113, 0.12);
  border-color: rgba(248, 113, 113, 0.4);
  color: #f87171;
}

.btn-action.danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.2);
}

.cell-check {
  width: 36px;
  text-align: center;
}

.cell-check input[type='checkbox'] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: rgb(124, 92, 252);
}

.cell-check input[type='checkbox']:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.row-selected {
  background: rgba(124, 92, 252, 0.06);
}

.audit-details {
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  color: var(--color-text-muted);
  word-break: break-all;
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-text);
  transition: all var(--transition-fast);
  font-size: 0.88rem;
}

.btn-action:hover:not(:disabled) {
  background: var(--card-hover-bg);
}

.btn-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
