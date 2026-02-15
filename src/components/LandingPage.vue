<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import logoIcon from '@/assets/icon.png'

const apiStatus = ref(null)
const apiLatency = ref(null)
const memberCount = ref(0)
const faceRecOk = ref(false)
const pdfGenOk = ref(false)
const logs = ref([])
const maxLogs = 40
let pollTimer = null
let checkCount = ref(0)
const shownEventKeys = new Set()

function addLog(icon, message, type = 'info') {
  const now = new Date()
  const ts = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute:'2-digit', second:'2-digit' })
  logs.value.unshift({ id: Date.now() + Math.random(), ts, icon, message, type })
  if (logs.value.length > maxLogs) logs.value.pop()
}

async function checkHealth() {
  const start = performance.now()
  checkCount.value++
  addLog('📡', 'Отправляем запрос на проверку сервера...', 'sending')
  try {
    const res = await fetch('/api/health')
    const elapsed = Math.round(performance.now() - start)
    apiLatency.value = elapsed
    if (res.ok) {
      const data = await res.json()
      apiStatus.value = 'online'
      memberCount.value = data.members_count || 0
      faceRecOk.value = data.face_recognition
      pdfGenOk.value = data.pdf_generation
      addLog('✅', `Сервер работает! Время ответа: ${elapsed}мс`, 'success')
      if (data.face_recognition) {
        addLog('🧠', 'Модуль распознавания лиц — активен', 'success')
      }
      if (data.pdf_generation) {
        addLog('📄', 'Модуль генерации PDF — активен', 'success')
      }
      addLog('👥', `Зарегистрировано лиц в базе: ${data.members_count}`, 'info')

      // Отображаем серверные события (PDF генерация и т.д.)
      if (data.recent_events && data.recent_events.length > 0) {
        data.recent_events.forEach(ev => {
          const key = `${ev.ts}_${ev.message}`
          if (!shownEventKeys.has(key)) {
            shownEventKeys.add(key)
            addLog(ev.icon || '🔔', ev.message, ev.type || 'info')
          }
        })
      }
    } else {
      apiStatus.value = 'error'
      addLog('⚠️', `Сервер ответил с ошибкой (код ${res.status}). Время: ${elapsed}мс`, 'error')
    }
  } catch (e) {
    apiStatus.value = 'offline'
    addLog('❌', 'Не удалось подключиться к серверу — проверьте, запущен ли он', 'error')
  }
}

async function testListFaces() {
  const start = performance.now()
  addLog('🔍', 'Запрашиваем список зарегистрированных лиц...', 'sending')
  try {
    const res = await fetch('/api/list_faces')
    const elapsed = Math.round(performance.now() - start)
    if (res.ok) {
      const data = await res.json()
      const count = data.count || 0
      addLog('✅', `Получен ответ за ${elapsed}мс`, 'success')
      if (count === 0) {
        addLog('📋', 'В базе пока нет зарегистрированных лиц', 'info')
      } else {
        addLog('📋', `Найдено лиц: ${count}`, 'info')
        const faces = data.faces || []
        faces.slice(0, 5).forEach(f => {
          addLog('👤', `${f.member_name} (ID: ${f.member_id})`, 'info')
        })
        if (faces.length > 5) {
          addLog('➕', `... и ещё ${faces.length - 5}`, 'info')
        }
      }
    } else {
      addLog('⚠️', `Ошибка при получении списка (код ${res.status})`, 'error')
    }
  } catch (e) {
    addLog('❌', 'Не удалось получить список — сервер недоступен', 'error')
  }
}

