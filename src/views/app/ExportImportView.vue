<script setup lang="ts">
import { reactive, ref, onMounted, computed, nextTick } from 'vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
import ImageBackgroundCropper from '@/components/shared/ImageBackgroundCropper.vue'
import PdfCanvasEditor from '@/components/shared/PdfCanvasEditor.vue'
import type { CanvasState } from '@/components/shared/PdfCanvasEditor.vue'
import { useMemberStore } from '@/stores/memberStore'
import { addBackupAudit } from '@/db/repositories'
import {
  generatePdf,
  generatePdfV2,
  generatePdfV3,
  fetchPdfV2Options
} from '@/services/api'
import type { PdfV2Options, PdfV2BackgroundConfig } from '@/types/api'
import type { PdfV3Node, PdfV3Edge } from '@/services/api'
import { exportMembersToCsv, exportMembersToJson, importMembersFromJsonText } from '@/services/memberData'
import { downloadBlob, downloadText } from '@/utils/download'

const memberStore = useMemberStore()
const importInput = ref<HTMLInputElement | null>(null)

const importMode = ref<'merge' | 'replace'>('merge')
const importing = ref(false)
const pdfBusy = ref(false)
const pdfProgress = ref(0)
const dragOver = ref(false)
const status = ref('')
const error = ref('')

const pdfSettings = reactive({
  format: 'A4_LANDSCAPE',
  use_drive: false,
  show_photos: true,
  show_dates: true,
  show_patronymic: true,
  title: 'Семейное древо',
  photo_quality: 'medium'
})

// --- PDF v2: гибкие настройки стиля ---
const pdfVersion = ref<'v1' | 'v2' | 'v3'>('v1')

const pdfV2Options = reactive({
  themes: ['vintage', 'modern', 'minimal', 'dark', 'sakura', 'forest', 'paper'],
  cardStyles: ['classic', 'modern', 'minimal', 'dark', 'photo', 'poster'],
  layouts: ['generations', 'compact', 'centered'],
  photoShapes: ['circle', 'rounded', 'square'],
  connectionStyles: ['orthogonal', 'curve', 'straight'],
  fontFamilies: ['sans', 'serif', 'mono'],
  backgroundTypes: ['color', 'gradient', 'image']
})

const THEME_LABELS: Record<string, string> = {
  vintage: 'Винтаж',
  modern: 'Современная',
  minimal: 'Минимализм',
  dark: 'Тёмная',
  sakura: 'Сакура',
  forest: 'Лес',
  paper: 'Бумага'
}

const CARD_STYLE_LABELS: Record<string, string> = {
  classic: 'Классика',
  modern: 'Современный',
  minimal: 'Минимал',
  dark: 'Тёмный',
  photo: 'С фото',
  poster: 'Постер'
}

const LAYOUT_LABELS: Record<string, string> = {
  generations: 'Поколения',
  compact: 'Компакт',
  centered: 'По центру'
}

const PHOTO_SHAPE_LABELS: Record<string, string> = {
  circle: 'Круг',
  rounded: 'Скруглённый',
  square: 'Квадрат'
}

const CONNECTION_LABELS: Record<string, string> = {
  orthogonal: 'Прямые углы',
  curve: 'Изогнутые',
  straight: 'Прямая линия'
}

const FONT_LABELS: Record<string, string> = {
  sans: 'Без засечек',
  serif: 'С засечками',
  mono: 'Моноширинный'
}

const BG_TYPE_LABELS: Record<string, string> = {
  color: 'Однотонный',
  gradient: 'Градиент',
  image: 'Изображение'
}

// Готовые фоны из public/backgrounds. URL будет вида `/backgrounds/<файл>`.
interface BgPreset {
  id: string
  label: string
  file: string
  category: 'season' | 'parchment'
}

const BG_PRESETS: BgPreset[] = [
  { id: 'summer',     label: 'Лето',         file: 'лето.png',        category: 'season' },
  { id: 'autumn',     label: 'Осень',        file: 'Осень.png',       category: 'season' },
  { id: 'parchment1', label: 'Пергамент 1',  file: 'пергамент1.png',  category: 'parchment' },
  { id: 'parchment2', label: 'Пергамент 2',  file: 'пергамент2.png',  category: 'parchment' },
  { id: 'parchment3', label: 'Пергамент 3',  file: 'пергамент3.png',  category: 'parchment' }
]

function bgPresetUrl(p: BgPreset): string {
  // encodeURI оставляет `/` нетронутым, но корректно кодирует кириллицу в имени файла.
  return encodeURI(`/backgrounds/${p.file}`)
}

const selectedBgPresetId = ref<string | null>(null)
const bgCropperV2 = ref<InstanceType<typeof ImageBackgroundCropper> | null>(null)
const bgCropperV3 = ref<InstanceType<typeof ImageBackgroundCropper> | null>(null)

