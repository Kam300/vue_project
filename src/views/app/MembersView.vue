<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMemberStore } from '@/stores/memberStore'
import PageHeader from '@/components/shared/PageHeader.vue'
import { ROLE_LABELS } from '@/types/models'
import { toTelegramLink, toTelLink, toWhatsAppLink } from '@/utils/phone'

const memberStore = useMemberStore()
const router = useRouter()
const search = ref('')
const deletingId = ref<number | null>(null)

const filteredMembers = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return memberStore.members
  return memberStore.members.filter((member) => {
    const values = [
      member.firstName,
      member.lastName,
      member.patronymic || '',
      ROLE_LABELS[member.role]
    ]
    return values.join(' ').toLowerCase().includes(query)
  })
})

onMounted(() => {
  if (!memberStore.members.length) {
    memberStore.refresh()
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

function openContact(url: string): void {
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        title="Список семьи"
        subtitle="Управление членами семьи, поиск и быстрые контакты"
      />

      <article class="app-card members-card">
        <div class="members-toolbar">
          <input v-model="search" type="text" placeholder="Поиск по имени, фамилии, роли..." />
          <div class="btn-row">
            <button class="btn-action primary" @click="router.push('/app/members/new')">
              Добавить члена семьи
            </button>
          </div>
        </div>

        <div v-if="!filteredMembers.length" class="empty-state">
          В списке пока нет данных.
        </div>

        <div v-else class="table-wrap">
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
                  <strong>{{ member.firstName }} {{ member.lastName }}</strong>
                  <div class="status-line" v-if="member.patronymic">{{ member.patronymic }}</div>
                </td>
                <td>{{ ROLE_LABELS[member.role] }}</td>
                <td>{{ member.birthDate }}</td>
                <td>
                  <div class="btn-row" v-if="member.phoneNumber">
                    <button class="btn-action" @click="openContact(toTelegramLink(member.phoneNumber))">
                      Telegram
                    </button>
                    <button class="btn-action" @click="openContact(toWhatsAppLink(member.phoneNumber))">
                      WhatsApp
                    </button>
                    <a class="btn-action" :href="toTelLink(member.phoneNumber)">Позвонить</a>
                  </div>
                  <span v-else class="status-line">Телефон не указан</span>
                </td>
                <td>
                  <div class="btn-row">
                    <button class="btn-action" @click="editMember(member.id)">Профиль</button>
                    <button
                      class="btn-action danger"
                      @click="removeMember(member.id)"
                      :disabled="deletingId === member.id"
                    >
                      {{ deletingId === member.id ? 'Удаление...' : 'Удалить' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.members-card {
  padding: 16px;
}

.members-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  margin-bottom: 14px;
}

.members-toolbar input {
  flex: 1;
  min-width: 260px;
  max-width: 520px;
  border: 1px solid var(--color-glass-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  color: var(--color-text);
  padding: 10px 12px;
}
</style>
