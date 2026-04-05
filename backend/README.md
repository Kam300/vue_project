# Backend: API, backup и база данных

Этот backend отвечает за:

- API для web и Android
- backup и восстановление
- хранение структуры семейного древа
- фото и распознавание лиц
- авторизацию через локальное устройство и внешние провайдеры

## Запуск

Из папки `backend`:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe telegram_service.py
```

База данных по умолчанию:

- `backend/familyone.db`

## Backup API

Основные маршруты:

- `POST /api/backup/upload`
- `GET /api/backup/meta`
- `GET /api/backup/download`
- `DELETE /api/backup`

Для backup используются:

- SQLite-метаданные в `familyone.db`
- сами архивы в `backup_storage/` или `backup_storage_sql/`

## Обязательные env для backup

```env
GOOGLE_OAUTH_WEB_CLIENT_ID=YOUR_WEB_CLIENT_ID.apps.googleusercontent.com
BACKUP_STORAGE_DIR=backup_storage
BACKUP_MAX_FILE_MB=250
BACKUP_MAX_UNCOMPRESSED_MB=700
BACKUP_SCHEMA_VERSION=1
```

## Структура базы данных

Актуальная база `familyone.db` содержит `13` таблиц.

### Пользователи и доступ

- `users` — основная таблица пользователей. Хранит имя, email, телефон, предпочтительный способ входа и время последнего входа.
- `auth_identities` — привязки внешних и локальных идентичностей к пользователю. Здесь лежат `provider`, `provider_user_id`, профиль провайдера и служебные поля входа.
- `user_settings` — настройки конкретного пользователя: onboarding, privacy consent, PIN, тема, базовый API URL, device id и дерево по умолчанию.
- `family_trees` — сами семейные деревья. У дерева есть владелец, название и описание.
- `tree_memberships` — связь пользователей с деревьями. Нужна, чтобы один пользователь мог быть владельцем или участником конкретного дерева.

### Люди и связи внутри дерева

- `persons` — главная таблица людей в дереве. Хранит ФИО, пол, даты, роль в семье, заметки и ссылку на фото.
- `person_contacts` — контакты человека. Отдельная таблица нужна, чтобы у одного человека могло быть несколько контактов разных типов.
- `relationships` — связи между людьми: кто кому родитель, супруг, ребёнок и так далее.

### Фото и распознавание лиц

- `photos` — все фотографии, загруженные в дерево. Хранит путь к файлу, хэши, источник, дату и флаг фото профиля.
- `photo_person_tags` — отметки людей на фотографиях. Здесь хранится, кто отмечен, кем отмечен, источник тега и confidence.
- `face_encodings` — векторы признаков лица для распознавания. Привязаны к человеку и, при необходимости, к фото.

### Backup и журнал действий

- `backup_snapshots` — метаданные backup-архивов: путь, checksum, размер, версия схемы, количество людей, фото и assets.
- `audit_logs` — журнал действий в системе. Используется для отслеживания операций вроде загрузки и удаления backup.

## Как это связано между собой

- один `user` может иметь несколько `auth_identities`
- один `user` может иметь несколько `family_trees` через `tree_memberships`
- одно `family_tree` содержит много `persons`, `photos`, `relationships` и `backup_snapshots`
- один `person` может иметь много `person_contacts`, `photo_person_tags` и `face_encodings`

## Практический смысл таблиц

- если нужно показать список людей — читается `persons`
- если нужно построить дерево — используются `persons` + `relationships`
- если нужен профиль входа — используются `users` + `auth_identities` + `user_settings`
- если нужен backup — используются `backup_snapshots` и файловое хранилище
- если нужно распознавание лиц — используются `photos`, `photo_person_tags`, `face_encodings`