async function applyBgPreset(preset: BgPreset): Promise<void> {
  selectedBgPresetId.value = preset.id
  pdfV2.use_custom_bg = true
  pdfV2.bg_type = 'image'
  const url = bgPresetUrl(preset)

  // Автоподбор ориентации PDF под ориентацию картинки, чтобы кроппер не
  // обрезал её. Сохраняем базу (A4/A3) и переключаем только portrait/landscape.
  try {
    const { w, h } = await probeImageSize(url)
    if (w && h) {
      const imgLandscape = w >= h
      const cur = pdfSettings.format
      const base = cur.startsWith('A3') ? 'A3' : 'A4'
      const target = imgLandscape ? `${base}_LANDSCAPE` : base
      if (target !== cur && PAGE_SIZES_PT[target]) {
        pdfSettings.format = target
      }
    }
  } catch { /* не критично, продолжаем */ }

  // Ждём рендер DOM, чтобы v-if='bg_type === image' отработал.
  await nextTick()
  const target = pdfVersion.value === 'v3' ? bgCropperV3.value : bgCropperV2.value
  if (target?.loadFromUrl) {
    await target.loadFromUrl(url)
  } else {
    pdfV2.bg_image_src = url
  }
}

function probeImageSize(url: string): Promise<{ w: number; h: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight })
    img.onerror = () => reject(new Error('probe failed'))
    img.src = url
  })
}

const pdfV2 = reactive({
  theme: 'vintage',
  card_style: 'classic',
  layout: 'generations',
  accent_color: '#96723d',
  photo_shape: 'circle' as 'circle' | 'rounded' | 'square',
  connection_style: 'orthogonal' as 'orthogonal' | 'curve' | 'straight',
  font_family: 'serif' as 'sans' | 'serif' | 'mono',
  show_social_roles: true,
  show_footer: true,
  show_subtitle: true,
  show_tree: true,
  show_leaves: true,
  show_corners: true,
  double_frame: true,
  show_title_on_page: false,
  use_custom_bg: false,
  bg_type: 'gradient' as 'color' | 'gradient' | 'image',
  bg_color: '#f7f0d9',
  bg_from: '#f7f0d9',
  bg_to: '#e8e0c8',
  bg_direction: 'vertical' as 'vertical' | 'horizontal' | 'diagonal',
  bg_image_src: '',
  bg_opacity: 1
})

// Палитра быстрых акцентов — зависит от темы
const themeAccents: Record<string, string[]> = {
  vintage: ['#96723d', '#b8862f', '#7a5d32', '#a84a2a'],
  modern: ['#3b82f6', '#10b981', '#f43f5e', '#8b5cf6'],
  minimal: ['#111111', '#555555', '#888888', '#222222'],
  dark: ['#60a5fa', '#34d399', '#fbbf24', '#f472b6'],
  sakura: ['#e11d74', '#f472b6', '#ec4899', '#be185d'],
  forest: ['#2f7a3d', '#256b2a', '#4a8b52', '#78a87a'],
  paper: ['#000000', '#222222', '#444444', '#666666']
}

const currentAccentPalette = computed(() => themeAccents[pdfV2.theme] || themeAccents.vintage)

// Размеры страниц PDF в точках (pt) — для соотношения сторон кроппера.
// ReportLab использует A4=595.276×841.890, A3=841.890×1190.551.
const PAGE_SIZES_PT: Record<string, [number, number]> = {
  A4: [595, 842],
  A4_LANDSCAPE: [842, 595],
  A3: [842, 1191],
  A3_LANDSCAPE: [1191, 842]
}

const pageAspect = computed(() => {
  const [w, h] = PAGE_SIZES_PT[pdfSettings.format] || PAGE_SIZES_PT.A4_LANDSCAPE
  return { width: w, height: h }
})

// --- PDF v3: canvas state ---
const canvasState = ref<CanvasState>({ nodes: [], edges: [], defaults: {} })

function clearMessages(): void {
  status.value = ''
  error.value = ''
}

// Fake progress ticker — плавно движется до ~90%, финальный скачок при завершении
let _progressTimer: ReturnType<typeof setInterval> | null = null

function startFakeProgress(): void {
  pdfProgress.value = 0
  _progressTimer = setInterval(() => {
    if (pdfProgress.value < 88) {
      pdfProgress.value += Math.random() * 4 + 1
    }
  }, 400)
}

function finishProgress(): void {
  if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null }
  pdfProgress.value = 100
  setTimeout(() => { pdfProgress.value = 0 }, 800)
}

async function ensureMembers(): Promise<void> {
  if (!memberStore.members.length) {
    await memberStore.refresh()
  }
}

