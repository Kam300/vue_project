<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, nextTick, watch } from 'vue'
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

const search = ref('')
const activeId = ref<number | null>(null)
const stageRef = ref<HTMLDivElement | null>(null)
const cardRefs = new Map<number, HTMLElement>()
const lines = ref<Array<{ id: string; d: string; kind: 'parent' | 'spouse'; highlight: boolean }>>([])

function registerCard(id: number | undefined, el: HTMLElement | null) {
  if (!id) return
  if (el) cardRefs.set(id, el)
  else cardRefs.delete(id)
}

// --- Помощники по супругам ---
interface Pair { husband: FamilyMember | null; wife: FamilyMember | null; key: string }

/**
 * Группирует мужа и жену в пары по ролям (FATHER+MOTHER, GRANDFATHER+GRANDMOTHER).
 * Если пары нет (один из двух) — показываем одиночкой.
 */
function pairByRoles(members: FamilyMember[], maleRole: string, femaleRole: string): Pair[] {
  const males = members.filter((m) => m.role === maleRole)
  const females = members.filter((m) => m.role === femaleRole)
  const result: Pair[] = []
  const used = new Set<number>()
  males.forEach((h) => {
    // ищем супругу: та же фамилия (если maiden, лучше считать по fatherId/motherId детей)
    let wife = females.find((w) => !used.has(w.id!) && w.lastName === h.lastName)
    if (!wife) wife = females.find((w) => !used.has(w.id!))
    if (wife) used.add(wife.id!)
    result.push({ husband: h, wife: wife || null, key: `pair-${h.id}-${wife?.id || 'x'}` })
  })
  females.filter((w) => !used.has(w.id!)).forEach((w) => {
    result.push({ husband: null, wife: w, key: `pair-x-${w.id}` })
  })
  return result
}

const filteredMembers = computed<FamilyMember[]>(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return memberStore.members
  return memberStore.members.filter((m) => {
    const full = `${m.firstName} ${m.lastName} ${m.patronymic || ''} ${m.socialRoles || ''}`.toLowerCase()
    return full.includes(q)
  })
})

const generations = computed(() => {
  const m = filteredMembers.value
  return [
    {
      label: 'Бабушки и дедушки',
      icon: 'elderly',
      pairs: pairByRoles(m, 'GRANDFATHER', 'GRANDMOTHER'),
      members: m.filter((x) => ['GRANDFATHER', 'GRANDMOTHER'].includes(x.role))
    },
    {
      label: 'Родители',
      icon: 'family_restroom',
      pairs: pairByRoles(m, 'FATHER', 'MOTHER'),
      members: m.filter((x) => ['FATHER', 'MOTHER'].includes(x.role))
    },
    {
      label: 'Дяди и тёти',
      icon: 'person',
      pairs: pairByRoles(m, 'UNCLE', 'AUNT'),
      members: m.filter((x) => ['UNCLE', 'AUNT'].includes(x.role))
    },
    {
      label: 'Дети',
      icon: 'boy',
      pairs: [] as Pair[],
      members: m.filter((x) =>
        ['SON', 'DAUGHTER', 'BROTHER', 'SISTER', 'NEPHEW', 'NIECE'].includes(x.role)
      )
    },
    {
      label: 'Внуки',
      icon: 'child_friendly',
      pairs: [] as Pair[],
      members: m.filter((x) => ['GRANDSON', 'GRANDDAUGHTER'].includes(x.role))
    },
    {
      label: 'Другое',
      icon: 'groups',
      pairs: [] as Pair[],
      members: m.filter((x) => x.role === 'OTHER')
    }
  ].filter((g) => g.members.length > 0)
})

