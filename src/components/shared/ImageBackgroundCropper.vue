<script setup lang="ts">
/**
 * Кроппер фонового изображения под заданное соотношение сторон.
 *
 * Работает полностью на клиенте: загружаем файл → пользователь позиционирует/зумит →
 * результат рендерим в <canvas> с точным соотношением → отдаём через `update:modelValue`
 * как data URL того же формата, что и исходник (PNG остаётся PNG, JPEG — JPEG).
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'

interface Props {
  /** Текущее значение (data URL готовой картинки). */
  modelValue: string
  /** Ширина / высота PDF страницы для правильного соотношения. */
  aspectWidth: number
  aspectHeight: number
  /** Целевая ширина итогового изображения, px. Высота считается по aspect. */
  outputWidth?: number
  /** Качество JPEG 0..1. Для PNG игнорируется. */
  quality?: number
}

const props = withDefaults(defineProps<Props>(), {
  outputWidth: 1600,
  quality: 0.88
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', meta: { width: number; height: number; sizeKb: number; mime: string }): void
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const stageRef = ref<HTMLDivElement | null>(null)

/** Оригинальное изображение после загрузки. */
const sourceImage = ref<HTMLImageElement | null>(null)
const sourceMime = ref<'image/png' | 'image/jpeg'>('image/jpeg')
const sourceSizeKb = ref(0)
const loadError = ref('')

/** Трансформация (позиция + зум), применяется внутри превью. */
const offsetX = ref(0)
const offsetY = ref(0)
const scale = ref(1)

/** Текущая итоговая обрезка (для отображения размера). */
const resultMeta = ref<{ width: number; height: number; sizeKb: number } | null>(null)

const aspectRatio = computed(() => {
  const { aspectWidth, aspectHeight } = props
  if (!aspectWidth || !aspectHeight) return 1
  return aspectWidth / aspectHeight
})

const stageStyle = computed(() => ({
  aspectRatio: `${props.aspectWidth} / ${props.aspectHeight}`
}))

const hasImage = computed(() => sourceImage.value !== null)

/** Масштаб картинки внутри превью (в пикселях экрана). */
const baseFit = ref(1)
/** Вычисленные параметры превью. */
const stageWidth = ref(0)
const stageHeight = ref(0)

function openPicker(): void {
  fileInput.value?.click()
}

function onFile(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  loadFile(file)
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  const file = e.dataTransfer?.files?.[0]
  if (file) loadFile(file)
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
}

function loadFile(file: File): void {
  loadError.value = ''
  if (!file.type.startsWith('image/')) {
    loadError.value = 'Нужен файл изображения (PNG или JPG).'
    return
  }
  sourceMime.value = file.type === 'image/png' ? 'image/png' : 'image/jpeg'
  sourceSizeKb.value = Math.round(file.size / 1024)

  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      sourceImage.value = img
      resetTransform()
      scheduleRender()
    }
    img.onerror = () => {
      loadError.value = 'Не удалось загрузить изображение.'
    }
    img.src = String(reader.result || '')
  }
  reader.onerror = () => {
    loadError.value = 'Ошибка чтения файла.'
  }
  reader.readAsDataURL(file)
}

/**
 * Загрузить изображение по URL (например, готовый фон из /backgrounds/).
 * Скачиваем как blob, превращаем в File и пропускаем через обычный loadFile,
 * чтобы состояние кроппера (offsets, scale) инициализировалось корректно.
 */
async function loadFromUrl(url: string): Promise<void> {
  loadError.value = ''
  try {
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const mime = blob.type.startsWith('image/') ? blob.type : 'image/png'
    const name = url.split('/').pop() || 'preset.png'
    const file = new File([blob], name, { type: mime })
    loadFile(file)
  } catch (e) {
    loadError.value = 'Не удалось загрузить готовый фон: ' + (e as Error).message
  }
}

defineExpose({ loadFromUrl })

/** Обновляем размеры превью по текущему контейнеру. */
function measureStage(): void {
  const el = stageRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  stageWidth.value = rect.width
  stageHeight.value = rect.height
}

