# Семейное древо: web + backend + Windows setup

Этот репозиторий содержит веб-часть проекта, Python backend и Windows-скрипты для локального запуска и настройки VPS/ПК.

## Что есть в репозитории

- `src/` — web-приложение на Vue 3
- `backend/` — API на Python
- `scripts/` — PowerShell-скрипты для запуска, FRP и сборки утилит
- `public/` — статические файлы, иконки, APK
- `dist-tools/` — собранные Windows `.exe`

## Что умеет проект

- лендинг и web-приложение `/app`
- список членов семьи и дерево
- экспорт и backup
- работа с фото и server API
- Windows-мастер для настройки сервера на ПК

## Что нужно для запуска

- Node.js 20+
- Python 3.11+
- Windows PowerShell

## Быстрый старт для разработки

### 1. Установить frontend-зависимости

```powershell
npm install
```

### 2. Поднять backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### 3. Запустить проект

Frontend:

```powershell
npm run dev
```

Backend:

```powershell
cd backend
.venv\Scripts\python.exe telegram_service.py
```

## Запуск всего стека на Windows

Если нужен запуск через готовый PowerShell-скрипт:

```powershell
.\scripts\deploy-and-run.ps1
```

Остановка:

```powershell
.\scripts\stop-all.ps1
```

## Полезные команды

```powershell
npm run dev
npm run build
npm run typecheck
.\scripts\build-pc-setup-ui.ps1
```

## Что собирается

- web-сборка: `dist/`
- Windows-утилиты: `dist-tools/`

## Где смотреть дальше

- backend-детали: `backend/README.md`
- описание таблиц SQLite: `backend/README.md` -> раздел `Структура базы данных`
- инфраструктура: `infra/`
- дополнительные заметки: `docs/`
