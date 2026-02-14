# Vue + Flask Global Deploy (Windows + Cloudflare Tunnel)

Сайт и API запускаются на вашем ПК и доступны глобально через:
- `https://totalcode.indevs.in/`
- `https://totalcode.indevs.in/api/*` (каноничный API)
- `https://totalcode.indevs.in/health` и другие legacy пути (обратная совместимость)

## Архитектура

1. `backend/telegram_service.py` (Flask + Waitress) на `127.0.0.1:5000`
2. `Caddy` на `127.0.0.1:8080`:
   - `/api/*` -> Flask (без префикса `/api`)
   - legacy endpoints -> Flask
   - остальное -> `dist` (SPA fallback)
3. `cloudflared` публикует `totalcode.indevs.in -> http://127.0.0.1:8080`

## Первый запуск (один раз)

1. Установите в PATH:
   - `node`, `npm`, `python`
   - `caddy`
   - `cloudflared`
   - Для Windows отдельный `cmake` не нужен: скрипт использует `dlib-bin` (prebuilt wheel).
2. Создайте tunnel и DNS:

```powershell
cloudflared tunnel login
cloudflared tunnel create vue-api-pc
cloudflared tunnel route dns vue-api-pc totalcode.indevs.in
```

3. Подготовьте конфиг tunnel:

```powershell
Copy-Item infra/cloudflared/config.yml.example infra/cloudflared/config.yml
```

Отредактируйте `infra/cloudflared/config.yml`:
- `tunnel: <REAL_TUNNEL_ID>`
- `credentials-file: <FULL_PATH_TO_JSON>`

4. Подготовьте backend env:

```powershell
Copy-Item backend/.env.example backend/.env
```

При необходимости задайте `GOOGLE_DRIVE_FOLDER_ID` и другие параметры.

## Ежедневный запуск

```powershell
.\scripts\deploy-and-run.ps1
```

Скрипт:
1. Проверяет зависимости
2. Ставит frontend/backend зависимости
3. Собирает Vite (`dist`)
4. Запускает API, Caddy и cloudflared в фоне
5. Делает health-check локально и снаружи
6. Пишет PID и логи в `.runtime/`

## Остановка

```powershell
.\scripts\stop-all.ps1
```

## Логи и PID

- PID: `.runtime/pids.json`
- API logs: `.runtime/api.out.log`, `.runtime/api.err.log`
- Caddy logs: `.runtime/caddy.out.log`, `.runtime/caddy.err.log`
- Cloudflared logs: `.runtime/cloudflared.out.log`, `.runtime/cloudflared.err.log`

## Локальная разработка фронта

```powershell
npm run dev
```

В dev-режиме Vite проксирует `/api/*` на `http://127.0.0.1:5000`.
