# Backend: Face API + Backup API

Этот backend обслуживает:

- распознавание лиц,
- генерацию PDF,
- серверный backup для Android/будущего Web.

## Backup API (Google ID token)

Все backup endpoint-ы требуют:

- `Authorization: Bearer <google_id_token>`

Маршруты:

- `POST /api/backup/upload` (алиас `/backup/upload`)
- `GET /api/backup/meta` (алиас `/backup/meta`)
- `GET /api/backup/download` (алиас `/backup/download`)
- `DELETE /api/backup` (алиас `/backup`)

## Обязательные env для backup

Укажите в `backend/.env`:

```env
GOOGLE_OAUTH_WEB_CLIENT_ID=YOUR_WEB_CLIENT_ID.apps.googleusercontent.com
BACKUP_STORAGE_DIR=backup_storage
BACKUP_MAX_FILE_MB=250
BACKUP_MAX_UNCOMPRESSED_MB=700
BACKUP_SCHEMA_VERSION=1
```

Опционально:

```env
CORS_ORIGINS=https://your-web-domain.com,https://staging.your-web-domain.com
```

## Как работает авторизация

1. Клиент (Android/Web) получает Google ID token.
2. Backend верифицирует token (`aud`, `iss`, `exp`) через `google.oauth2.id_token`.
3. Владелец backup определяется по `sub`.
4. Доступ к backup файлу ограничен этим владельцем.

## Политика хранения

Для каждого пользователя хранится только один актуальный backup:

- `backup_storage/<hashed_owner_sub>/latest.zip`
- `backup_storage/<hashed_owner_sub>/latest.meta.json`

Замена выполняется атомарно через temp-файл и `os.replace`.

## Запуск

Из папки `backend`:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe telegram_service.py
```

Проверка:

```bash
curl https://totalcode.indevs.in/api/health
```

В ответе ожидается `"backup": true`.
