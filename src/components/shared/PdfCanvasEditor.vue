<script setup lang="ts">
/**
 * Визуальный редактор (draw.io-стиль) для ручной компоновки PDF.
 * Работает в координатах PDF-точек (pt). Масштаб — только для отображения.
 *
 * props.modelValue = { nodes, edges, defaults }
 */
import { computed, reactive, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'
import type { FamilyMember } from '@/types/models'

interface NodeStyle {
  bg_color?: string
  border_color?: string
  text_color?: string
  role_color?: string
  accent_color?: string
  radius?: number
  border_width?: number
  font_scale?: number
  font_family?: 'sans' | 'serif' | 'mono'
  photo_shape?: 'circle' | 'rounded' | 'square'
  show_photo?: boolean
  show_dates?: boolean
  show_patronymic?: boolean
  show_role?: boolean
  shadow?: boolean
}

interface EdgeStyle {
  kind?: 'orthogonal' | 'curve' | 'straight'
  color?: string
  width?: number
  marker?: boolean
}

export interface CanvasNode {
  id: string
  memberId?: string
  x: number
  y: number
  width: number
  height: number
  style?: NodeStyle
}

export interface CanvasEdge {
  from: string
  to: string
  from_side?: 'top' | 'bottom' | 'left' | 'right'
  to_side?: 'top' | 'bottom' | 'left' | 'right'
  style?: EdgeStyle
}

export interface CanvasState {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  defaults?: NodeStyle
}

interface Props {
  modelValue: CanvasState
  members: FamilyMember[]
  pageWidth: number
  pageHeight: number
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'update:modelValue', v: CanvasState): void }>()

const DEFAULT_NODE: Omit<CanvasNode, 'id' | 'memberId'> = {
  x: 40, y: 40, width: 140, height: 170,
  style: {}
}

const state = reactive<CanvasState>({
  nodes: props.modelValue?.nodes ? props.modelValue.nodes.map(n => ({ ...n, style: { ...n.style } })) : [],
  edges: props.modelValue?.edges ? props.modelValue.edges.map(e => ({ ...e, style: { ...e.style } })) : [],
  defaults: { ...(props.modelValue?.defaults || {}) }
})

watch(state, () => emit('update:modelValue', JSON.parse(JSON.stringify(state))), { deep: true })

/* ---------- Viewport / zoom ---------- */
const viewport = ref<HTMLDivElement | null>(null)
const scale = ref(1)
const fitScale = computed(() => {
  if (!viewport.value) return 1
  const rect = viewport.value.getBoundingClientRect()
  const sx = (rect.width - 24) / props.pageWidth
  const sy = (rect.height - 24) / props.pageHeight
  return Math.max(0.2, Math.min(sx, sy))
})

function zoom(delta: number, anchorX?: number, anchorY?: number): void {
  const next = Math.max(0.25, Math.min(3, scale.value + delta))
  scale.value = Number(next.toFixed(3))
}

function fitToScreen(): void {
  scale.value = Number(fitScale.value.toFixed(3))
}

/* ---------- Helpers ---------- */
function uid(): string {
  return 'n' + Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-3)
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v))
}

function toPt(screenDelta: number): number {
  return screenDelta / scale.value
}

/* ---------- Selection ---------- */
const selectedNodeId = ref<string | null>(null)
const selectedEdgeIdx = ref<number | null>(null)
const selectedNode = computed(() => state.nodes.find(n => n.id === selectedNodeId.value) || null)
const selectedEdge = computed(() => selectedEdgeIdx.value !== null ? state.edges[selectedEdgeIdx.value] : null)

function selectNode(id: string | null, e?: MouseEvent): void {
  if (e) e.stopPropagation()
  selectedNodeId.value = id
  selectedEdgeIdx.value = null
  // НЕ сбрасываем pendingEdgeFrom — это ломает клик-по-клик соединение.
}

function selectEdge(i: number, e: MouseEvent): void {
  e.stopPropagation()
  selectedEdgeIdx.value = i
  selectedNodeId.value = null
}

/* ---------- Drag nodes ---------- */
interface DragState {
  id: string
  startX: number
  startY: number
  origX: number
  origY: number
  mode: 'move' | 'resize-br'
  origW?: number
  origH?: number
}
const dragging = ref<DragState | null>(null)

function startNodeDrag(n: CanvasNode, e: PointerEvent, mode: 'move' | 'resize-br' = 'move'): void {
  if ((e.target as HTMLElement).closest('[data-no-drag]')) return
  e.stopPropagation()
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  selectNode(n.id)
  dragging.value = {
    id: n.id,
    startX: e.clientX, startY: e.clientY,
    origX: n.x, origY: n.y,
    mode,
    origW: n.width, origH: n.height,
  }
}