/** При загрузке/смене пропорций центрируем и вписываем картинку. */
function resetTransform(): void {
  const img = sourceImage.value
  measureStage()
  if (!img || !stageWidth.value || !stageHeight.value) {
    offsetX.value = 0
    offsetY.value = 0
    scale.value = 1
    baseFit.value = 1
    return
  }
  // "Cover" — картинка заполняет кадр без пустых полей.
  const fit = Math.max(stageWidth.value / img.naturalWidth, stageHeight.value / img.naturalHeight)
  baseFit.value = fit
  scale.value = 1
  // Центрируем
  const drawW = img.naturalWidth * fit
  const drawH = img.naturalHeight * fit
  offsetX.value = (stageWidth.value - drawW) / 2
  offsetY.value = (stageHeight.value - drawH) / 2
}

/** Сдерживаем картинку, чтобы не уезжала за пределы кадра. */
function clampTransform(): void {
  const img = sourceImage.value
  if (!img) return
  const drawW = img.naturalWidth * baseFit.value * scale.value
  const drawH = img.naturalHeight * baseFit.value * scale.value
  if (drawW >= stageWidth.value) {
    const minX = stageWidth.value - drawW
    if (offsetX.value > 0) offsetX.value = 0
    if (offsetX.value < minX) offsetX.value = minX
  } else {
    // Картинка уже и кадра — центрируем по X
    offsetX.value = (stageWidth.value - drawW) / 2
  }
  if (drawH >= stageHeight.value) {
    const minY = stageHeight.value - drawH
    if (offsetY.value > 0) offsetY.value = 0
    if (offsetY.value < minY) offsetY.value = minY
  } else {
    offsetY.value = (stageHeight.value - drawH) / 2
  }
}

/** Перетаскивание. */
const dragState = ref<{ x: number; y: number; ox: number; oy: number } | null>(null)

function onPointerDown(e: PointerEvent): void {
  if (!sourceImage.value) return
  const target = e.currentTarget as HTMLElement
  target.setPointerCapture(e.pointerId)
  dragState.value = { x: e.clientX, y: e.clientY, ox: offsetX.value, oy: offsetY.value }
}

function onPointerMove(e: PointerEvent): void {
  if (!dragState.value) return
  offsetX.value = dragState.value.ox + (e.clientX - dragState.value.x)
  offsetY.value = dragState.value.oy + (e.clientY - dragState.value.y)
  clampTransform()
  scheduleRender()
}

function onPointerUp(e: PointerEvent): void {
  const target = e.currentTarget as HTMLElement
  try { target.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
  dragState.value = null
}

function onWheel(e: WheelEvent): void {
  if (!sourceImage.value) return
  e.preventDefault()
  const delta = -e.deltaY * 0.0015
  applyScaleChange(scale.value + delta, e.offsetX, e.offsetY)
}

function onScaleSliderInput(e: Event): void {
  const value = Number((e.target as HTMLInputElement).value)
  applyScaleChange(value, stageWidth.value / 2, stageHeight.value / 2)
}

function applyScaleChange(nextScale: number, anchorX: number, anchorY: number): void {
  const img = sourceImage.value
  if (!img) return
  const clamped = Math.max(1, Math.min(6, nextScale))
  // Сохраняем точку под курсором неподвижной.
  const imgPointX = (anchorX - offsetX.value) / scale.value
  const imgPointY = (anchorY - offsetY.value) / scale.value
  scale.value = clamped
  offsetX.value = anchorX - imgPointX * scale.value
  offsetY.value = anchorY - imgPointY * scale.value
  clampTransform()
  scheduleRender()
}

function recenter(): void {
  resetTransform()
  scheduleRender()
}

function clearImage(): void {
  sourceImage.value = null
  resultMeta.value = null
  emit('update:modelValue', '')
}

/** Рендерим превью → canvas → data URL. */
let renderTimer: ReturnType<typeof setTimeout> | null = null
function scheduleRender(): void {
  if (renderTimer) clearTimeout(renderTimer)
  renderTimer = setTimeout(render, 120)
}

function render(): void {
  const img = sourceImage.value
  if (!img || !stageWidth.value || !stageHeight.value) return

  const outW = Math.max(200, Math.round(props.outputWidth))
  const outH = Math.round(outW / aspectRatio.value)

  // Как картинка в оригинальных пикселях попадает в кадр превью:
  //   drawW_preview = img.naturalWidth * baseFit * scale
  //   а превью по высоте stageHeight.value соответствует outH.
  // Значит, пиксели оригинала на выходе: natural * (outH / stageHeight)
  const previewToOutput = outH / stageHeight.value
  const canvas = document.createElement('canvas')
  canvas.width = outW
  canvas.height = outH
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, outW, outH)

  const drawW = img.naturalWidth * baseFit.value * scale.value * previewToOutput
  const drawH = img.naturalHeight * baseFit.value * scale.value * previewToOutput
  const drawX = offsetX.value * previewToOutput
  const drawY = offsetY.value * previewToOutput

  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(img, drawX, drawY, drawW, drawH)

  const dataUrl =
    sourceMime.value === 'image/png'
      ? canvas.toDataURL('image/png')
      : canvas.toDataURL('image/jpeg', props.quality)
  const approxKb = Math.round((dataUrl.length * 3) / 4 / 1024)
  resultMeta.value = { width: outW, height: outH, sizeKb: approxKb }
  emit('update:modelValue', dataUrl)
  emit('change', { width: outW, height: outH, sizeKb: approxKb, mime: sourceMime.value })
}

