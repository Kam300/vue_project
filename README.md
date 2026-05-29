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

## Multi-device sync safety (v0.9)

Раздел описывает изменения, появившиеся вместе со спецификацией
`multi-device-sync-safety` (см. `.kiro/specs/multi-device-sync-safety/`).
Цель — защитить данные пользователя при одновременной работе с двух
и более устройств, исключить «тихую» потерю изменений и сделать поведение
сервера и клиентов согласованным с тегом версии бэкапа.

### Новые HTTP-заголовки

- `If-Match: <serverVersionTag>` — обязательный для `POST /v2/backup/upload`
  (off-line загрузка снапшота). Значение — последний известный клиенту
  `serverVersionTag` (нижний регистр, 64 hex). Для первого снапшота допустимо
  `If-Match: *`.
- `X-Client-Capabilities: if-match-v1` — клиент сообщает, что умеет работать
  с оптимистичной блокировкой по `If-Match`. Старые клиенты без этого
  заголовка получают `426 client_upgrade_required` при попытке перезаписать
  существующий снапшот; первая загрузка для пользователя без снапшота
  по-прежнему принимается.

### Новые/обновлённые эндпоинты

- `POST /v2/backup/upload` — теперь учитывает `If-Match` и query-параметр
  `force=true` (см. таблицу решений ниже). Ответ всегда содержит свежий
  `serverVersionTag`.
- `GET /v2/backup/meta` — добавлено поле `serverVersionTag` в payload.
- `PATCH /v2/auth/settings` — переключение режима «одна сессия / много сессий»:
  тело `{"singleSessionEnabled": boolean}`; при включении строгого режима
  все остальные активные сессии пользователя ревокаются с причиной
  `single_session_re_enabled`. Ответ:
  `{"success": true, "singleSessionEnabled": <new>, "revokedSessions": <n>}`.
- `GET /v2/presence/ping` — лёгкий probe для определения онлайн-состояния.
  Не требует авторизации, отвечает 2xx без тела. Используется детектором
  офлайна на Web и Android.

### Семантика кодов ответа `POST /v2/backup/upload`

| Код | Когда                                                                 | Что делать клиенту                                                  |
|-----|------------------------------------------------------------------------|---------------------------------------------------------------------|
| 200 | `If-Match` совпал с текущим тегом, либо `force=true`                   | Удалить подтверждённые `changeId` из локального буфера, обновить тег|
| 409 | Конфликт версий: серверный тег отличается от `If-Match`                | Открыть «Конфликт версий», предложить «Скачать серверную версию» / «Перезаписать всё равно» |
| 426 | Legacy-клиент (нет `X-Client-Capabilities: if-match-v1`) при существующем снапшоте | Обновить клиент до версии с поддержкой `if-match-v1` |
| 428 | Заголовок `If-Match` отсутствует у capability-aware клиента            | Получить актуальный тег через `GET /v2/backup/meta` и повторить через 1 с |
| 503 | `audit_unavailable` — не удалось записать аудит при `force=true`       | Снапшот не изменён; повторить позже                                 |

### Чтение `serverVersionTag`

`serverVersionTag = sha256(updated_at_sql + "|" + checksum_sha256)`, lowercase
hex длиной 64 символа. Тег детерминированно вычисляется сервером и одинаков
для двух последовательных `GET /v2/backup/meta` без записи между ними.
Клиент сохраняет последний известный тег после `GET /v2/backup/meta`,
`GET /v2/backup/download` и `POST /v2/backup/upload (200)`.

### Переменные окружения

- `BACKUP_REQUIRE_IF_MATCH=1` — значение по умолчанию. Сервер требует
  `If-Match` от capability-aware клиентов и возвращает 409 / 428 / 426
  согласно таблице выше.
- `BACKUP_REQUIRE_IF_MATCH=0` — режим инцидент-респонса. Сервер по-прежнему
  выдаёт `serverVersionTag`, но `If-Match` трактуется как advisory:
  `409 / 428 / 426` не возвращаются. Использовать только временно при
  устранении массовых сбоев синхронизации.

### План раскатки

1. Сервер выкатывается с `BACKUP_REQUIRE_IF_MATCH=1` и поддержкой обоих
   заголовков. Старые клиенты, у которых уже есть снапшот, получают `426`
   и обновляются. Первая загрузка для пользователя без снапшота принимается
   и от legacy-клиента.
2. Web и Android выкатываются с `X-Client-Capabilities: if-match-v1`,
   `Pending_Changes_Buffer` и UI: офлайн-баннер, бейдж
   «N несинхронизированных изменений», диалоги «Конфликт версий» и
   «Сессия завершена. Несохранённые изменения», тумблер
   «Разрешить одновременные сессии на нескольких устройствах».
3. При инциденте сервер можно временно перевести в `BACKUP_REQUIRE_IF_MATCH=0`,
   чтобы снять оптимистичную блокировку, не выкатывая клиентов.

### Дополнительно

- Подробные требования: `.kiro/specs/multi-device-sync-safety/requirements.md`.
- Архитектура и таблицы решений: `.kiro/specs/multi-device-sync-safety/design.md`.
- Список реализационных задач: `.kiro/specs/multi-device-sync-safety/tasks.md`.
