<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMemberStore } from '@/stores/memberStore'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import { ROLE_LABELS } from '@/types/models'
import { toTelegramLink, toTelLink, toWhatsAppLink } from '@/utils/phone'
import { calcAge } from '@/utils/date'

const memberStore = useMemberStore()
const router = useRouter()
const search = ref('')
const deletingId = ref<number | null>(null)
const viewMode = ref<'table' | 'cards'>('table')

const filteredMembers = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return memberStore.members
  return memberStore.members.filter((member) => {
    const values = [
      member.firstName,
      member.lastName,
      member.patronymic || '',
      member.socialRoles || '',
      ROLE_LABELS[member.role]
    ]
    return values.join(' ').toLowerCase().includes(query)
  })
})

onMounted(() => {
  if (!memberStore.members.length) {
    memberStore.refresh()
  }
  if (window.innerWidth <= 768) {
    viewMode.value = 'cards'
  }
})

function editMember(memberId: number | undefined): void {
  if (!memberId) return
  router.push(`/app/members/${memberId}`)
}

async function removeMember(memberId: number | undefined): Promise<void> {
  if (!memberId) return
  const confirmed = window.confirm('Удалить выбранного члена семьи?')
  if (!confirmed) return

  deletingId.value = memberId
  try {
    await memberStore.removeMember(memberId)
  } finally {
    deletingId.value = null
  }
}

function formatBirthDate(date: string | undefined): string {
  if (!date) return '—'
  const age = calcAge(date)
  return age ? `${date} ${age}` : date
}

function openContact(url: string): void {
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="groups"
        title="Список семьи"
        subtitle="Управление членами семьи, поиск и быстрые контакты"
      />

      <article class="app-card members-card">
        <div class="members-toolbar">
          <div class="search-wrap">
            <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input v-model="search" type="text" placeholder="Поиск по имени, фамилии, роли..." />
          </div>
          <div class="toolbar-actions">
            <div class="view-toggle">
              <button class="btn-icon-sm" :class="{ active: viewMode === 'table' }" @click="viewMode = 'table'" title="Таблица">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
              </button>
              <button class="btn-icon-sm" :class="{ active: viewMode === 'cards' }" @click="viewMode = 'cards'" title="Карточки">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
              </button>
            </div>
            <button class="btn-action primary members-add-btn" @click="router.push('/app/members/new')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Добавить
            </button>
          </div>
        </div>

        <!-- Skeleton loading: table -->
        <div v-if="memberStore.loading" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Человек</th><th>Роль</th><th>Дата рождения</th><th>Контакты</th><th>Действия</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="n in 5" :key="n" class="skeleton-row">
                <td><div class="sk-cell" style="width: 60%"></div></td>
                <td><div class="sk-cell" style="width: 50%"></div></td>
                <td><div class="sk-cell" style="width: 70%"></div></td>
                <td><div class="sk-cell" style="width: 40%"></div></td>
                <td><div class="sk-cell" style="width: 55%"></div></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Empty state -->
        <div v-else-if="!filteredMembers.length" class="empty-state">
          <span class="empty-state-icon">
            <AppIcon name="family_restroom" :size="32" />
          </span>
          <p>В списке пока нет данных.</p>
          <button class="btn-action primary" style="margin-top: 12px" @click="router.push('/app/members/new')">
            Добавить первого члена семьи
          </button>
        </div>

        <!-- Table view -->
        <div v-else-if="viewMode === 'table'" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Человек</th>
                <th>Роль</th>
                <th>Дата рождения</th>
                <th>Контакты</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="member in filteredMembers" :key="member.id">
                <td>
                  <div class="member-name-cell">
                    <div class="mini-avatar-cell">
                      <img v-if="member.photoUri" :src="member.photoUri" class="mini-avatar" />
                      <span v-else class="mini-avatar placeholder">
                        <AppIcon name="person" :size="18" />
                      </span>
                    </div>
                    <div>
                      <strong>{{ member.firstName }} {{ member.lastName }}</strong>
                      <div class="status-line" v-if="member.patronymic">{{ member.patronymic }}</div>
                      <div class="status-line" v-if="member.socialRoles">{{ member.socialRoles }}</div>
                    </div>
                  </div>
                </td>
                <td><span class="chip">{{ ROLE_LABELS[member.role] }}</span></td>
                <td>{{ formatBirthDate(member.birthDate) }}</td>
                <td>
                  <div class="btn-row" v-if="member.phoneNumber">
                    <button class="btn-action" @click="openContact(toTelegramLink(member.phoneNumber))" title="Telegram">
                      <AppIcon name="send" :size="16" />
                    </button>
                    <button class="btn-action" @click="openContact(toWhatsAppLink(member.phoneNumber))" title="WhatsApp">
                      <AppIcon name="chat" :size="16" />
                    </button>
                    <a class="btn-action" :href="toTelLink(member.phoneNumber)" title="Позвонить">
                      <AppIcon name="call" :size="16" />
                    </a>
                  </div>
                  <span v-else class="status-line">—</span>
                </td>
                <td>
                  <div class="btn-row">
                    <button class="btn-action" @click="editMember(member.id)">Профиль</button>
                    <button
                      class="btn-action danger"
                      @click="removeMember(member.id)"
                      :disabled="deletingId === member.id"
                    >
                      <AppIcon :name="deletingId === member.id ? 'hourglass_top' : 'close'" :size="16" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Card view / skeleton -->
        <div v-else-if="memberStore.loading" class="cards-grid">
          <div v-for="n in 6" :key="n" class="sk-card">
            <div class="sk-avatar"></div>
            <div class="sk-lines">
              <div class="sk-cell" style="width: 65%; height: 14px"></div>
              <div class="sk-cell" style="width: 40%; height: 11px"></div>
            </div>
          </div>
        </div>

        <!-- Card view -->
        <div v-else class="cards-grid">
          <article
            v-for="member in filteredMembers"
            :key="member.id"
            class="member-card-item"
            @click="editMember(member.id)"
          >
            <div class="card-avatar-wrap">
              <img v-if="member.photoUri" :src="member.photoUri" class="card-avatar" />
              <div v-else class="card-avatar placeholder">
                <AppIcon name="person" :size="20" />
              </div>
            </div>
            <div class="card-info">
              <h3>{{ member.firstName }} {{ member.lastName }}</h3>
              <span class="chip">{{ ROLE_LABELS[member.role] }}</span>
              <small v-if="member.socialRoles">{{ member.socialRoles }}</small>
              <small v-if="member.birthDate">{{ formatBirthDate(member.birthDate) }}</small>
            </div>
            <div class="card-actions" @click.stop>
              <button v-if="member.phoneNumber" class="btn-action" @click="openContact(toTelegramLink(member.phoneNumber))">
                <AppIcon name="send" :size="16" />
              </button>
              <button class="btn-action danger" @click="removeMember(member.id)" :disabled="deletingId === member.id">
                <AppIcon :name="deletingId === member.id ? 'hourglass_top' : 'close'" :size="16" />
              </button>
            </div>
          </article>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.members-card {
  padding: 20px;
  overflow: hidden;
}

.members-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.search-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  max-width: 480px;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 18px;
  height: 18px;
  color: var(--color-text-muted);
  pointer-events: none;
}