onMounted(() => {
  addLog('🚀', 'Страница загружена — начинаем мониторинг сервера', 'info')
  checkHealth()
  pollTimer = setInterval(checkHealth, 15000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

const features = [
  { icon: 'face', title: 'Распознавание лиц', desc: 'Технология face_recognition идентифицирует членов семьи на фотографиях с точностью до 98%.' },
  { icon: 'pdf', title: 'Генерация PDF', desc: 'Красивое семейное древо в формате PDF с помощью ReportLab — готово к печати.' },
  { icon: 'tree', title: 'Семейные связи', desc: 'Визуализация поколений, связей и родственных отношений в удобном интерфейсе.' },
  { icon: 'cloud', title: 'Облачный сервер', desc: 'API сервер с Cloudflare Tunnel обеспечивает доступ из любой точки мира.' },
]

const steps = [
  { num: '01', title: 'Добавьте членов семьи', desc: 'Создайте профили с фото, датами и ролями в приложении.' },
  { num: '02', title: 'Распознайте лица', desc: 'Загрузите фото — сервер определит, кто на нём изображён.' },
  { num: '03', title: 'Экспортируйте древо', desc: 'Получите красивый PDF-документ с вашим семейным древом.' },
]

const techStack = [
  { name: 'Android / Kotlin', color: '#a4c639' },
  { name: 'Python / Flask', color: '#3776ab' },
  { name: 'Vue.js 3', color: '#42b883' },
  { name: 'face_recognition', color: '#f472b6' },
  { name: 'ReportLab', color: '#fbbf24' },
  { name: 'Cloudflare', color: '#f6821f' },
  { name: 'Caddy Server', color: '#22d3ee' },
  { name: 'OkHttp', color: '#a78bfa' },
]
</script>

<template>
  <div class="landing">
    <!-- BG particles -->
    <div class="bg-effects">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>

    <!-- NAV -->
    <nav class="navbar animate-in">
      <div class="container nav-inner">
        <div class="nav-brand">
          <img :src="logoIcon" alt="FamilyOne Logo" class="nav-logo" />
          <span>FamilyOne</span>
        </div>
        <div class="nav-links">
          <a href="#features">Возможности</a>
          <a href="#how">Как работает</a>
          <a href="#tech">Технологии</a>
          <a href="#logs">Сервер</a>
        </div>
      </div>
    </nav>

    <!-- HERO -->
    <section class="hero">
      <div class="container hero-inner">
        <div class="hero-content animate-in delay-1">
          <span class="hero-badge">🎓 Дипломный проект 2026</span>
          <h1 class="hero-title">
            <span class="title-line">Семейное</span>
            <span class="title-accent">Древо</span>
          </h1>
          <p class="hero-subtitle">
            Мобильное Android-приложение для создания семейного древа
            с&nbsp;распознаванием лиц на&nbsp;базе нейросетей и генерацией
            красивых PDF-документов.
          </p>
          <div class="hero-actions">
            <a href="#features" class="btn btn-primary">Узнать подробнее</a>
            <a href="#logs" class="btn btn-outline">Статус сервера</a>
          </div>
          <div class="hero-stats">
            <div class="stat">
              <span class="stat-value">AI</span>
              <span class="stat-label">Распознавание лиц</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat">
              <span class="stat-value">PDF</span>
              <span class="stat-label">Экспорт древа</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat">
              <span class="stat-value">24/7</span>
              <span class="stat-label">Облачный API</span>
            </div>
          </div>
        </div>
        <div class="hero-visual animate-in delay-3">
          <div class="phone-mockup">
            <div class="phone-screen">
              <div class="mock-header">
                <div class="mock-avatar"></div>
                <div class="mock-title-block">
                  <div class="mock-bar w60"></div>
                  <div class="mock-bar w40 light"></div>
                </div>
              </div>
              <div class="mock-tree">
                <div class="mock-node top"></div>
                <div class="mock-line-v"></div>
                <div class="mock-row">
                  <div class="mock-node"></div>
                  <div class="mock-line-h"></div>
                  <div class="mock-node"></div>
                </div>
                <div class="mock-line-v short"></div>
                <div class="mock-row">
                  <div class="mock-node small"></div>
                  <div class="mock-node small"></div>
                  <div class="mock-node small"></div>
                </div>
              </div>
              <div class="mock-bottom">
                <div class="mock-btn"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- FEATURES -->
    <section id="features" class="section features-section">
      <div class="container">
        <h2 class="section-title animate-in">Возможности</h2>
        <p class="section-subtitle animate-in delay-1">Всё, что нужно для вашего семейного древа — в одном приложении</p>
        <div class="features-grid">
          <div v-for="(f, i) in features" :key="i" class="feature-card animate-in" :class="'delay-' + (i + 2)">
            <div class="feature-icon-wrap">
              <!-- Face -->
              <svg v-if="f.icon === 'face'" viewBox="0 0 48 48" fill="none" class="feature-icon"><circle cx="24" cy="20" r="10" stroke="currentColor" stroke-width="2"/><circle cx="20" cy="18" r="1.5" fill="currentColor"/><circle cx="28" cy="18" r="1.5" fill="currentColor"/><path d="M20 23c1 2 5.5 2 7 0" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><rect x="14" y="14" width="20" height="18" rx="3" stroke="currentColor" stroke-width="1" opacity=".3" stroke-dasharray="3 3"/><path d="M12 36h24" stroke="currentColor" stroke-width="1.5" opacity=".4"/></svg>
              <!-- PDF -->
              <svg v-if="f.icon === 'pdf'" viewBox="0 0 48 48" fill="none" class="feature-icon"><rect x="10" y="6" width="22" height="30" rx="3" stroke="currentColor" stroke-width="2"/><path d="M16 14h10M16 19h12M16 24h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity=".6"/><rect x="26" y="24" width="12" height="16" rx="2" fill="var(--color-accent)" opacity=".15" stroke="currentColor" stroke-width="1.5"/><text x="29" y="35" fill="currentColor" font-size="7" font-weight="700">PDF</text></svg>
              <!-- Tree -->
              <svg v-if="f.icon === 'tree'" viewBox="0 0 48 48" fill="none" class="feature-icon"><circle cx="24" cy="10" r="4" stroke="currentColor" stroke-width="2"/><line x1="24" y1="14" x2="24" y2="22" stroke="currentColor" stroke-width="1.5"/><line x1="14" y1="22" x2="34" y2="22" stroke="currentColor" stroke-width="1.5"/><circle cx="14" cy="28" r="3.5" stroke="currentColor" stroke-width="1.5"/><circle cx="34" cy="28" r="3.5" stroke="currentColor" stroke-width="1.5"/><line x1="14" y1="22" x2="14" y2="24.5" stroke="currentColor" stroke-width="1.5"/><line x1="34" y1="22" x2="34" y2="24.5" stroke="currentColor" stroke-width="1.5"/><circle cx="8" cy="40" r="2.5" stroke="currentColor" stroke-width="1" opacity=".5"/><circle cx="20" cy="40" r="2.5" stroke="currentColor" stroke-width="1" opacity=".5"/><line x1="14" y1="31.5" x2="14" y2="34" stroke="currentColor" stroke-width="1" opacity=".5"/><line x1="8" y1="34" x2="20" y2="34" stroke="currentColor" stroke-width="1" opacity=".5"/><line x1="8" y1="34" x2="8" y2="37.5" stroke="currentColor" stroke-width="1" opacity=".5"/><line x1="20" y1="34" x2="20" y2="37.5" stroke="currentColor" stroke-width="1" opacity=".5"/></svg>
              <!-- Cloud -->
              <svg v-if="f.icon === 'cloud'" viewBox="0 0 48 48" fill="none" class="feature-icon"><path d="M14 32h20a8 8 0 10-3-15.4A10 10 0 0014 22a7 7 0 000 10z" stroke="currentColor" stroke-width="2"/><path d="M20 28v-6m4 6v-8m4 8v-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity=".5"/></svg>
            </div>
            <h3>{{ f.title }}</h3>
            <p>{{ f.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- HOW IT WORKS -->
    <section id="how" class="section how-section">
      <div class="container">
        <h2 class="section-title animate-in">Как это работает</h2>
        <div class="steps-row">
          <div v-for="(s, i) in steps" :key="i" class="step-card animate-in" :class="'delay-' + (i + 2)">
            <span class="step-num">{{ s.num }}</span>
            <h3>{{ s.title }}</h3>
            <p>{{ s.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- TECH STACK -->
    <section id="tech" class="section tech-section">
      <div class="container">
        <h2 class="section-title animate-in">Стек технологий</h2>
        <p class="section-subtitle animate-in delay-1">Проект построен на современных и надёжных инструментах</p>
        <div class="tech-badges animate-in delay-2">
          <span v-for="(t, i) in techStack" :key="i" class="tech-badge" :style="{ '--badge-color': t.color }">
            <span class="badge-dot" :style="{ background: t.color }"></span>
            {{ t.name }}
          </span>
        </div>
      </div>
    </section>

    <!-- API STATUS & LOGS -->
    <section id="logs" class="section logs-section">
      <div class="container">
        <h2 class="section-title animate-in">Сервер API</h2>
        <p class="section-subtitle animate-in delay-1">Мониторинг сервера в реальном времени</p>

        <div class="api-panel animate-in delay-2">
          <!-- Status bar -->
          <div class="api-status-bar">
            <div class="status-indicator" :class="apiStatus || 'loading'">
              <span class="status-dot"></span>
              <span v-if="apiStatus === 'online'">Сервер онлайн</span>
              <span v-else-if="apiStatus === 'error'">Ошибка сервера</span>
              <span v-else-if="apiStatus === 'offline'">Сервер недоступен</span>
              <span v-else>Проверка...</span>
            </div>
            <div class="status-meta">
              <span v-if="apiLatency" class="latency">{{ apiLatency }}ms</span>
              <span class="members-count">Лиц в базе: {{ memberCount }}</span>
            </div>
          </div>

          <!-- Quick actions -->
          <div class="api-actions">
            <button class="action-btn" @click="checkHealth">
              <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path d="M4 2a1 1 0 011 1v2.1c1.5-1.6 3.5-2.6 5.8-2.6 4.4 0 8 3.6 8 8s-3.6 8-8 8-8-3.6-8-8a1 1 0 012 0c0 3.3 2.7 6 6 6s6-2.7 6-6-2.7-6-6-6c-1.8 0-3.4.8-4.5 2H8a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1z"/></svg>
              Проверить сервер
            </button>
            <button class="action-btn" @click="testListFaces">
              <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path d="M9 6a3 3 0 110 6 3 3 0 010-6zm0-2a5 5 0 100 10A5 5 0 009 4zm8 12a1 1 0 01-2 0c0-2.8-2.2-4-5-4s-5 1.2-5 4a1 1 0 01-2 0c0-4.2 3.6-6 7-6s7 1.8 7 6z"/></svg>
              Список лиц в базе
            </button>
          </div>

          <!-- Capabilities -->
          <div class="api-caps">
            <div class="cap" :class="{ active: faceRecOk }">
              <span class="cap-dot"></span>
              Распознавание лиц
            </div>
            <div class="cap" :class="{ active: pdfGenOk }">
              <span class="cap-dot"></span>
              Генерация PDF
            </div>
            <div class="cap info">
              <span>Проверок: {{ checkCount }}</span>
            </div>
          </div>

          <!-- Log feed -->
          <div class="log-feed">
            <div class="log-header">
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h6a1 1 0 110 2H4a1 1 0 01-1-1z"/></svg>
              Журнал событий
              <span class="log-count">{{ logs.length }}</span>
            </div>
            <div class="log-entries" ref="logContainer">
              <TransitionGroup name="log-item">
                <div v-for="log in logs" :key="log.id" class="log-entry" :class="'log-' + log.type">
                  <span class="log-time">{{ log.ts }}</span>
                  <span class="log-icon">{{ log.icon }}</span>
                  <span class="log-msg">{{ log.message }}</span>
                </div>
              </TransitionGroup>
              <div v-if="logs.length === 0" class="log-empty">
                ⏳ Ожидание событий...
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- FOOTER -->
    <footer class="footer">
      <div class="container footer-inner">
        <div class="footer-brand">
          <img :src="logoIcon" alt="FamilyOne Logo" class="nav-logo" />
          <span>FamilyOne — Семейное Древо</span>
        </div>
        <p class="footer-copy">© 2026 Дипломный проект. Все права защищены.</p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* ==== LAYOUT ==== */
.landing {
  position: relative;
}

/* ---- BG ---- */
.bg-effects {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 0;
  overflow: hidden;
}
.orb {
  position: absolute; border-radius: 50%; filter: blur(100px);
}
.orb-1 {
  width: 600px; height: 600px;
  background: rgba(124, 92, 252, 0.12);
  top: -200px; left: -100px;
  animation: float 20s ease-in-out infinite;
}
.orb-2 {
  width: 500px; height: 500px;
  background: rgba(244, 114, 182, 0.08);
  bottom: -150px; right: -100px;
  animation: float 25s ease-in-out infinite reverse;
}
.orb-3 {
  width: 300px; height: 300px;
  background: rgba(34, 211, 238, 0.06);
  top: 50%; left: 50%;
  animation: float 18s ease-in-out infinite 3s;
}

/* ---- NAV ---- */
.navbar {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: rgba(11, 14, 23, 0.7);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--color-glass-border);
}
.nav-inner {
  display: flex; align-items: center; justify-content: space-between;
  height: 64px;
}
.nav-brand {
  display: flex; align-items: center; gap: 10px;
  font-weight: 600; font-size: 1.1rem;
  color: var(--color-text);
}
.nav-logo { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; }
.nav-links { display: flex; gap: 28px; }
.nav-links a {
  color: var(--color-text-secondary); font-size: 0.88rem; font-weight: 500;
  text-decoration: none; transition: color 0.3s;
}
.nav-links a:hover { color: var(--color-text); }

/* ---- HERO ---- */
.hero {
  position: relative; z-index: 1;
  min-height: 100vh;
  display: flex; align-items: center;
  padding: 100px 0 60px;
  background: var(--gradient-bg);
}
.hero-inner {
  display: grid; grid-template-columns: 1fr 1fr; gap: 60px; align-items: center;
}
.hero-badge {
  display: inline-block;
  padding: 6px 16px; border-radius: 999px;
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  font-size: 0.82rem; color: var(--color-accent-light);
  font-weight: 500; margin-bottom: 20px;
}
.hero-title {
  font-family: var(--font-display);
  font-size: 4rem; line-height: 1.1; font-weight: 700;
  margin-bottom: 20px;
}
.title-line { display: block; color: var(--color-text); }
.title-accent {
  display: block;
  background: var(--gradient-accent);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-subtitle {
  font-size: 1.12rem; line-height: 1.8;
  color: var(--color-text-secondary);
  max-width: 520px; margin-bottom: 32px;
}
.hero-actions { display: flex; gap: 14px; margin-bottom: 48px; }

.btn {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 13px 28px; border-radius: var(--radius-md);
  font-weight: 600; font-size: 0.92rem; text-decoration: none;
  cursor: pointer; transition: all 0.3s ease; border: none;
}
.btn-primary {
  background: var(--gradient-accent); color: #fff;
  box-shadow: 0 4px 20px rgba(124, 92, 252, 0.35);
}
.btn-primary:hover {
  background: var(--gradient-accent-hover);
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(124, 92, 252, 0.5);
}
.btn-outline {
  background: transparent; color: var(--color-text);
  border: 1px solid var(--color-glass-border);
}
.btn-outline:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-accent);
}

.hero-stats {
  display: flex; align-items: center; gap: 24px;
}
.stat { text-align: center; }
.stat-value {
  display: block; font-weight: 700; font-size: 1.3rem;
  background: var(--gradient-accent);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.stat-label { font-size: 0.78rem; color: var(--color-text-muted); }
.stat-divider { width: 1px; height: 36px; background: var(--color-glass-border); }

/* Phone Mock */
.hero-visual { display: flex; justify-content: center; }
.phone-mockup {
  width: 260px; height: 460px;
  background: var(--color-bg-alt);
  border-radius: 32px;
  border: 2px solid var(--color-glass-border);
  padding: 16px;
  box-shadow: var(--shadow-glow), var(--shadow-card);
  animation: float 8s ease-in-out infinite;
}
.phone-screen {
  height: 100%; border-radius: 20px;
  background: rgba(255,255,255,0.03);
  padding: 20px 16px;
  display: flex; flex-direction: column; gap: 20px;
  overflow: hidden;
}
.mock-header { display: flex; align-items: center; gap: 12px; }
.mock-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--gradient-accent); opacity: 0.6;
}
.mock-title-block { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.mock-bar {
  height: 8px; border-radius: 4px;
  background: rgba(255,255,255,0.12);
}
.mock-bar.w60 { width: 60%; }
.mock-bar.w40 { width: 40%; }
.mock-bar.light { opacity: 0.5; }

.mock-tree {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 6px;
}
.mock-node {
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--gradient-accent); opacity: 0.5;
}
.mock-node.top { opacity: 0.7; }
.mock-node.small { width: 26px; height: 26px; opacity: 0.35; }
.mock-line-v { width: 2px; height: 18px; background: var(--color-accent); opacity: 0.3; }
.mock-line-v.short { height: 12px; }
.mock-line-h { width: 40px; height: 2px; background: var(--color-accent); opacity: 0.3; }
.mock-row { display: flex; align-items: center; gap: 8px; }
.mock-bottom {
  display: flex; justify-content: center;
}
.mock-btn {
  width: 80%; height: 36px; border-radius: 10px;
  background: var(--gradient-accent); opacity: 0.25;
}

/* ---- SECTIONS ---- */
.section {
  position: relative; z-index: 1;
  padding: var(--section-gap) 0;
}
.section-title {
  font-family: var(--font-display);
  font-size: 2.5rem; font-weight: 700; text-align: center;
  margin-bottom: 12px;
}
.section-subtitle {
  text-align: center; color: var(--color-text-secondary);
  font-size: 1.05rem; margin-bottom: 50px;
}

/* ---- FEATURES ---- */
.features-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px;
}
.feature-card {
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-lg);
  padding: 32px 24px;
  transition: all 0.35s ease;
}
.feature-card:hover {
  background: var(--color-surface-hover);
  border-color: rgba(124, 92, 252, 0.3);
  transform: translateY(-6px);
  box-shadow: var(--shadow-glow);
}
.feature-icon-wrap {
  width: 56px; height: 56px;
  border-radius: var(--radius-md);
  background: rgba(124, 92, 252, 0.12);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 18px;
}
.feature-icon { width: 32px; height: 32px; color: var(--color-accent-light); }
.feature-card h3 {
  font-size: 1.1rem; font-weight: 600; margin-bottom: 8px;
}
.feature-card p {
  font-size: 0.88rem; line-height: 1.6; color: var(--color-text-secondary);
}

/* ---- HOW ---- */
.how-section { background: var(--gradient-bg); }
.steps-row {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 30px;
}
.step-card {
  text-align: center;
  padding: 40px 28px;
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-lg);
  transition: all 0.35s ease;
}
.step-card:hover {
  border-color: rgba(124, 92, 252, 0.3);
  transform: translateY(-4px);
}
.step-num {
  display: inline-block;
  font-size: 2.5rem; font-weight: 800;
  background: var(--gradient-accent);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 14px; line-height: 1;
}
.step-card h3 { font-size: 1.15rem; font-weight: 600; margin-bottom: 10px; }
.step-card p { font-size: 0.88rem; color: var(--color-text-secondary); line-height: 1.6; }

/* ---- TECH ---- */
.tech-badges {
  display: flex; flex-wrap: wrap; justify-content: center; gap: 12px;
}
.tech-badge {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 20px; border-radius: 999px;
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  font-size: 0.88rem; font-weight: 500;
  transition: all 0.3s;
}
.tech-badge:hover {
  border-color: var(--badge-color);
  box-shadow: 0 0 20px color-mix(in srgb, var(--badge-color) 25%, transparent);
}
.badge-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

/* ---- LOGS ---- */
.api-panel {
  background: var(--color-bg-alt);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-card);
}
.api-status-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 28px;
  border-bottom: 1px solid var(--color-glass-border);
}
.status-indicator {
  display: flex; align-items: center; gap: 10px;
  font-weight: 600; font-size: 1rem;
}
.status-dot {
  width: 10px; height: 10px; border-radius: 50%;
  animation: blink-dot 2s ease infinite;
}
.status-indicator.online .status-dot { background: var(--color-success); box-shadow: 0 0 10px var(--color-success); }
.status-indicator.online { color: var(--color-success); }
.status-indicator.error .status-dot { background: var(--color-warning); }
.status-indicator.error { color: var(--color-warning); }
.status-indicator.offline .status-dot { background: var(--color-error); }
.status-indicator.offline { color: var(--color-error); }
.status-indicator.loading .status-dot { background: var(--color-text-muted); }
.status-indicator.loading { color: var(--color-text-muted); }

