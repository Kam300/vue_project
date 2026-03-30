<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useMemberStore } from '@/stores/memberStore'
import { useAppStore } from '@/stores/appStore'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
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
      icon: 'elderly',
      members: members.filter((member) => ['GRANDFATHER', 'GRANDMOTHER'].includes(member.role))
    },
    {
      label: 'Родители',
      icon: 'family_restroom',
      members: members.filter((member) => ['FATHER', 'MOTHER'].includes(member.role))
    },
    {
      label: 'Дяди и тети',
      icon: 'person',
      members: members.filter((member) => ['UNCLE', 'AUNT'].includes(member.role))
    },
    {
      label: 'Дети',
      icon: 'boy',
      members: members.filter((member) =>
        ['SON', 'DAUGHTER', 'BROTHER', 'SISTER', 'NEPHEW', 'NIECE'].includes(member.role)
      )
    },
    {
      label: 'Внуки',
      icon: 'child_friendly',
      members: members.filter((member) => ['GRANDSON', 'GRANDDAUGHTER'].includes(member.role))
    },
    {
      label: 'Другое',
      icon: 'groups',
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
    .join(' · ')
}

async function setTemplate(next: 'modern' | 'classic' | 'print'): Promise<void> {
  await appStore.updateSettings({ treeTemplate: next })
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="account_tree"
        title="Семейное древо"
        subtitle="Три режима отображения: modern, classic и print"
      />

      <article class="app-card tree-shell">
        <div class="template-switch">
          <button
            v-for="t in (['modern', 'classic', 'print'] as const)"
            :key="t"
            class="btn-action"
            :class="{ primary: template === t }"
            @click="setTemplate(t)"
          >
            {{ t === 'modern' ? 'Modern' : t === 'classic' ? 'Classic' : 'Print' }}
          </button>
        </div>

        <div v-if="memberStore.loading" class="cards-skeleton">
          <div v-for="n in 6" :key="n" class="sk-gen-card">
            <div class="sk-bar" style="width: 55%; height: 11px"></div>
            <div class="sk-bar" style="width: 80%; height: 13px"></div>
          </div>
        </div>

        <div v-else-if="!groupedGenerations.length" class="empty-state">
          <span class="empty-state-icon">
            <AppIcon name="spa" :size="32" />
          </span>
          <p>Нет данных для построения древа.</p>
        </div>

        <div v-else class="generation-stack" :class="`template-${template}`">
          <section
            v-for="(group, groupIndex) in groupedGenerations"
            :key="group.label"
            class="generation"
          >
            <!-- Connector between generations -->
            <div v-if="groupIndex > 0" class="generation-connector">
              <div class="connector-line"></div>
              <div class="connector-dot"></div>
              <div class="connector-line"></div>
            </div>

            <h2 class="generation-label">
              <span class="gen-icon">
                <AppIcon :name="group.icon" :size="20" />
              </span>
              {{ group.label }}
              <span class="chip">{{ group.members.length }}</span>
            </h2>
            <div class="cards">
              <article v-for="member in group.members" :key="member.id" class="tree-member-card">
                <MemberMiniCard :member="member" :compact="template !== 'modern'" />
                <p class="relation-line">{{ getRelationLabel(member) }}</p>
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
  padding: 20px;
}

.template-switch {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.generation-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Generation connector */
.generation-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4px 0;
}

.connector-line {
  width: 2px;
  height: 16px;
  background: linear-gradient(180deg, var(--color-accent), rgba(124, 92, 252, 0.2));
}

.connector-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
  box-shadow: 0 0 8px rgba(124, 92, 252, 0.4);
}

.generation-label {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 1.05rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.gen-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.cards {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.tree-member-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.relation-line {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  padding-left: 12px;
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
  padding: 14px;
}

.template-print .generation-connector {
  display: none;
}

/* ===== Mobile ===== */
@media (max-width: 768px) {
  .tree-shell {
    padding: 16px 12px;
  }

  /* Кнопки шаблона — равная ширина, не обрезаются */
  .template-switch {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    margin-bottom: 16px;
  }

  .template-switch .btn-action {
    justify-content: center;
    padding: 8px 4px;
    font-size: 0.82rem;
    min-width: 0;
  }

  .cards {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }

  .generation-label {
    font-size: 0.92rem;
  }

  .template-classic .cards {
    grid-template-columns: 1fr;
  }

  .template-print .cards {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }
}

@media (max-width: 480px) {
  .cards {
    grid-template-columns: 1fr;
  }

  .cards-skeleton {
    grid-template-columns: 1fr;
  }
}

/* ===== Skeleton ===== */
@keyframes shimmer {
  0% { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

.cards-skeleton {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.sk-gen-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
}

.sk-bar {
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
</style>