/** На случай смены aspect ratio — пересчитываем. */
watch(aspectRatio, () => {
  if (sourceImage.value) {
    resetTransform()
    scheduleRender()
  }
})

/** Слушаем ресайз, чтобы корректно рендерить превью. */
let resizeObserver: ResizeObserver | null = null
watch(stageRef, (el, _old, onCleanup) => {
  if (!el) return
  resizeObserver = new ResizeObserver(() => {
    const prevW = stageWidth.value
    measureStage()
    if (prevW && stageWidth.value && sourceImage.value) {
      // Сохраняем относительное позиционирование при resize
      const ratio = stageWidth.value / prevW
      offsetX.value *= ratio
      offsetY.value *= ratio
      baseFit.value *= ratio
      clampTransform()
      scheduleRender()
    } else {
      measureStage()
    }
  })
  resizeObserver.observe(el)
  onCleanup(() => {
    resizeObserver?.disconnect()
    resizeObserver = null
  })
})

onBeforeUnmount(() => {
  if (renderTimer) clearTimeout(renderTimer)
})
</script>

<template>
  <div class="bg-cropper">
    <!-- Зона превью / выбора -->
    <div
      v-if="!hasImage"
      class="drop-zone"
      @click="openPicker"
      @drop="onDrop"
      @dragover="onDragOver"
      role="button"
      tabindex="0"
    >
      <AppIcon name="image" :size="40" class="drop-zone-icon" />
      <p class="drop-zone-label">
        Перетащите PNG или JPG сюда
        <span class="drop-zone-or">или нажмите для выбора</span>
      </p>
      <p class="drop-zone-hint">
        Картинка будет точно подогнана под соотношение страницы
        <strong>{{ aspectWidth }}×{{ aspectHeight }}</strong>
      </p>
    </div>

    <div v-else class="cropper-body">
      <div
        ref="stageRef"
        class="cropper-stage"
        :style="stageStyle"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @pointerleave="onPointerUp"
        @wheel="onWheel"
      >
        <img
          v-if="sourceImage"
          :src="sourceImage.src"
          alt="background"
          class="cropper-image"
          draggable="false"
          :style="{
            transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale})`,
            width: sourceImage.naturalWidth * baseFit + 'px',
            height: sourceImage.naturalHeight * baseFit + 'px'
          }"
        />
        <div class="cropper-guides">
          <span class="guide-h guide-h-1" />
          <span class="guide-h guide-h-2" />
          <span class="guide-v guide-v-1" />
          <span class="guide-v guide-v-2" />
        </div>
      </div>

      <div class="cropper-controls">
        <label class="scale-slider">
          <AppIcon name="zoom_in" :size="18" />
          <input
            type="range"
            min="1"
            max="4"
            step="0.01"
            :value="scale"
            @input="onScaleSliderInput"
          />
          <span class="scale-value">{{ Math.round(scale * 100) }}%</span>
        </label>

        <div class="cropper-actions">
          <button type="button" class="mini-btn" @click="recenter" title="Центрировать">
            <AppIcon name="filter_center_focus" :size="16" />
            <span>По центру</span>
          </button>
          <button type="button" class="mini-btn" @click="openPicker" title="Заменить">
            <AppIcon name="upload_file" :size="16" />
            <span>Заменить</span>
          </button>
          <button type="button" class="mini-btn danger" @click="clearImage" title="Удалить">
            <AppIcon name="delete" :size="16" />
            <span>Убрать</span>
          </button>
        </div>
      </div>

      <div class="cropper-meta">
        <span class="meta-chip">
          {{ aspectWidth }}×{{ aspectHeight }} соотношение
        </span>
        <span v-if="resultMeta" class="meta-chip">
          {{ resultMeta.width }}×{{ resultMeta.height }} px
        </span>
        <span v-if="resultMeta" class="meta-chip">
          ~{{ resultMeta.sizeKb }} КБ
        </span>
        <span v-if="sourceSizeKb" class="meta-chip subtle">
          оригинал: {{ sourceSizeKb }} КБ
        </span>
      </div>
    </div>

    <p v-if="loadError" class="error-msg">{{ loadError }}</p>

    <input
      ref="fileInput"
      type="file"
      accept="image/png,image/jpeg"
      style="display: none"
      @change="onFile"
    />
  </div>
</template>

<style scoped>
.bg-cropper {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 28px 20px;
  border: 2px dashed var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
  text-align: center;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.drop-zone:hover {
  border-color: var(--color-accent);
  background: var(--color-surface-hover);
}

.drop-zone-icon {
  color: var(--color-text-secondary);
}

.drop-zone-label {
  margin: 0;
  font-weight: 500;
  color: var(--color-text);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.drop-zone-or {
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--color-text-secondary);
}

.drop-zone-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

.cropper-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cropper-stage {
  position: relative;
  width: 100%;
  max-height: 420px;
  overflow: hidden;
  border-radius: var(--radius-md);
  background:
    linear-gradient(45deg, var(--input-bg) 25%, transparent 25%) 0 0 / 20px 20px,
    linear-gradient(-45deg, var(--input-bg) 25%, transparent 25%) 0 10px / 20px 20px,
    linear-gradient(45deg, transparent 75%, var(--input-bg) 75%) 10px -10px / 20px 20px,
    linear-gradient(-45deg, transparent 75%, var(--input-bg) 75%) -10px 0 / 20px 20px,
    var(--color-bg-alt, #111627);
  border: 1px solid var(--color-glass-border);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.cropper-stage:active {
  cursor: grabbing;
}

.cropper-image {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  pointer-events: none;
  will-change: transform;
}

.cropper-guides {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.cropper-guides .guide-h,
.cropper-guides .guide-v {
  position: absolute;
  background: rgba(255, 255, 255, 0.25);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
}

.cropper-guides .guide-h {
  left: 0;
  right: 0;
  height: 1px;
}

.cropper-guides .guide-v {
  top: 0;
  bottom: 0;
  width: 1px;
}

.cropper-guides .guide-h-1 { top: 33.333%; }
.cropper-guides .guide-h-2 { top: 66.666%; }
.cropper-guides .guide-v-1 { left: 33.333%; }
.cropper-guides .guide-v-2 { left: 66.666%; }

.cropper-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.scale-slider {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}

.scale-slider input[type='range'] {
  flex: 1;
  accent-color: var(--color-accent);
}

.scale-value {
  font-variant-numeric: tabular-nums;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  min-width: 44px;
  text-align: right;
}

.cropper-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  color: var(--color-text-secondary);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}

.mini-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-text);
  background: var(--input-hover-bg);
}

.mini-btn.danger:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.cropper-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-chip {
  padding: 3px 8px;
  font-size: 0.72rem;
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.meta-chip.subtle {
  opacity: 0.65;
}

.error-msg {
  margin: 4px 0 0;
  color: var(--color-error);
  font-size: 0.8rem;
}
</style>