async function exportJsonFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  const content = exportMembersToJson(memberStore.members)
  const fileName = `familyone_members_${new Date().toISOString().slice(0, 10)}.json`
  downloadText(content, fileName, 'application/json;charset=utf-8')
  await addBackupAudit('local_export', `json:${memberStore.members.length}`)
  status.value = 'JSON экспорт готов.'
}

async function exportCsvFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  const content = exportMembersToCsv(memberStore.members)
  const fileName = `familyone_members_${new Date().toISOString().slice(0, 10)}.csv`
  downloadText(content, fileName, 'text/csv;charset=utf-8')
  await addBackupAudit('local_export', `csv:${memberStore.members.length}`)
  status.value = 'CSV экспорт готов.'
}

function base64ToBlob(base64: string): Blob {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new Blob([bytes], { type: 'application/pdf' })
}

async function exportPdfFile(): Promise<void> {
  clearMessages()
  await ensureMembers()
  if (!memberStore.members.length) {
    error.value = 'Нет данных для PDF экспорта.'
    return
  }

  pdfBusy.value = true
  startFakeProgress()
  try {
    const membersForPdf = memberStore.members.map((member) => ({
      ...member,
      photoBase64: member.photoUri || ''
    }))

    const response =
      pdfVersion.value === 'v3'
        ? await (async () => {
            if (!canvasState.value.nodes.length) {
              throw new Error('Добавьте хотя бы одну карточку на холст.')
            }
            const bg = pdfV2.use_custom_bg ? buildPdfV2Options().background : undefined
            return generatePdfV3({
              nodes: canvasState.value.nodes as PdfV3Node[],
              edges: (canvasState.value.edges || []) as PdfV3Edge[],
              members: membersForPdf,
              page_format: pdfSettings.format,
              title: pdfSettings.title,
              show_header: pdfV2.show_title_on_page,
              show_footer: pdfV2.show_footer,
              theme: pdfV2.theme,
              font_family: pdfV2.font_family,
              background: bg,
              use_drive: false,
              defaults: canvasState.value.defaults || {}
            })
          })()
        : pdfVersion.value === 'v2'
        ? await generatePdfV2({
            members: membersForPdf,
            page_format: pdfSettings.format,
            use_drive: false,
            theme: pdfV2.theme,
            card_style: pdfV2.card_style,
            layout: pdfV2.layout,
            options: buildPdfV2Options()
          })
        : await generatePdf({
            members: membersForPdf,
            format: pdfSettings.format,
            use_drive: false,
            show_photos: pdfSettings.show_photos,
            show_dates: pdfSettings.show_dates,
            show_patronymic: pdfSettings.show_patronymic,
            title: pdfSettings.title,
            photo_quality: pdfSettings.photo_quality
          })

    if (!response.success) {
      throw new Error(response.error || 'PDF генерация завершилась с ошибкой')
    }

    if (!response.pdf_base64) {
      throw new Error('PDF не вернулся от сервера')
    }

    const fileName = response.filename || `family_tree_${Date.now()}.pdf`
    const pdfBlob = base64ToBlob(response.pdf_base64)
    downloadBlob(pdfBlob, fileName)
    await addBackupAudit('local_export', `pdf:base64:${pdfBlob.size}`)
    status.value = 'PDF экспорт завершен.'
  } catch (reason) {
    error.value = (reason as Error).message
  } finally {
    finishProgress()
    pdfBusy.value = false
  }
}

function buildPdfV2Options(): PdfV2Options {
  const options: PdfV2Options = {
    title: pdfSettings.title,
    show_photos: pdfSettings.show_photos,
    show_dates: pdfSettings.show_dates,
    show_patronymic: pdfSettings.show_patronymic,
    show_social_roles: pdfV2.show_social_roles,
    show_footer: pdfV2.show_footer,
    show_subtitle: pdfV2.show_subtitle,
    accent_color: pdfV2.accent_color,
    photo_shape: pdfV2.photo_shape,
    connection_style: pdfV2.connection_style,
    font_family: pdfV2.font_family,
    show_tree: pdfV2.show_tree,
    show_leaves: pdfV2.show_leaves,
    show_corners: pdfV2.show_corners,
    double_frame: pdfV2.double_frame,
    page_format: pdfSettings.format
  }
  if (pdfV2.use_custom_bg) {
    const bg: PdfV2BackgroundConfig = { type: pdfV2.bg_type }
    if (pdfV2.bg_type === 'color') {
      bg.color = pdfV2.bg_color
    } else if (pdfV2.bg_type === 'gradient') {
      bg.from = pdfV2.bg_from
      bg.to = pdfV2.bg_to
      bg.direction = pdfV2.bg_direction
    } else if (pdfV2.bg_type === 'image') {
      bg.src = pdfV2.bg_image_src
      bg.opacity = pdfV2.bg_opacity
      // Изображение уже подогнано под соотношение страницы в кроппере —
      // используем stretch, чтобы заполнить без искажения.
      bg.fit = 'stretch'
    }
    options.background = bg
  }
  return options
}