.status-meta {
  display: flex; gap: 20px; font-size: 0.82rem; color: var(--color-text-secondary);
}
.latency {
  padding: 3px 10px; border-radius: 6px;
  background: rgba(52, 211, 153, 0.1); color: var(--color-success);
  font-weight: 500; font-variant-numeric: tabular-nums;
}

.api-actions {
  display: flex; gap: 10px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--color-glass-border);
}
.action-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--radius-sm);
  background: var(--color-surface);
  border: 1px solid var(--color-glass-border);
  color: var(--color-text-secondary);
  font-size: 0.82rem; font-weight: 500;
  cursor: pointer; transition: all 0.25s;
  font-family: var(--font-sans);
}
.action-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
  border-color: var(--color-accent);
}

.api-caps {
  display: flex; gap: 16px;
  padding: 12px 28px;
  border-bottom: 1px solid var(--color-glass-border);
}
.cap {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.82rem; color: var(--color-text-muted);
}
.cap.active { color: var(--color-success); }
.cap.info { margin-left: auto; color: var(--color-text-muted); font-size: 0.78rem; }
.cap-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--color-text-muted);
}
.cap.active .cap-dot {
  background: var(--color-success);
  box-shadow: 0 0 8px var(--color-success);
  animation: blink-dot 2s ease infinite;
}