const stats = computed(() => {
  const total = memberStore.members.length
  const gens = generations.value.length
  const pairs = generations.value.reduce((sum, g) => sum + g.pairs.filter((p) => p.husband && p.wife).length, 0)
  const withPhoto = memberStore.members.filter((m) => !!m.photoUri).length
  return { total, gens, pairs, withPhoto }
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

// --- Подсвеченные связанные карточки (родственный круг) ---
const highlightSet = computed<Set<number>>(() => {
  const id = activeId.value
  const set = new Set<number>()
  if (!id) return set
  set.add(id)
  const m = memberStore.membersById.get(id)
  if (!m) return set
  // Родители
  if (m.fatherId) set.add(m.fatherId)
  if (m.motherId) set.add(m.motherId)
  // Дети
  memberStore.members.forEach((x) => {
    if (x.fatherId === id || x.motherId === id) set.add(x.id!)
  })
  // Сиблинги (общие родители)
  if (m.fatherId || m.motherId) {
    memberStore.members.forEach((x) => {
      if (x.id === id) return
      if ((m.fatherId && x.fatherId === m.fatherId) || (m.motherId && x.motherId === m.motherId)) {
        set.add(x.id!)
      }
    })
  }
  return set
})

function cardClasses(member: FamilyMember): Record<string, boolean> {
  const isActive = activeId.value === member.id
  const isRelated = highlightSet.value.has(member.id!) && !isActive
  const isDimmed = !!activeId.value && !highlightSet.value.has(member.id!)
  return { 'card-active': isActive, 'card-related': isRelated, 'card-dimmed': isDimmed }
}

function setActive(member: FamilyMember): void {
  activeId.value = activeId.value === member.id ? null : (member.id ?? null)
}

// --- SVG-линии между карточками ---
function recalcLines(): void {
  const stage = stageRef.value
  if (!stage) { lines.value = []; return }
  const stageRect = stage.getBoundingClientRect()
  const toLocal = (r: DOMRect) => ({
    left: r.left - stageRect.left,
    top: r.top - stageRect.top,
    right: r.right - stageRect.left,
    bottom: r.bottom - stageRect.top,
    cx: r.left + r.width / 2 - stageRect.left,
    cy: r.top + r.height / 2 - stageRect.top
  })

  const out: typeof lines.value = []
  const members = memberStore.members

  /**
   * Группируем детей по родителю-"якорю".
   * Якорь = пара (fatherId, motherId) или один родитель.
   * Рисуем org-chart стиле: родитель(и) → вниз до "шины", горизонтальная шина
   * по ширине детей, вертикальные отводы к каждому ребёнку.
   */
  interface SiblingGroup {
    key: string
    parentIds: number[]
    childIds: number[]
  }
  const groupsMap = new Map<string, SiblingGroup>()
  members.forEach((c) => {
    if (!c.id) return
    const f = c.fatherId || 0
    const m = c.motherId || 0
    if (!f && !m) return
    const key = `${f}-${m}`
    const g = groupsMap.get(key) ?? { key, parentIds: [f, m].filter(Boolean) as number[], childIds: [] }
    g.childIds.push(c.id)
    groupsMap.set(key, g)
  })

  groupsMap.forEach((g) => {
    const parentRects = g.parentIds
      .map((id) => cardRefs.get(id))
      .filter((el): el is HTMLElement => !!el)
      .map((el) => toLocal(el.getBoundingClientRect()))
    const childRects = g.childIds
      .map((id) => cardRefs.get(id))
      .filter((el): el is HTMLElement => !!el)
      .map((el) => toLocal(el.getBoundingClientRect()))
    if (!parentRects.length || !childRects.length) return

    // Точка "выхода" из родителей: центр по X между парой, низ карточки по Y.
    const parentTopY = Math.min(...parentRects.map((r) => r.top))
    const parentBotY = Math.max(...parentRects.map((r) => r.bottom))
    const parentX =
      parentRects.length === 2
        ? (parentRects[0].cx + parentRects[1].cx) / 2
        : parentRects[0].cx

    const childTopY = Math.min(...childRects.map((r) => r.top))
    // Если родительская пара выше детей — шина посередине между низом родителя
    // и верхом ребёнка. Иначе упираемся в минимум зазора (чтобы не ехать за кадр).
    const gap = Math.max(10, childTopY - parentBotY)
    const trunkY = parentBotY + gap / 2

    const highlight =
      activeId.value != null &&
      (g.parentIds.includes(activeId.value) || g.childIds.includes(activeId.value))

    // 1) Стебель от центра родителей вниз до шины.
    //    Если родителей двое и они на одном уровне, стебель начинается
    //    от общей "сердечной" точки между ними.
    const stemStartY =
      parentRects.length === 2
        ? (parentRects[0].cy + parentRects[1].cy) / 2
        : parentBotY
    out.push({
      id: `stem-${g.key}`,
      d: `M ${parentX},${stemStartY} V ${trunkY}`,
      kind: 'parent',
      highlight
    })

    // 2) Горизонтальная "шина": расширяем до parentX, чтобы не было разрывов
    //    когда ребёнок один и стоит не под центром родителей.
    const xs = childRects.map((r) => r.cx)
    const minXAll = Math.min(...xs, parentX)
    const maxXAll = Math.max(...xs, parentX)
    if (maxXAll - minXAll > 0.5) {
      out.push({
        id: `bus-${g.key}`,
        d: `M ${minXAll},${trunkY} H ${maxXAll}`,
        kind: 'parent',
        highlight
      })
    }

    // 3) Вертикальные отводы от шины к каждому ребёнку.
    childRects.forEach((cr, i) => {
      const x = cr.cx
      out.push({
        id: `branch-${g.key}-${g.childIds[i]}`,
        d: `M ${x},${trunkY} V ${cr.top}`,
        kind: 'parent',
        highlight:
          activeId.value != null &&
          (g.parentIds.includes(activeId.value) || activeId.value === g.childIds[i])
      })
    })

    // 4) Если родитель только один (неполная семья) — рисуем короткую
    //    горизонтальную от его низа к центру шины, чтобы выглядело аккуратнее.
    if (parentRects.length === 1 && Math.abs(parentRects[0].cx - parentX) > 0.5) {
      // уже совпадает (parentX == parentRects[0].cx), пропускаем
    }

    // Ссылки parentTopY для ts-strict
    void parentTopY
  })

  lines.value = out
}

function scheduleRecalc(): void {
  nextTick(() => requestAnimationFrame(recalcLines))
}

// Перерисовываем линии при изменении членов, шаблона, фильтра, активной карточки
watch([filteredMembers, template, activeId], scheduleRecalc)

let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  scheduleRecalc()
  window.addEventListener('resize', scheduleRecalc)
  window.addEventListener('scroll', scheduleRecalc, true)
  if (stageRef.value) {
    resizeObserver = new ResizeObserver(scheduleRecalc)
    resizeObserver.observe(stageRef.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', scheduleRecalc)
  window.removeEventListener('scroll', scheduleRecalc, true)
  resizeObserver?.disconnect()
})
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
        <!-- Верхняя панель: переключатели + поиск + статистика -->
        <div class="tree-toolbar">
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

          <div class="search-wrap">
            <AppIcon name="search" :size="16" />
            <input
              v-model="search"
              type="text"
              placeholder="Поиск по имени, фамилии..."
              class="search-input"
            />
            <button v-if="search" type="button" class="search-clear" @click="search = ''">
              <AppIcon name="close" :size="14" />
            </button>
          </div>
        </div>

        <div v-if="!memberStore.loading && memberStore.members.length" class="stats-row">
          <div class="stat">
            <AppIcon name="groups" :size="16" />
            <span class="stat-value">{{ stats.total }}</span>
            <span class="stat-label">человек</span>
          </div>
          <div class="stat">
            <AppIcon name="stairs" :size="16" />
            <span class="stat-value">{{ stats.gens }}</span>
            <span class="stat-label">поколений</span>
          </div>
          <div class="stat">
            <AppIcon name="favorite" :size="16" />
            <span class="stat-value">{{ stats.pairs }}</span>
            <span class="stat-label">пар</span>
          </div>
          <div class="stat">
            <AppIcon name="photo_camera" :size="16" />
            <span class="stat-value">{{ stats.withPhoto }}</span>
            <span class="stat-label">с фото</span>
          </div>
          <div v-if="activeId" class="stat stat-hint">
            <AppIcon name="info" :size="14" />
            <span>Клик по карточке ещё раз — сбросить подсветку</span>
          </div>
        </div>

        <div v-if="memberStore.loading" class="cards-skeleton">
          <div v-for="n in 6" :key="n" class="sk-gen-card">
            <div class="sk-bar" style="width: 55%; height: 11px"></div>
            <div class="sk-bar" style="width: 80%; height: 13px"></div>
          </div>
        </div>

        <div v-else-if="!generations.length" class="empty-state">
          <span class="empty-state-icon">
            <AppIcon name="spa" :size="32" />
          </span>
          <p v-if="search">Никого не нашли по запросу «{{ search }}».</p>
          <p v-else>Нет данных для построения древа.</p>
        </div>

        <div
          v-else
          ref="stageRef"
          class="generation-stack"
          :class="`template-${template}`"
        >
          <!-- SVG-слой связей -->
          <svg class="links-layer" aria-hidden="true">
            <defs>
              <marker id="arrow-sub" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                <circle cx="5" cy="5" r="2.2" fill="currentColor" />
              </marker>
            </defs>
            <path
              v-for="ln in lines"
              :key="ln.id"
              :d="ln.d"
              :class="['link', `link-${ln.kind}`, { 'link-highlight': ln.highlight }]"
              fill="none"
            />
          </svg>

          <section
            v-for="(group, groupIndex) in generations"
            :key="group.label"
            class="generation"
          >
            <div v-if="groupIndex > 0" class="generation-connector">
              <div class="connector-dot"></div>
            </div>

            <h2 class="generation-label">
              <span class="gen-icon">
                <AppIcon :name="group.icon" :size="20" />
              </span>
              {{ group.label }}
              <span class="chip">{{ group.members.length }}</span>
            </h2>

            <!-- Если есть пары — рисуем их как связанные карточки, иначе обычная сетка -->
            <div v-if="group.pairs.length" class="pairs">
              <div v-for="pair in group.pairs" :key="pair.key" class="pair">
                <article
                  v-if="pair.husband"
                  :ref="(el) => registerCard(pair.husband?.id, el as HTMLElement)"
                  class="tree-member-card"
                  :class="cardClasses(pair.husband)"
                  @click="setActive(pair.husband!)"
                >
                  <MemberMiniCard :member="pair.husband" :compact="template !== 'modern'" />
                  <p class="relation-line">{{ getRelationLabel(pair.husband) }}</p>
                </article>

                <div v-if="pair.husband && pair.wife" class="pair-link" aria-hidden="true">
                  <AppIcon name="favorite" :size="14" />
                </div>

                <article
                  v-if="pair.wife"
                  :ref="(el) => registerCard(pair.wife?.id, el as HTMLElement)"
                  class="tree-member-card"
                  :class="cardClasses(pair.wife)"
                  @click="setActive(pair.wife!)"
                >
                  <MemberMiniCard :member="pair.wife" :compact="template !== 'modern'" />
                  <p class="relation-line">{{ getRelationLabel(pair.wife) }}</p>
                </article>
              </div>
            </div>

            <div v-else class="cards">
              <article
                v-for="member in group.members"
                :key="member.id"
                :ref="(el) => registerCard(member.id, el as HTMLElement)"
                class="tree-member-card"
                :class="cardClasses(member)"
                @click="setActive(member)"
              >
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

/* --- Toolbar --- */
.tree-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.template-switch {
  display: flex;
  gap: 8px;
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  min-width: 220px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  color: var(--color-text-secondary);
}

.search-wrap:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px rgba(124, 92, 252, 0.18);
}

.search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--color-text);
  font-size: 0.88rem;
}