async function onBgImagePicked(_event: Event): Promise<void> {
  // legacy — кроппер теперь сам управляет состоянием pdfV2.bg_image_src
}

function applyAccentFromPalette(color: string): void {
  pdfV2.accent_color = color
}

onMounted(async () => {
  try {
    const resp = await fetchPdfV2Options()
    if (resp.success) {
      if (resp.themes?.length) pdfV2Options.themes = resp.themes
      if (resp.card_styles?.length) pdfV2Options.cardStyles = resp.card_styles
      if (resp.layouts?.length) pdfV2Options.layouts = resp.layouts
      if (resp.photo_shapes?.length) pdfV2Options.photoShapes = resp.photo_shapes
      if (resp.connection_styles?.length) pdfV2Options.connectionStyles = resp.connection_styles
      if (resp.font_families?.length) pdfV2Options.fontFamilies = resp.font_families
      if (resp.background_types?.length) pdfV2Options.backgroundTypes = resp.background_types
    }
  } catch {
    // Фолбэк на локальные дефолты — не фатально
  }
})

function openImportPicker(): void {
  importInput.value?.click()
}

async function processImportFile(file: File): Promise<void> {
  clearMessages()
  if (!file.name.endsWith('.json') && file.type !== 'application/json') {
    error.value = 'Поддерживается только JSON файл.'
    return
  }
  importing.value = true
  try {
    const content = await file.text()
    const report = await importMembersFromJsonText(content, importMode.value)
    await memberStore.refresh()
    const action = importMode.value === 'replace' ? 'local_import_replace' : 'local_import_merge'
    await addBackupAudit(action, JSON.stringify(report))
    status.value = `Импорт завершен. Добавлено: ${report.inserted}, пропущено: ${report.skipped}, связей обновлено: ${report.relationsUpdated}.`
  } catch (reason) {
    error.value = `Ошибка импорта: ${(reason as Error).message}`
  } finally {
    importing.value = false
  }
}

