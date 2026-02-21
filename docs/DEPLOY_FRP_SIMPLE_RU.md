# Простой туториал: публикация FamilyOne на `totalcode.online` (Windows + VPS + FRP)

Этот вариант работает без Cloudflare Tunnel:
- сайт и API крутятся на вашем Windows-ПК;
- VPS используется как публичная точка входа;
- домен `totalcode.online` ведет на VPS.

## 1. Что должно быть

- Домен: `totalcode.online`
- VPS Ubuntu 22.04+ с белым IP (пример: `144.31.53.179`)
- Локальный ПК Windows с проектом `vue_project`

## 2. DNS (один раз)

В панели DNS домена:
- `A` запись: `@` -> `IP_ВАШЕГО_VPS`
- `CNAME` запись: `www` -> `totalcode.online`

Проверка:

```powershell
Resolve-DnsName totalcode.online
```

## 3. Настройка VPS (один раз)

На Windows (в папке проекта):

```powershell
scp .\infra\frp\setup-frps.sh root@IP_VPS:/root/setup-frps.sh
ssh root@IP_VPS
```

На VPS:

```bash
chmod +x /root/setup-frps.sh
/root/setup-frps.sh --domain totalcode.online --email your@email.com
```

Сохраните токен:

```bash
grep -E '^token\s*=' /etc/frp/frps.toml
```

## 4. Настройка FRP-клиента на Windows (один раз)

Запустите PowerShell **от имени администратора**:

```powershell
cd C:\Users\RobotComp.ru\Documents\vs_ptoject\vue_project
.\scripts\setup-frpc.ps1 `
  -ServerIp IP_VPS `
  -Token "ВАШ_ТОКЕН_ИЗ_VPS" `
  -Domain totalcode.online `
  -ProxyName "familyone-web-robot" `
  -InstallService
```

> Если скачивание FRP блокируется, сначала скачайте `frpc.exe` вручную, затем передайте `-FrpcExePath`.

## 5. Ежедневный запуск

Обычный PowerShell:

```powershell
cd C:\Users\RobotComp.ru\Documents\vs_ptoject\vue_project
.\start-server.ps1 -NoTunnel
```

Остановка:

```powershell
.\stop-server.ps1
```

## 6. Быстрые проверки

Локально:

```powershell
curl.exe -I http://127.0.0.1:8080/
```

Публично:

```powershell
curl.exe -I http://totalcode.online/
curl.exe -I https://totalcode.online/
curl.exe -I https://totalcode.online/api/health
```

На VPS:

```bash
systemctl status frps caddy --no-pager
journalctl -u frps -n 80 --no-pager
journalctl -u caddy -n 80 --no-pager
```

## 7. Если что-то не работает

### `HTTP 404 Not Found` на домене

Обычно это означает, что FRP не видит корректный route.

Проверьте на Windows:

```powershell
tasklist | findstr /I frpc
Get-Content .\.runtime\frpc.out.log -Tail 80
```

Нужно, чтобы был ровно один рабочий `frpc` и в логе было `start proxy success`.

### `proxy already exists`

Есть дубликаты `frpc`. Уберите лишний:

```powershell
taskkill /F /IM frpc.exe
```

И снова:

```powershell
.\start-server.ps1 -NoTunnel
```

### `https` не открывается / TLS timeout

- Проверьте, не включен ли VPN.
- Убедитесь, что `443/tcp` открыт на VPS (`ufw status`).
- Проверьте, что `caddy` на VPS слушает `:443`:

```bash
ss -lntp | egrep ':80|:443|:7000|:8080'
```

## 8. Важно

- В проде используйте только один способ публикации: либо FRP, либо Cloudflare Tunnel.
- Для текущей схемы используйте только:

```powershell
.\start-server.ps1 -NoTunnel
```