.search-wrap input {
  width: 100%;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  color: var(--color-text);
  padding: 10px 14px 10px 40px;
  font-size: 0.92rem;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.search-wrap input:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(124, 92, 252, 0.18);
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.view-toggle {
  display: flex;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.btn-icon-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-icon-sm svg {
  width: 16px;
  height: 16px;
}

.btn-icon-sm:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.btn-icon-sm.active {
  background: rgba(124, 92, 252, 0.15);
  color: var(--color-accent-light);
}

/* Mini avatar in table */
.member-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mini-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--color-glass-border);
}

.mini-avatar.placeholder {
  display: grid;
  place-items: center;
  background: var(--color-surface);
  font-size: 1rem;
}

/* Cards grid */
.cards-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  align-items: start;
}

.member-card-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  cursor: pointer;
  transition: all var(--transition-normal);
}

.member-card-item:hover {
  border-color: var(--card-hover-border);
  background: var(--card-hover-bg);
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.card-avatar-wrap {
  flex-shrink: 0;
}

.card-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  object-fit: cover;
  border: 1px solid var(--color-glass-border);
}

.card-avatar.placeholder {
  display: grid;
  place-items: center;
  background: var(--color-surface);
  font-size: 1.3rem;
}

.card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-info h3 {
  font-size: 0.95rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-info small {
  color: var(--color-text-muted);
  font-size: 0.78rem;
}

.card-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  align-items: center;
}

.card-actions .btn-action,
.card-actions .btn-action.danger {
  flex: 0 0 auto;
  min-width: 42px;
  padding: 10px 12px;
}

@media (max-width: 640px) {
  .members-card {
    padding: 16px;
  }

  .members-toolbar {
    align-items: stretch;
  }

  .search-wrap {
    min-width: 0;
    max-width: none;
  }

  .toolbar-actions {
    width: 100%;
    justify-content: space-between;
  }

  .members-add-btn {
    flex: 1 1 auto;
  }

  .member-card-item {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: start;
  }

  .card-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}

@media (max-width: 480px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }

  .members-card {
    padding: 14px;
  }

  .view-toggle {
    display: none;
  }

  .toolbar-actions {
    gap: 8px;
  }

  .members-add-btn {
    min-width: 0;
  }

  .member-card-item {
    gap: 12px;
    padding: 12px;
  }

  .card-avatar {
    width: 44px;
    height: 44px;
  }

  .card-info h3 {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    line-height: 1.25;
  }
}

/* ===== Skeleton ===== */
@keyframes shimmer {
  0% { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

.sk-cell {
  height: 13px;
  border-radius: 6px;
  background: linear-gradient(
    90deg,
    var(--color-surface) 25%,
    var(--color-surface-hover) 50%,
    var(--color-surface) 75%
  );
  background-size: 800px 100%;
  animation: shimmer 1.4s infinite linear;
}

.skeleton-row td {
  padding-top: 16px;
  padding-bottom: 16px;
}

.sk-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
}

.sk-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  flex-shrink: 0;
  background: linear-gradient(
    90deg,
    var(--color-surface) 25%,
    var(--color-surface-hover) 50%,
    var(--color-surface) 75%
  );
  background-size: 800px 100%;
  animation: shimmer 1.4s infinite linear;
}

.sk-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
