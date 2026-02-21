<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useMemberStore } from '@/stores/memberStore'
import { useAppStore } from '@/stores/appStore'
import PageHeader from '@/components/shared/PageHeader.vue'
import MemberMiniCard from '@/components/shared/MemberMiniCard.vue'
import type { FamilyMember } from '@/types/models'

const memberStore = useMemberStore()
const appStore = useAppStore()

onMounted(() => {
  if (!memberStore.members.length) {
    memberStore.refresh()
  }
})

const template = computed(() => appStore.settings.treeTemplate)

const groupedGenerations = computed(() => {
  const members = memberStore.members
  return [
    {
      label: 'Бабушки и дедушки',
      members: members.filter((member) => ['GRANDFATHER', 'GRANDMOTHER'].includes(member.role))
    },
    {
      label: 'Родители',
      members: members.filter((member) => ['FATHER', 'MOTHER'].includes(member.role))
    },
    {
      label: 'Дяди и тети',
      members: members.filter((member) => ['UNCLE', 'AUNT'].includes(member.role))
    },
    {
      label: 'Дети',
      members: members.filter((member) =>
        ['SON', 'DAUGHTER', 'BROTHER', 'SISTER', 'NEPHEW', 'NIECE'].includes(member.role)
      )
    },
    {
      label: 'Внуки',
      members: members.filter((member) => ['GRANDSON', 'GRANDDAUGHTER'].includes(member.role))
    },
    {
      label: 'Другое',
      members: members.filter((member) => member.role === 'OTHER')
    }
  ].filter((group) => group.members.length > 0)
})

function getRelationLabel(member: FamilyMember): string {
  const father = member.fatherId ? memberStore.membersById.get(member.fatherId) : null
  const mother = member.motherId ? memberStore.membersById.get(member.motherId) : null
  if (!father && !mother) return 'Связи не указаны'
  return [
    father ? `Отец: ${father.firstName} ${father.lastName}` : '',
    mother ? `Мать: ${mother.firstName} ${mother.lastName}` : ''
  ]
    .filter(Boolean)
    .join(' | ')
}

async function setTemplate(next: 'modern' | 'classic' | 'print'): Promise<void> {
  await appStore.updateSettings({ treeTemplate: next })
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        title="Семейное древо"
        subtitle="Три режима отображения: modern, classic и print"
      />

      <article class="app-card tree-shell">
        <div class="btn-row">
          <button
            class="btn-action"
            :class="{ primary: template === 'modern' }"
            @click="setTemplate('modern')"
          >
            Modern
          </button>
          <button
            class="btn-action"
            :class="{ primary: template === 'classic' }"
            @click="setTemplate('classic')"
          >
            Classic
          </button>
          <button
            class="btn-action"
            :class="{ primary: template === 'print' }"
            @click="setTemplate('print')"
          >
            Print
          </button>
        </div>

        <div v-if="!groupedGenerations.length" class="empty-state">
          Нет данных для построения древа.
        </div>

        <div v-else class="generation-stack" :class="`template-${template}`">
          <section v-for="group in groupedGenerations" :key="group.label" class="generation">
            <h2>{{ group.label }}</h2>
            <div class="cards">
              <article v-for="member in group.members" :key="member.id" class="tree-member-card">
                <MemberMiniCard :member="member" :compact="template !== 'modern'" />
                <p class="status-line">{{ getRelationLabel(member) }}</p>
              </article>
            </div>
          </section>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.tree-shell {
  padding: 16px;
}

.generation-stack {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.generation h2 {
  margin-bottom: 10px;
  font-size: 1rem;
  color: var(--color-text-secondary);
}

.cards {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.tree-member-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.template-classic .cards {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.template-print .cards {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}

.template-print .generation {
  border: 1px dashed var(--color-glass-border);
  border-radius: 12px;
  padding: 10px;
}
</style>