function onPointerMove(e: PointerEvent): void {
  if (!dragging.value) return
  const node = state.nodes.find(n => n.id === dragging.value!.id)
  if (!node) return
  const dx = toPt(e.clientX - dragging.value.startX)
  const dy = toPt(e.clientY - dragging.value.startY)
  if (dragging.value.mode === 'move') {
    node.x = clamp(dragging.value.origX + dx, 0, props.pageWidth - node.width)
    node.y = clamp(dragging.value.origY + dy, 0, props.pageHeight - node.height)
  } else if (dragging.value.mode === 'resize-br') {
    node.width = clamp((dragging.value.origW ?? 140) + dx, 80, props.pageWidth - node.x)
    node.height = clamp((dragging.value.origH ?? 170) + dy, 60, props.pageHeight - node.y)
  }
}

function onPointerUp(e: PointerEvent): void {
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch {}
  dragging.value = null
}

/* ---------- Add / remove ---------- */
function addMember(m: FamilyMember): void {
  if (m.id == null) return
  const memberId = String(m.id)
  const existing = state.nodes.filter(n => n.memberId === memberId).length
  const n: CanvasNode = {
    id: uid(),
    memberId,
    x: 60 + existing * 18,
    y: 60 + existing * 18,
    width: DEFAULT_NODE.width,
    height: DEFAULT_NODE.height,
    style: {}
  }
  state.nodes.push(n)
  selectNode(n.id)
}

function duplicateNode(): void {
  if (!selectedNode.value) return
  const n = selectedNode.value
  const copy: CanvasNode = {
    ...n, id: uid(),
    x: Math.min(props.pageWidth - n.width, n.x + 20),
    y: Math.min(props.pageHeight - n.height, n.y + 20),
    style: { ...(n.style || {}) },
  }
  state.nodes.push(copy)
  selectNode(copy.id)
}

function deleteSelected(): void {
  if (selectedNode.value) {
    const id = selectedNode.value.id
    state.nodes = state.nodes.filter(n => n.id !== id)
    state.edges = state.edges.filter(e => e.from !== id && e.to !== id)
    selectNode(null)
  } else if (selectedEdge.value && selectedEdgeIdx.value !== null) {
    state.edges.splice(selectedEdgeIdx.value, 1)
    selectedEdgeIdx.value = null
  }
}

function clearAll(): void {
  if (!confirm('Очистить холст?')) return
  state.nodes = []
  state.edges = []
  selectNode(null)
}

/* ---------- Edges ---------- */
const pendingEdgeFrom = ref<string | null>(null)

/** Drag-коннектор: начинаем тянуть от конкретной стороны. */
interface LiveEdge {
  fromId: string
  fromSide: 'top' | 'bottom' | 'left' | 'right'
  startX: number
  startY: number
  x: number
  y: number
}
const liveEdge = ref<LiveEdge | null>(null)

function startEdge(): void {
  if (!selectedNode.value) return
  pendingEdgeFrom.value = selectedNode.value.id
}

function cancelPendingEdge(): void {
  pendingEdgeFrom.value = null
  liveEdge.value = null
}

function completeEdge(target: CanvasNode, side?: 'top' | 'bottom' | 'left' | 'right'): void {
  const fromId = liveEdge.value?.fromId || pendingEdgeFrom.value
  if (!fromId || fromId === target.id) {
    cancelPendingEdge()
    return
  }
  const fromSide = liveEdge.value?.fromSide
  const exists = state.edges.some(e => e.from === fromId && e.to === target.id)
  if (!exists) {
    const edge: CanvasEdge = { from: fromId, to: target.id, style: {} }
    if (fromSide) edge.from_side = fromSide
    if (side) edge.to_side = side
    state.edges.push(edge)
  }
  cancelPendingEdge()
}

/** Начать протаскивание связи от хендла карточки. */
function startEdgeDrag(n: CanvasNode, side: 'top' | 'bottom' | 'left' | 'right', e: PointerEvent): void {
  e.stopPropagation()
  e.preventDefault()
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  selectNode(n.id)
  const [sx, sy] = anchor(n, side)
  liveEdge.value = {
    fromId: n.id,
    fromSide: side,
    startX: sx,
    startY: sy,
    x: sx,
    y: sy
  }
}

function onEdgeDragMove(e: PointerEvent): void {
  if (!liveEdge.value) return
  const page = viewport.value?.querySelector('.ce-page') as HTMLElement | null
  if (!page) return
  const rect = page.getBoundingClientRect()
  liveEdge.value.x = (e.clientX - rect.left) / scale.value
  liveEdge.value.y = (e.clientY - rect.top) / scale.value
}