async function onImportPicked(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  await processImportFile(file)
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave(): void {
  dragOver.value = false
}

async function onDrop(e: DragEvent): Promise<void> {
  e.preventDefault()
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  await processImportFile(file)
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        icon="import_export"
        title="Экспорт и импорт"
        subtitle="JSON, CSV, PDF через backend и импорт с режимами Merge/Replace"
      />

      <!-- Export section -->
      <article class="app-card block">
        <h2 class="block-title with-icon">
          <AppIcon name="upload_file" :size="20" />
          Экспорт данных
        </h2>
        <div class="export-formats">
          <button class="format-card" @click="exportJsonFile">
            <AppIcon name="list_alt" :size="30" class="format-icon" />
            <span class="format-name">JSON</span>
            <small>Полные данные</small>
          </button>
          <button class="format-card" @click="exportCsvFile">
            <AppIcon name="bar_chart" :size="30" class="format-icon" />
            <span class="format-name">CSV</span>
            <small>Таблица</small>
          </button>
        </div>

        <div class="section-divider"></div>

        <div class="pdf-box">
          <h3 class="with-icon">
            <AppIcon name="description" :size="19" />
            PDF через backend
          </h3>

          <!-- Переключатель версий генератора -->
          <div class="pdf-version-tabs">
            <button
              type="button"
              class="pdf-version-tab"
              :class="{ active: pdfVersion === 'v1' }"
              @click="pdfVersion = 'v1'"
            >
              <AppIcon name="description" :size="16" />
              Стандартный
            </button>
            <button
              type="button"
              class="pdf-version-tab"
              :class="{ active: pdfVersion === 'v2' }"
              @click="pdfVersion = 'v2'"
            >
              <AppIcon name="palette" :size="16" />
              Стилизованный (v2)
            </button>
            <button
              type="button"
              class="pdf-version-tab"
              :class="{ active: pdfVersion === 'v3' }"
              @click="pdfVersion = 'v3'"
            >
              <AppIcon name="dashboard_customize" :size="16" />
              Конструктор (v3)
            </button>
          </div>

          <div class="form-grid">
            <div class="field">
              <label>Формат</label>
              <select v-model="pdfSettings.format">
                <option value="A4_LANDSCAPE">A4 Landscape</option>
                <option value="A3_LANDSCAPE">A3 Landscape</option>
                <option value="A4">A4 Portrait</option>
                <option value="A3">A3 Portrait</option>
              </select>
            </div>
            <div class="field" v-if="pdfVersion === 'v1'">
              <label>Качество фото</label>
              <select v-model="pdfSettings.photo_quality">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>

            <div class="field full-width">
              <label>Заголовок PDF</label>
              <input v-model="pdfSettings.title" type="text" />
            </div>
          </div>

          <div class="toggle-row">
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_photos" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Фото</span>
            </label>
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_dates" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Даты</span>
            </label>
            <label class="toggle-switch">
              <input v-model="pdfSettings.show_patronymic" type="checkbox" />
              <span class="toggle-track"></span>
              <span>Отчество</span>
            </label>
          </div>

          <!-- Блок настроек v2: темы, стили, фон -->
          <div v-if="pdfVersion === 'v2'" class="pdf-v2-box">
            <div class="pdf-v2-section">
              <div class="pdf-v2-section-title">
                <AppIcon name="palette" :size="16" />
                <span>Тема оформления</span>
              </div>
              <div class="chip-grid">
                <button
                  v-for="themeKey in pdfV2Options.themes"
                  :key="themeKey"
                  type="button"
                  class="chip"
                  :class="{ active: pdfV2.theme === themeKey }"
                  @click="pdfV2.theme = themeKey; applyAccentFromPalette(currentAccentPalette[0])"
                >
                  {{ THEME_LABELS[themeKey] || themeKey }}
                </button>
              </div>
            </div>

            <div class="pdf-v2-section">
              <div class="pdf-v2-section-title">
                <AppIcon name="style" :size="16" />
                <span>Стиль карточек</span>
              </div>
              <div class="chip-grid">
                <button
                  v-for="styleKey in pdfV2Options.cardStyles"
                  :key="styleKey"
                  type="button"
                  class="chip"
                  :class="{ active: pdfV2.card_style === styleKey }"
                  @click="pdfV2.card_style = styleKey"
                >
                  {{ CARD_STYLE_LABELS[styleKey] || styleKey }}
                </button>
              </div>
            </div>

            <div class="form-grid">
              <div class="field">
                <label>Раскладка</label>
                <select v-model="pdfV2.layout">
                  <option v-for="k in pdfV2Options.layouts" :key="k" :value="k">
                    {{ LAYOUT_LABELS[k] || k }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Форма фото</label>
                <select v-model="pdfV2.photo_shape">
                  <option v-for="k in pdfV2Options.photoShapes" :key="k" :value="k">
                    {{ PHOTO_SHAPE_LABELS[k] || k }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Тип связей</label>
                <select v-model="pdfV2.connection_style">
                  <option v-for="k in pdfV2Options.connectionStyles" :key="k" :value="k">
                    {{ CONNECTION_LABELS[k] || k }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Шрифт</label>
                <select v-model="pdfV2.font_family">
                  <option v-for="k in pdfV2Options.fontFamilies" :key="k" :value="k">
                    {{ FONT_LABELS[k] || k }}
                  </option>
                </select>
              </div>
            </div>

            <div class="pdf-v2-section">
              <div class="pdf-v2-section-title">
                <AppIcon name="colorize" :size="16" />
                <span>Акцентный цвет</span>
              </div>
              <div class="accent-row">
                <input
                  v-model="pdfV2.accent_color"
                  type="color"
                  class="color-input"
                  aria-label="Акцентный цвет"
                />
                <div class="accent-palette">
                  <button
                    v-for="color in currentAccentPalette"
                    :key="color"
                    type="button"
                    class="accent-swatch"
                    :class="{ active: pdfV2.accent_color === color }"
                    :style="{ background: color }"
                    @click="applyAccentFromPalette(color)"
                    aria-label="Применить цвет"
                  />
                </div>
                <code class="accent-code">{{ pdfV2.accent_color }}</code>
              </div>
            </div>

            <div class="toggle-row">
              <label class="toggle-switch">
                <input v-model="pdfV2.show_social_roles" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Соц. роли</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_subtitle" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Подзаголовок</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_footer" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Футер</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_tree" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Дерево</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_leaves" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Листочки</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_corners" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Уголки</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.double_frame" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Двойная рамка</span>
              </label>
            </div>

            <div class="pdf-v2-section">
              <div class="pdf-v2-section-title">
                <AppIcon name="image" :size="16" />
                <span>Фон</span>
                <label class="toggle-switch compact">
                  <input v-model="pdfV2.use_custom_bg" type="checkbox" />
                  <span class="toggle-track"></span>
                  <span>{{ pdfV2.use_custom_bg ? 'Свой' : 'Из темы' }}</span>
                </label>
              </div>

              <div v-if="pdfV2.use_custom_bg" class="custom-bg">
                <div class="bg-presets">
                  <div class="bg-presets-title">Готовые фоны</div>
                  <div class="bg-presets-grid">
                    <button
                      v-for="p in BG_PRESETS"
                      :key="p.id"
                      type="button"
                      class="bg-preset"
                      :class="{ active: selectedBgPresetId === p.id && pdfV2.bg_type === 'image' }"
                      :title="p.label"
                      @click="applyBgPreset(p)"
                    >
                      <img :src="bgPresetUrl(p)" :alt="p.label" loading="lazy" />
                      <span class="bg-preset-label">{{ p.label }}</span>
                    </button>
                  </div>
                </div>

                <div class="chip-grid">
                  <button
                    v-for="type in pdfV2Options.backgroundTypes"
                    :key="type"
                    type="button"
                    class="chip"
                    :class="{ active: pdfV2.bg_type === type }"
                    @click="pdfV2.bg_type = type as any"
                  >
                    {{ BG_TYPE_LABELS[type] || type }}
                  </button>
                </div>

                <div v-if="pdfV2.bg_type === 'color'" class="form-grid">
                  <div class="field">
                    <label>Цвет фона</label>
                    <input v-model="pdfV2.bg_color" type="color" class="color-input" />
                  </div>
                </div>

                <div v-else-if="pdfV2.bg_type === 'gradient'" class="form-grid">
                  <div class="field">
                    <label>От</label>
                    <input v-model="pdfV2.bg_from" type="color" class="color-input" />
                  </div>
                  <div class="field">
                    <label>К</label>
                    <input v-model="pdfV2.bg_to" type="color" class="color-input" />
                  </div>
                  <div class="field">
                    <label>Направление</label>
                    <select v-model="pdfV2.bg_direction">
                      <option value="vertical">Вертикально</option>
                      <option value="horizontal">Горизонтально</option>
                      <option value="diagonal">Диагональ</option>
                    </select>
                  </div>
                </div>

                <div v-else-if="pdfV2.bg_type === 'image'" class="bg-image-field">
                  <div class="field full-width">
                    <label>Фоновое изображение</label>
                    <ImageBackgroundCropper
                      ref="bgCropperV2"
                      v-model="pdfV2.bg_image_src"
                      :aspect-width="pageAspect.width"
                      :aspect-height="pageAspect.height"
                      :output-width="1800"
                      :quality="0.9"
                    />
                    <small class="help hint-subtle">
                      Соотношение автоматически подстраивается под формат PDF «{{ pdfSettings.format }}».
                      Потяните изображение мышью, колёсиком мыши — масштаб.
                    </small>
                  </div>
                  <div class="field" v-if="pdfV2.bg_image_src">
                    <label>Прозрачность: {{ Math.round(pdfV2.bg_opacity * 100) }}%</label>
                    <input
                      v-model.number="pdfV2.bg_opacity"
                      type="range"
                      min="0.1"
                      max="1"
                      step="0.05"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Блок настроек v3: визуальный конструктор -->
          <div v-if="pdfVersion === 'v3'" class="pdf-v2-box">
            <div class="pdf-v2-section">
              <div class="pdf-v2-section-title">
                <AppIcon name="dashboard_customize" :size="16" />
                <span>Холст конструктора</span>
              </div>
              <PdfCanvasEditor
                v-model="canvasState"
                :members="memberStore.members"
                :page-width="pageAspect.width"
                :page-height="pageAspect.height"
              />
            </div>

            <div class="form-grid">
              <div class="field">
                <label>Тема фона</label>
                <select v-model="pdfV2.theme">
                  <option v-for="k in pdfV2Options.themes" :key="k" :value="k">
                    {{ THEME_LABELS[k] || k }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Шрифт по умолчанию</label>
                <select v-model="pdfV2.font_family">
                  <option v-for="k in pdfV2Options.fontFamilies" :key="k" :value="k">
                    {{ FONT_LABELS[k] || k }}
                  </option>
                </select>
              </div>
            </div>

            <div class="toggle-row">
              <label class="toggle-switch">
                <input v-model="pdfV2.show_title_on_page" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Заголовок в PDF</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.show_footer" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Футер с датой</span>
              </label>
              <label class="toggle-switch">
                <input v-model="pdfV2.use_custom_bg" type="checkbox" />
                <span class="toggle-track"></span>
                <span>Свой фон</span>
              </label>
            </div>

            <div v-if="pdfV2.use_custom_bg" class="custom-bg">
              <div class="bg-presets">
                <div class="bg-presets-title">Готовые фоны</div>
                <div class="bg-presets-grid">
                  <button
                    v-for="p in BG_PRESETS"
                    :key="p.id"
                    type="button"
                    class="bg-preset"
                    :class="{ active: selectedBgPresetId === p.id && pdfV2.bg_type === 'image' }"
                    :title="p.label"
                    @click="applyBgPreset(p)"
                  >
                    <img :src="bgPresetUrl(p)" :alt="p.label" loading="lazy" />
                    <span class="bg-preset-label">{{ p.label }}</span>
                  </button>
                </div>
              </div>

              <div class="chip-grid">
                <button
                  v-for="type in pdfV2Options.backgroundTypes"
                  :key="type"
                  type="button"
                  class="chip"
                  :class="{ active: pdfV2.bg_type === type }"
                  @click="pdfV2.bg_type = type as any"
                >
                  {{ BG_TYPE_LABELS[type] || type }}
                </button>
              </div>

              <div v-if="pdfV2.bg_type === 'color'" class="form-grid">
                <div class="field">
                  <label>Цвет фона</label>
                  <input v-model="pdfV2.bg_color" type="color" class="color-input" />
                </div>
              </div>

              <div v-else-if="pdfV2.bg_type === 'gradient'" class="form-grid">
                <div class="field">
                  <label>От</label>
                  <input v-model="pdfV2.bg_from" type="color" class="color-input" />
                </div>
                <div class="field">
                  <label>К</label>
                  <input v-model="pdfV2.bg_to" type="color" class="color-input" />
                </div>
                <div class="field">
                  <label>Направление</label>
                  <select v-model="pdfV2.bg_direction">
                    <option value="vertical">Вертикально</option>
                    <option value="horizontal">Горизонтально</option>
                    <option value="diagonal">Диагональ</option>
                  </select>
                </div>
              </div>

              <div v-else-if="pdfV2.bg_type === 'image'" class="bg-image-field">
                <div class="field full-width">
                  <label>Фоновое изображение</label>
                  <ImageBackgroundCropper
                    ref="bgCropperV3"
                    v-model="pdfV2.bg_image_src"
                    :aspect-width="pageAspect.width"
                    :aspect-height="pageAspect.height"
                    :output-width="1800"
                    :quality="0.9"
                  />
                </div>
                <div class="field" v-if="pdfV2.bg_image_src">
                  <label>Прозрачность: {{ Math.round(pdfV2.bg_opacity * 100) }}%</label>
                  <input
                    v-model.number="pdfV2.bg_opacity"
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="btn-row">
            <button class="btn-action primary" :disabled="pdfBusy" @click="exportPdfFile">
              <AppIcon :name="pdfBusy ? 'hourglass_top' : 'description'" :size="18" />
              {{ pdfBusy ? 'Генерация PDF...' : pdfVersion === 'v3' ? 'Экспорт PDF (конструктор)' : pdfVersion === 'v2' ? 'Экспорт PDF (стиль)' : 'Экспорт PDF' }}
            </button>
          </div>

          <Transition name="fade-progress">
            <div v-if="pdfBusy || pdfProgress > 0" class="pdf-progress-wrap">
              <div class="progress-bar">
                <div
                  class="progress-bar-fill"
                  :class="{ 'progress-pulse': pdfBusy && pdfProgress < 95 }"
                  :style="{ width: Math.min(pdfProgress, 100) + '%' }"
                />
              </div>
              <span class="pdf-progress-label">
                {{ pdfProgress >= 100 ? 'Готово!' : `${Math.round(pdfProgress)}%` }}
              </span>
            </div>
          </Transition>
        </div>
      </article>

      <!-- Import section -->
      <article class="app-card block">
        <h2 class="block-title with-icon">
          <AppIcon name="download" :size="20" />
          Импорт JSON
        </h2>

        <div class="import-row">
          <div class="field mode-field">
            <label>Режим импорта</label>
            <select v-model="importMode">
              <option value="merge">Merge (по умолчанию)</option>
              <option value="replace">Replace (полная замена)</option>
            </select>
          </div>
        </div>

        <div
          class="drop-zone"
          :class="{ active: dragOver || importing }"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
          @click="openImportPicker"
        >
          <AppIcon
            :name="importing ? 'hourglass_top' : 'upload_file'"
            :size="40"
            class="drop-zone-icon"
            :class="{ 'spin-slow': importing }"
          />
          <p class="drop-zone-label">
            <template v-if="importing">Импорт...</template>
            <template v-else>
              Перетащите JSON файл сюда
              <span class="drop-zone-or">или нажмите для выбора</span>
            </template>
          </p>
        </div>

        <input
          ref="importInput"
          type="file"
          accept="application/json,.json"
          style="display: none"
          @change="onImportPicked"
        />
      </article>

      <!-- Status -->
      <article class="app-card block" v-if="status || error">
        <p v-if="status" class="status-success with-icon">
          <AppIcon name="check_circle" :size="18" />
          {{ status }}
        </p>
        <p v-if="error" class="error-msg with-icon">
          <AppIcon name="error" :size="18" />
          {{ error }}
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.block {
  padding: 20px;
}

.block + .block {
  margin-top: 14px;
}

.block-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 16px;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* Format cards */
.export-formats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.format-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 28px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  transition: all var(--transition-normal);
  font-family: var(--font-sans);
  min-width: 120px;
}

.format-card:hover {
  border-color: rgba(124, 92, 252, 0.4);
  background: rgba(124, 92, 252, 0.06);
  transform: translateY(-3px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.format-icon {
  font-size: 2rem;
}

.format-name {
  font-weight: 700;
  font-size: 1rem;
}

.format-card small {
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

/* PDF box */
.pdf-box {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pdf-box h3 {
  font-size: 1rem;
  font-weight: 600;
}

.toggle-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.full-width {
  grid-column: 1 / -1;
}

/* Import row */
.import-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.mode-field {
  max-width: 360px;
  flex: 1;
}

.status-success {
  color: var(--color-success);
  font-size: 0.9rem;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.9rem;
}

/* PDF progress */
.pdf-progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.pdf-progress-label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  min-width: 36px;
  text-align: right;
  white-space: nowrap;
}

@keyframes progress-pulse-anim {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.progress-pulse {
  animation: progress-pulse-anim 1.2s ease-in-out infinite;
}

.fade-progress-enter-active,
.fade-progress-leave-active {
  transition: opacity 0.3s;
}
.fade-progress-enter-from,
.fade-progress-leave-to {
  opacity: 0;
}

/* Drop zone customization */
.drop-zone-label {
  margin: 0;
  font-size: 0.95rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.drop-zone-or {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

@keyframes spin-slow-anim {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spin-slow {
  animation: spin-slow-anim 1.8s linear infinite;
  display: inline-block;
}

/* ============ PDF v2 UI ============ */

.pdf-version-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  padding: 4px;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
}

.pdf-version-tab {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  font-weight: 500;
  font-size: 0.9rem;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}

.pdf-version-tab:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.pdf-version-tab.active {
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent);
  box-shadow: var(--shadow-glow);
}

.pdf-v2-box {
  margin-top: 18px;
  padding: 16px;
  border: 1px dashed var(--color-glass-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pdf-v2-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pdf-v2-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary);
}

.pdf-v2-section-title .toggle-switch.compact {
  margin-left: auto;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: none;
  letter-spacing: normal;
}

.chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  padding: 8px 14px;
  border: 1px solid var(--color-glass-border);
  border-radius: 999px;
  background: var(--input-bg);
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast), transform 0.1s;
}

.chip:hover {
  border-color: var(--color-accent);
  color: var(--color-text);
  background: var(--input-hover-bg);
  transform: translateY(-1px);
}

.chip.active {
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent);
  box-shadow: var(--shadow-glow);
}

.accent-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.color-input {
  width: 48px;
  height: 36px;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  cursor: pointer;
  padding: 2px;
}

.accent-palette {
  display: flex;
  gap: 6px;
}

.accent-swatch {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid var(--color-glass-border);
  cursor: pointer;
  padding: 0;
  transition: transform 0.12s, border-color 0.12s;
}

.accent-swatch:hover {
  transform: scale(1.1);
}

.accent-swatch.active {
  border-color: var(--color-text);
  transform: scale(1.15);
  box-shadow: var(--shadow-glow);
}

.accent-code {
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}

.custom-bg {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--color-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-glass-border);
}

.bg-presets {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bg-presets-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.bg-presets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
}

.bg-preset {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 4px;
  background: var(--input-bg);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  overflow: hidden;
  transition:
    border-color var(--transition-fast),
    transform var(--transition-fast),
    box-shadow var(--transition-fast);
}

.bg-preset img {
  width: 100%;
  max-height: 120px;
  object-fit: contain;
  border-radius: calc(var(--radius-sm) - 2px);
  display: block;
  background: var(--color-bg-alt);
}

.bg-preset-label {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bg-preset:hover {
  border-color: var(--color-accent);
  transform: translateY(-1px);
}

.bg-preset.active {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-accent);
}

.bg-preset.active .bg-preset-label {
  color: var(--color-text);
  font-weight: 600;
}

.bg-image-field {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bg-image-field .help {
  color: var(--color-text-muted);
  font-size: 0.78rem;
  margin-top: 4px;
}

.bg-image-field .hint-subtle {
  display: block;
  margin-top: 8px;
  line-height: 1.4;
}

@media (max-width: 640px) {
  .pdf-version-tabs {
    flex-direction: column;
  }
  .accent-row {
    gap: 8px;
  }
}
</style>