.log-feed {
  font-size: 0.85rem;
}
.log-header {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 28px;
  color: var(--color-text-muted);
  font-size: 0.75rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.log-count {
  padding: 1px 8px; border-radius: 10px;
  background: var(--color-surface);
  font-size: 0.7rem;
}
.log-entries {
  max-height: 380px; overflow-y: auto;
  padding: 8px 0;
}
.log-entries::-webkit-scrollbar { width: 6px; }
.log-entries::-webkit-scrollbar-track { background: transparent; }
.log-entries::-webkit-scrollbar-thumb { background: var(--color-glass-border); border-radius: 3px; }

.log-entry {
  display: flex; align-items: baseline; gap: 10px;
  padding: 6px 28px;
  transition: background 0.2s;
}
.log-entry:hover { background: rgba(255,255,255,0.02); }
.log-time {
  color: var(--color-text-muted); flex-shrink: 0; white-space: nowrap;
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}
.log-icon { flex-shrink: 0; font-size: 0.9rem; }
.log-msg { color: var(--color-text-secondary); }
.log-entry.log-success .log-msg { color: var(--color-success); }
.log-entry.log-error .log-msg { color: var(--color-error); }
.log-entry.log-sending .log-msg { color: var(--color-accent-light); }
.log-empty {
  padding: 30px 28px; text-align: center;
  color: var(--color-text-muted);
}

/* TransitionGroup */
.log-item-enter-active { animation: slide-in-log 0.3s ease-out; }
.log-item-leave-active { transition: opacity 0.2s; }
.log-item-leave-to { opacity: 0; }

/* ---- FOOTER ---- */
.footer {
  position: relative; z-index: 1;
  padding: 40px 0;
  border-top: 1px solid var(--color-glass-border);
}
.footer-inner {
  display: flex; align-items: center; justify-content: space-between;
}
.footer-brand {
  display: flex; align-items: center; gap: 10px;
  font-weight: 600; font-size: 0.95rem;
  color: var(--color-text-secondary);
}
.footer-brand .nav-logo { width: 22px; height: 22px; color: var(--color-accent); }
.footer-copy { font-size: 0.82rem; color: var(--color-text-muted); }

/* ==== RESPONSIVE ==== */
@media (max-width: 1024px) {
  .features-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .nav-links { display: none; }
  .hero-inner { grid-template-columns: 1fr; text-align: center; }
  .hero-title { font-size: 2.8rem; }
  .hero-subtitle { margin: 0 auto 24px; }
  .hero-actions { justify-content: center; }
  .hero-stats { justify-content: center; }
  .hero-visual { margin-top: 20px; }
  .phone-mockup { width: 200px; height: 360px; }
  .features-grid { grid-template-columns: 1fr; }
  .steps-row { grid-template-columns: 1fr; }
  .api-status-bar { flex-direction: column; gap: 12px; align-items: flex-start; }
  .footer-inner { flex-direction: column; gap: 12px; text-align: center; }
  .section-title { font-size: 2rem; }
}
</style>