function onEdgeDragEnd(e: PointerEvent): void {
  const le = liveEdge.value
  if (!le) return
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch {}
  const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
  const nodeEl = el?.closest('[data-node-id]') as HTMLElement | null
  const targetId = nodeEl?.dataset.nodeId
  const target = targetId ? state.nodes.find(n => n.id === targetId) : null
  if (target && target.id !== le.fromId) {
    const rect = nodeEl!.getBoundingClientRect()
    const relX = (e.clientX - rect.left) / rect.width
    const relY = (e.clientY - rect.top) / rect.height
    const distances = [
      { s: 'top' as const, d: relY },
      { s: 'bottom' as const, d: 1 - relY },
      { s: 'left' as const, d: relX },
      { s: 'right' as const, d: 1 - relX },
    ].sort((a, b) => a.d - b.d)
    completeEdge(target, distances[0].s)
  } else {
    cancelPendingEdge()
  }
}

/** SVG-путь для live-линии (рисуется пока тянем). */
const liveEdgePath = computed(() => {
  const le = liveEdge.value
  if (!le) return ''
  const { startX: x1, startY: y1, x: x2, y: y2 } = le
  const horizontal = le.fromSide === 'left' || le.fromSide === 'right'
  if (horizontal) {
    const cx = (x1 + x2) / 2
    return `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
  }
  const cy = (y1 + y2) / 2
  return `M ${x1} ${y1} C ${x1} ${cy}, ${x2} ${cy}, ${x2} ${y2}`
})

/* ---------- Member helpers ---------- */
const membersById = computed(() => {
  const map: Record<string, FamilyMember> = {}
  for (const m of props.members) if (m.id != null) map[String(m.id)] = m
  return map
})

function memberOf(n: CanvasNode): FamilyMember | null {
  return n.memberId ? membersById.value[n.memberId] || null : null
}

function memberName(n: CanvasNode): string {
  const m = memberOf(n)
  if (!m) return '—'
  return [m.lastName, m.firstName].filter(Boolean).join(' ') || m.firstName || 'Без имени'
}

const usedIds = computed(() => new Set(
  state.nodes.map(n => n.memberId).filter((v): v is string => Boolean(v))
))

/* ---------- Edges rendering ---------- */
interface EdgeLine {
  index: number
  kind: 'orthogonal' | 'curve' | 'straight'
  color: string
  width: number
  path: string
  dotX: number
  dotY: number
}

function bestSides(a: CanvasNode, b: CanvasNode): [string, string] {
  const ax = a.x + a.width / 2, ay = a.y + a.height / 2
  const bx = b.x + b.width / 2, by = b.y + b.height / 2
  const dx = bx - ax, dy = by - ay
  if (Math.abs(dy) >= Math.abs(dx)) {
    return dy > 0 ? ['bottom', 'top'] : ['top', 'bottom']
  }
  return dx > 0 ? ['right', 'left'] : ['left', 'right']
}

function anchor(n: CanvasNode, side: string): [number, number] {
  const cx = n.x + n.width / 2
  if (side === 'top') return [cx, n.y]
  if (side === 'bottom') return [cx, n.y + n.height]
  if (side === 'left') return [n.x, n.y + n.height / 2]
  return [n.x + n.width, n.y + n.height / 2]
}

const edgeLines = computed<EdgeLine[]>(() => {
  const byId: Record<string, CanvasNode> = {}
  for (const n of state.nodes) byId[n.id] = n
  return state.edges.map((e, i) => {
    const a = byId[e.from], b = byId[e.to]
    if (!a || !b) return null
    const st = { ...(state.defaults || {}), ...(e.style || {}) } as EdgeStyle
    const kind = (st.kind || 'orthogonal') as 'orthogonal' | 'curve' | 'straight'
    const [defSa, defSb] = bestSides(a, b)
    const sa = e.from_side || defSa
    const sb = e.to_side || defSb
    const [x1, y1] = anchor(a, sa)
    const [x2, y2] = anchor(b, sb)
    let path = ''
    if (kind === 'straight') {
      path = `M ${x1} ${y1} L ${x2} ${y2}`
    } else if (kind === 'curve') {
      if (sa === 'top' || sa === 'bottom') {
        const cy = (y1 + y2) / 2
        path = `M ${x1} ${y1} C ${x1} ${cy}, ${x2} ${cy}, ${x2} ${y2}`
      } else {
        const cx = (x1 + x2) / 2
        path = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
      }
    } else {
      if ((sa === 'top' || sa === 'bottom') && (sb === 'top' || sb === 'bottom')) {
        const mid = (y1 + y2) / 2
        path = `M ${x1} ${y1} L ${x1} ${mid} L ${x2} ${mid} L ${x2} ${y2}`
      } else if ((sa === 'left' || sa === 'right') && (sb === 'left' || sb === 'right')) {
        const mid = (x1 + x2) / 2
        path = `M ${x1} ${y1} L ${mid} ${y1} L ${mid} ${y2} L ${x2} ${y2}`
      } else {
        path = `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2}`
      }
    }
    return {
      index: i,
      kind,
      color: st.color || '#7a5d32',
      width: st.width || 1.4,
      path, dotX: x2, dotY: y2,
    }
  }).filter(Boolean) as EdgeLine[]
})

/* ---------- Auto layout ---------- */
function autoLayout(): void {
  // Простой автолейаут: группировка по поколениям на основе ролей.
  const GEN_MAP: Record<string, number> = {
    GRANDFATHER: 0, GRANDMOTHER: 0,
    FATHER: 1, MOTHER: 1, UNCLE: 1, AUNT: 1,
    SON: 2, DAUGHTER: 2, BROTHER: 2, SISTER: 2,
    NEPHEW: 3, NIECE: 3,
    GRANDSON: 4, GRANDDAUGHTER: 4,
    OTHER: 5,
  }
  const rows: Record<number, CanvasNode[]> = {}
  for (const n of state.nodes) {
    const m = memberOf(n)
    const role = ((m?.role || 'OTHER') + '').toUpperCase()
    const g = GEN_MAP[role] ?? 5
    rows[g] = rows[g] || []
    rows[g].push(n)
  }
  const marginX = 30, marginY = 40
  const hSpacing = 20, vSpacing = 40
  let y = marginY
  const sortedGens = Object.keys(rows).map(Number).sort((a, b) => a - b)
  for (const gen of sortedGens) {
    const row = rows[gen]
    const maxH = Math.max(...row.map(n => n.height))
    const totalW = row.reduce((s, n) => s + n.width, 0) + (row.length - 1) * hSpacing
    let x = Math.max(marginX, (props.pageWidth - totalW) / 2)
    for (const n of row) {
      n.x = x
      n.y = y
      x += n.width + hSpacing
    }
    y += maxH + vSpacing
  }
}

/* ---------- Style editing (selected) ---------- */
function ensureStyle(target: CanvasNode | CanvasEdge): Record<string, unknown> {
  if (!target.style) target.style = {}
  return target.style as Record<string, unknown>
}

function applyToAll<K extends keyof NodeStyle>(key: K, value: NodeStyle[K]): void {
  if (!state.defaults) state.defaults = {}
  ;(state.defaults as NodeStyle)[key] = value
  for (const n of state.nodes) {
    if (!n.style) n.style = {}
    ;(n.style as NodeStyle)[key] = value
  }
}

/* ---------- Keyboard ---------- */
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    cancelPendingEdge()
    selectedNodeId.value = null
    selectedEdgeIdx.value = null
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    const tag = (document.activeElement?.tagName || '').toLowerCase()
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return
    if (selectedNode.value || selectedEdge.value) {
      e.preventDefault()
      deleteSelected()
    }
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="pdf-canvas-editor">
    <!-- Toolbar -->
    <div class="ce-toolbar">
      <button class="tbtn" @click="fitToScreen" title="Вписать"><AppIcon name="filter_center_focus" :size="16" /></button>
      <button class="tbtn" @click="zoom(-0.15)" title="Меньше"><AppIcon name="remove" :size="16" /></button>
      <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
      <button class="tbtn" @click="zoom(0.15)" title="Больше"><AppIcon name="add" :size="16" /></button>
      <span class="sep" />
      <button class="tbtn" :disabled="!selectedNode" @click="duplicateNode" title="Дубликат">
        <AppIcon name="content_copy" :size="16" />
      </button>
      <button class="tbtn" :disabled="!selectedNode" @click="startEdge" :class="{ active: pendingEdgeFrom }" title="Click-to-click соединение">
        <AppIcon name="timeline" :size="16" />
        <span v-if="pendingEdgeFrom" class="tbtn-label">Клик по цели…</span>
        <span v-else class="tbtn-label">Связь</span>
      </button>
      <button class="tbtn danger" :disabled="!selectedNode && selectedEdgeIdx === null" @click="deleteSelected" title="Удалить">
        <AppIcon name="delete" :size="16" />
      </button>
      <span class="sep" />
      <button class="tbtn" @click="autoLayout" title="Автолейаут по ролям">
        <AppIcon name="auto_fix_high" :size="16" />
        <span class="tbtn-label">Авто</span>
      </button>
      <button class="tbtn" @click="clearAll" title="Очистить">
        <AppIcon name="layers_clear" :size="16" />
      </button>
    </div>

    <div class="ce-body">
      <!-- Sidebar: members list -->
      <aside class="ce-sidebar">
        <div class="ce-sidebar-title">Список членов семьи</div>
        <div class="ce-member-list">
          <button
            v-for="m in members"
            :key="m.id"
            class="ce-member-item"
            :class="{ used: m.id != null && usedIds.has(String(m.id)) }"
            @click="addMember(m)"
            :title="m.id != null && usedIds.has(String(m.id)) ? 'Уже на холсте, клик — добавить ещё одну копию' : 'Добавить на холст'"
          >
            <AppIcon name="person_add" :size="14" />
            <span class="ce-member-name">
              {{ [m.lastName, m.firstName].filter(Boolean).join(' ') || m.firstName || '—' }}
            </span>
            <span class="ce-member-role">{{ m.role || 'OTHER' }}</span>
          </button>
          <p v-if="!members.length" class="ce-empty">Нет членов семьи.</p>
        </div>
      </aside>

      <!-- Canvas -->
      <div class="ce-canvas-wrap" ref="viewport" @click="selectNode(null)">
        <div
          class="ce-page"
          :style="{
            width: pageWidth + 'px',
            height: pageHeight + 'px',
            transform: `scale(${scale})`
          }"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <!-- Edges (drawn) + live preview -->
          <svg class="ce-edges" :viewBox="`0 0 ${pageWidth} ${pageHeight}`" preserveAspectRatio="none">
            <g v-for="e in edgeLines" :key="e.index">
              <path
                :d="e.path"
                :stroke="e.color"
                :stroke-width="e.width"
                fill="none"
                :class="{ selected: selectedEdgeIdx === e.index }"
                @click.stop="selectEdge(e.index, $event)"
              />
              <circle :cx="e.dotX" :cy="e.dotY" :r="2.5" :fill="e.color" />
            </g>
            <path
              v-if="liveEdge"
              :d="liveEdgePath"
              stroke="var(--color-accent)"
              stroke-width="2"
              stroke-dasharray="5 4"
              fill="none"
            />
          </svg>

          <!-- Nodes -->
          <div
            v-for="n in state.nodes"
            :key="n.id"
            class="ce-node"
            :data-node-id="n.id"
            :class="{ selected: selectedNodeId === n.id, 'edge-target': liveEdge && liveEdge.fromId !== n.id }"
            :style="{
              left: n.x + 'px',
              top: n.y + 'px',
              width: n.width + 'px',
              height: n.height + 'px',
              background: (n.style?.bg_color || state.defaults?.bg_color || '#fdf9ec'),
              borderColor: (n.style?.border_color || state.defaults?.border_color || '#96723d'),
              color: (n.style?.text_color || state.defaults?.text_color || '#3f2e14'),
              borderRadius: (n.style?.radius ?? state.defaults?.radius ?? 8) + 'px',
              borderWidth: (n.style?.border_width ?? state.defaults?.border_width ?? 1.4) + 'px'
            }"
            @pointerdown="startNodeDrag(n, $event)"
            @click.stop="pendingEdgeFrom ? completeEdge(n) : selectNode(n.id, $event)"
          >
            <div class="ce-node-body">
              <div class="ce-node-avatar" :style="{ borderColor: n.style?.accent_color || n.style?.border_color || '#96723d' }">
                <img v-if="memberOf(n)?.photoUri" :src="memberOf(n)?.photoUri || ''" alt="" />
                <AppIcon v-else name="person" :size="22" />
              </div>
              <div class="ce-node-name">{{ memberName(n) }}</div>
              <div class="ce-node-role" :style="{ color: n.style?.role_color || '#3f7a4d' }">
                {{ memberOf(n)?.role || 'OTHER' }}
              </div>
              <div v-if="memberOf(n)?.birthDate" class="ce-node-date">
                {{ memberOf(n)?.birthDate }}
              </div>
            </div>

            <!-- Коннекторы (видны при выделении) -->
            <template v-if="selectedNodeId === n.id || liveEdge">
              <div
                class="ce-port ce-port-top"
                data-no-drag
                title="Связь сверху"
                @pointerdown.stop="startEdgeDrag(n, 'top', $event)"
                @pointermove.stop="onEdgeDragMove"
                @pointerup.stop="onEdgeDragEnd"
                @pointercancel.stop="onEdgeDragEnd"
              />
              <div
                class="ce-port ce-port-bottom"
                data-no-drag
                title="Связь снизу"
                @pointerdown.stop="startEdgeDrag(n, 'bottom', $event)"
                @pointermove.stop="onEdgeDragMove"
                @pointerup.stop="onEdgeDragEnd"
                @pointercancel.stop="onEdgeDragEnd"
              />
              <div
                class="ce-port ce-port-left"
                data-no-drag
                title="Связь слева"
                @pointerdown.stop="startEdgeDrag(n, 'left', $event)"
                @pointermove.stop="onEdgeDragMove"
                @pointerup.stop="onEdgeDragEnd"
                @pointercancel.stop="onEdgeDragEnd"
              />
              <div
                class="ce-port ce-port-right"
                data-no-drag
                title="Связь справа"
                @pointerdown.stop="startEdgeDrag(n, 'right', $event)"
                @pointermove.stop="onEdgeDragMove"
                @pointerup.stop="onEdgeDragEnd"
                @pointercancel.stop="onEdgeDragEnd"
              />
            </template>

            <div
              class="ce-resize-handle"
              data-no-drag
              @pointerdown.stop="startNodeDrag(n, $event, 'resize-br')"
            />
          </div>
        </div>
      </div>

      <!-- Inspector -->
      <aside class="ce-inspector" v-if="selectedNode || selectedEdge">
        <div v-if="selectedNode" class="insp-block">
          <div class="insp-title">Карточка</div>
          <div class="insp-grid">
            <label>Фон
              <input type="color" :value="selectedNode.style?.bg_color || state.defaults?.bg_color || '#fdf9ec'"
                     @input="(ensureStyle(selectedNode) as any).bg_color = ($event.target as HTMLInputElement).value">
            </label>
            <label>Рамка
              <input type="color" :value="selectedNode.style?.border_color || state.defaults?.border_color || '#96723d'"
                     @input="(ensureStyle(selectedNode) as any).border_color = ($event.target as HTMLInputElement).value">
            </label>
            <label>Текст
              <input type="color" :value="selectedNode.style?.text_color || state.defaults?.text_color || '#3f2e14'"
                     @input="(ensureStyle(selectedNode) as any).text_color = ($event.target as HTMLInputElement).value">
            </label>
            <label>Роль
              <input type="color" :value="selectedNode.style?.role_color || state.defaults?.role_color || '#3f7a4d'"
                     @input="(ensureStyle(selectedNode) as any).role_color = ($event.target as HTMLInputElement).value">
            </label>
            <label class="full">Размер шрифта
              <input type="range" min="0.7" max="1.6" step="0.05"
                     :value="selectedNode.style?.font_scale ?? 1"
                     @input="(ensureStyle(selectedNode) as any).font_scale = Number(($event.target as HTMLInputElement).value)">
              <span class="v-val">{{ ((selectedNode.style?.font_scale ?? 1) * 100).toFixed(0) }}%</span>
            </label>
            <label class="full">Скругление
              <input type="range" min="0" max="24" step="1"
                     :value="selectedNode.style?.radius ?? 8"
                     @input="(ensureStyle(selectedNode) as any).radius = Number(($event.target as HTMLInputElement).value)">
              <span class="v-val">{{ selectedNode.style?.radius ?? 8 }}px</span>
            </label>
            <label>Шрифт
              <select :value="selectedNode.style?.font_family || state.defaults?.font_family || 'serif'"
                      @change="(ensureStyle(selectedNode) as any).font_family = ($event.target as HTMLSelectElement).value">
                <option value="sans">Без засечек</option>
                <option value="serif">С засечками</option>
                <option value="mono">Моноширинный</option>
              </select>
            </label>
            <label>Фото
              <select :value="selectedNode.style?.photo_shape || 'circle'"
                      @change="(ensureStyle(selectedNode) as any).photo_shape = ($event.target as HTMLSelectElement).value">
                <option value="circle">Круг</option>
                <option value="rounded">Скруглённый</option>
                <option value="square">Квадрат</option>
              </select>
            </label>
            <label class="toggle-line">
              <input type="checkbox" :checked="(selectedNode.style?.show_photo ?? true)"
                     @change="(ensureStyle(selectedNode) as any).show_photo = ($event.target as HTMLInputElement).checked">
              Показать фото
            </label>
            <label class="toggle-line">
              <input type="checkbox" :checked="(selectedNode.style?.show_dates ?? true)"
                     @change="(ensureStyle(selectedNode) as any).show_dates = ($event.target as HTMLInputElement).checked">
              Показать даты
            </label>
            <label class="toggle-line">
              <input type="checkbox" :checked="(selectedNode.style?.show_patronymic ?? true)"
                     @change="(ensureStyle(selectedNode) as any).show_patronymic = ($event.target as HTMLInputElement).checked">
              Отчество
            </label>
            <label class="toggle-line">
              <input type="checkbox" :checked="(selectedNode.style?.shadow ?? true)"
                     @change="(ensureStyle(selectedNode) as any).shadow = ($event.target as HTMLInputElement).checked">
              Тень
            </label>
          </div>
          <div class="insp-grid size-grid">
            <label>X
              <input type="number" :value="Math.round(selectedNode.x)"
                     @input="selectedNode.x = Number(($event.target as HTMLInputElement).value)">
            </label>
            <label>Y
              <input type="number" :value="Math.round(selectedNode.y)"
                     @input="selectedNode.y = Number(($event.target as HTMLInputElement).value)">
            </label>
            <label>Ширина
              <input type="number" :value="Math.round(selectedNode.width)"
                     @input="selectedNode.width = Number(($event.target as HTMLInputElement).value)">
            </label>
            <label>Высота
              <input type="number" :value="Math.round(selectedNode.height)"
                     @input="selectedNode.height = Number(($event.target as HTMLInputElement).value)">
            </label>
          </div>
          <button class="apply-all-btn" @click="() => { if (selectedNode?.style) Object.assign(state.defaults || (state.defaults = {}), selectedNode.style); for (const nn of state.nodes) nn.style = { ...(state.defaults || {}) } }">
            Применить стиль ко всем
          </button>
        </div>

        <div v-else-if="selectedEdge" class="insp-block">
          <div class="insp-title">Связь</div>
          <div class="insp-grid">
            <label>Тип
              <select :value="selectedEdge.style?.kind || 'orthogonal'"
                      @change="(ensureStyle(selectedEdge) as any).kind = ($event.target as HTMLSelectElement).value">
                <option value="orthogonal">Прямые углы</option>
                <option value="curve">Изогнутая</option>
                <option value="straight">Прямая</option>
              </select>
            </label>
            <label>Цвет
              <input type="color" :value="selectedEdge.style?.color || '#7a5d32'"
                     @input="(ensureStyle(selectedEdge) as any).color = ($event.target as HTMLInputElement).value">
            </label>
            <label class="full">Толщина
              <input type="range" min="0.5" max="4" step="0.1"
                     :value="selectedEdge.style?.width ?? 1.4"
                     @input="(ensureStyle(selectedEdge) as any).width = Number(($event.target as HTMLInputElement).value)">
              <span class="v-val">{{ (selectedEdge.style?.width ?? 1.4).toFixed(1) }}</span>
            </label>
          </div>
        </div>
      </aside>
    </div>

    <div class="ce-footer">
      <span>{{ state.nodes.length }} карточек · {{ state.edges.length }} связей</span>
      <span class="hint">
        Тяни из <b>синих точек</b> на карточке → другая карточка. Или кнопка «Связь» → клик по цели. Esc — отмена.
      </span>
      <span>Страница: {{ Math.round(pageWidth) }}×{{ Math.round(pageHeight) }} pt</span>
    </div>
  </div>
</template>

<style scoped>
.pdf-canvas-editor {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  overflow: hidden;
  height: 640px;
  max-height: 80vh;
}

.ce-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  background: var(--color-bg-alt);
  border-bottom: 1px solid var(--color-glass-border);
}

.tbtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 0.82rem;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}

.tbtn:hover:not(:disabled) {
  color: var(--color-text);
  border-color: var(--color-accent);
  background: var(--input-hover-bg);
}

.tbtn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tbtn.active {
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent);
}

.tbtn.danger:hover:not(:disabled) {
  color: var(--color-error);
  border-color: var(--color-error);
}

.tbtn-label {
  font-size: 0.78rem;
}

.sep {
  width: 1px;
  height: 20px;
  background: var(--color-glass-border);
  margin: 0 4px;
}

.zoom-label {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 42px;
  text-align: center;
}

.ce-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.ce-sidebar {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-glass-border);
  display: flex;
  flex-direction: column;
  background: var(--color-bg-alt);
}

.ce-sidebar-title {
  padding: 10px 12px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-glass-border);
}

.ce-member-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.ce-member-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-size: 0.82rem;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.ce-member-item:hover {
  background: var(--input-hover-bg);
  border-color: var(--color-glass-border);
}

.ce-member-item.used {
  opacity: 0.6;
}

.ce-member-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ce-member-role {
  font-size: 0.68rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.ce-empty {
  padding: 10px;
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

.ce-canvas-wrap {
  flex: 1;
  overflow: auto;
  background:
    linear-gradient(45deg, var(--input-bg) 25%, transparent 25%) 0 0 / 20px 20px,
    linear-gradient(-45deg, var(--input-bg) 25%, transparent 25%) 0 10px / 20px 20px,
    var(--color-bg-alt);
  position: relative;
  padding: 12px;
}

.ce-page {
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--color-glass-border), 0 4px 18px rgba(0, 0, 0, 0.2);
  transform-origin: 0 0;
  position: relative;
}

.ce-edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.ce-edges path {
  pointer-events: stroke;
  cursor: pointer;
  fill: none;
}

.ce-edges path.selected {
  stroke-dasharray: 6 4;
  animation: dash 1s linear infinite;
}

@keyframes dash {
  to { stroke-dashoffset: -20; }
}

.ce-node {
  position: absolute;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  border: 1.4px solid #96723d;
  background: #fdf9ec;
  color: #3f2e14;
  cursor: move;
  user-select: none;
  box-shadow: 2px 3px 0 rgba(0, 0, 0, 0.12);
  overflow: hidden;
}

.ce-node.selected {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.ce-node-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 6px;
  text-align: center;
  min-width: 0;
}

.ce-node-avatar {
  width: 54%;
  aspect-ratio: 1;
  border-radius: 50%;
  border: 2px solid #96723d;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3e9cf;
  color: #7a5d32;
}

.ce-node-avatar img {
  width: 100%; height: 100%; object-fit: cover;
}

.ce-node-name {
  font-weight: 600;
  font-size: 0.82rem;
  line-height: 1.1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.ce-node-role {
  font-style: italic;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.ce-node-date {
  font-size: 0.7rem;
  opacity: 0.8;
}

.ce-resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 12px;
  height: 12px;
  cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.25) 50%);
}

/* Коннекторы для связей */
.ce-port {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent);
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px var(--color-accent), 0 2px 6px rgba(0, 0, 0, 0.3);
  cursor: crosshair;
  z-index: 2;
  transition: transform 0.12s, background 0.12s;
}

.ce-port:hover {
  transform: scale(1.35);
  background: var(--color-success, #34d399);
}

.ce-port-top {
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
}

.ce-port-top:hover {
  transform: translateX(-50%) scale(1.35);
}

.ce-port-bottom {
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
}

.ce-port-bottom:hover {
  transform: translateX(-50%) scale(1.35);
}

.ce-port-left {
  left: -6px;
  top: 50%;
  transform: translateY(-50%);
}

.ce-port-left:hover {
  transform: translateY(-50%) scale(1.35);
}

.ce-port-right {
  right: -6px;
  top: 50%;
  transform: translateY(-50%);
}

.ce-port-right:hover {
  transform: translateY(-50%) scale(1.35);
}

.ce-node.edge-target:hover {
  outline: 2px solid var(--color-success, #34d399);
  outline-offset: 2px;
}

.ce-inspector {
  width: 260px;
  flex-shrink: 0;
  border-left: 1px solid var(--color-glass-border);
  background: var(--color-bg-alt);
  overflow-y: auto;
}

.insp-block {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.insp-title {
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-secondary);
}

.insp-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.insp-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}

.insp-grid label.full {
  grid-column: 1 / -1;
}

.insp-grid label.toggle-line {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  color: var(--color-text);
  font-size: 0.82rem;
}

.insp-grid input[type='color'] {
  width: 100%;
  height: 28px;
  background: transparent;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  padding: 1px;
  cursor: pointer;
}

.insp-grid input[type='number'],
.insp-grid select {
  width: 100%;
  min-height: 30px;
  padding: 4px 8px;
  border: 1px solid var(--color-glass-border);
  background: var(--input-bg);
  color: var(--color-text);
  border-radius: var(--radius-sm);
  font-size: 0.82rem;
}

.insp-grid input[type='range'] {
  width: 100%;
  accent-color: var(--color-accent);
}

.size-grid {
  grid-template-columns: 1fr 1fr;
}

.v-val {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  align-self: flex-end;
}

.apply-all-btn {
  padding: 8px 10px;
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.apply-all-btn:hover {
  background: var(--color-accent-dark);
}

.ce-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 12px;
  border-top: 1px solid var(--color-glass-border);
  background: var(--color-bg-alt);
  color: var(--color-text-muted);
  font-size: 0.72rem;
}

.ce-footer .hint {
  flex: 1;
  text-align: center;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ce-footer .hint b {
  color: var(--color-accent);
}

@media (max-width: 900px) {
  .ce-sidebar, .ce-inspector {
    width: 170px;
  }
}
</style>