.search-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: var(--color-bg-alt);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.search-clear:hover {
  background: var(--color-accent);
  color: white;
}

/* --- Stats --- */
.stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.stat {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--color-surface);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

.stat-value {
  font-weight: 700;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  color: var(--color-text-muted);
  font-size: 0.76rem;
}

.stat-hint {
  color: var(--color-accent);
  border-color: var(--color-accent);
}

/* --- Stage: генерации + SVG --- */
.generation-stack {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.links-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.link {
  stroke: var(--color-accent);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.55;
  transition: stroke var(--transition-fast), opacity var(--transition-fast), stroke-width var(--transition-fast);
}

.link-spouse {
  stroke-dasharray: 3 3;
  stroke: var(--color-accent);
  opacity: 0.45;
}

.link-highlight {
  stroke: var(--color-accent);
  stroke-width: 2.6;
  opacity: 1;
  filter: drop-shadow(0 0 4px rgba(124, 92, 252, 0.55));
}

/* --- Generation connector (центральная точка между поколениями) --- */
.generation-connector {
  display: flex;
  justify-content: center;
  padding: 6px 0 2px;
  position: relative;
  z-index: 1;
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
  position: relative;
  z-index: 1;
}

.gen-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* --- Pairs (супружеские пары) --- */
.pairs {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  position: relative;
  z-index: 1;
}

.pair {
  display: flex;
  align-items: stretch;
  gap: 8px;
  padding: 8px;
  border-radius: 14px;
  border: 1px dashed transparent;
  transition: border-color var(--transition-fast), background var(--transition-fast);
  flex: 1 1 440px;
  min-width: 260px;
}

.pair:hover {
  border-color: var(--color-glass-border);
  background: var(--color-surface);
}

.pair .tree-member-card {
  flex: 1;
  min-width: 0;
}

.pair-link {
  align-self: center;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ec4899, #8b5cf6);
  color: white;
  box-shadow: 0 2px 10px rgba(236, 72, 153, 0.35);
  flex-shrink: 0;
}

/* --- Cards --- */
.cards {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  position: relative;
  z-index: 1;
}

.tree-member-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  border-radius: 16px;
  transition: transform var(--transition-fast), opacity var(--transition-fast), box-shadow var(--transition-fast);
}

.tree-member-card.card-active {
  transform: translateY(-2px);
  box-shadow: 0 0 0 2px var(--color-accent), 0 10px 30px rgba(124, 92, 252, 0.25);
}

.tree-member-card.card-related {
  box-shadow: 0 0 0 1px var(--color-accent);
}

.tree-member-card.card-dimmed {
  opacity: 0.35;
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

.template-print .generation-connector,
.template-print .links-layer {
  display: none;
}

/* ===== Mobile ===== */
@media (max-width: 768px) {
  .tree-shell {
    padding: 16px 12px;
  }

  .tree-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .template-switch {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }

  .template-switch .btn-action {
    justify-content: center;
    padding: 8px 4px;
    font-size: 0.82rem;
    min-width: 0;
  }

  .search-wrap {
    min-width: 0;
  }

  .cards {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }

  .pair {
    flex-direction: column;
    flex: 1 1 100%;
  }

  .pair-link {
    transform: rotate(90deg);
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

  /* На мобиле линии часто мусорят — скрываем */
  .links-layer { display: none; }
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
