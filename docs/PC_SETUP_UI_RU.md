# FamilyOne PC Setup UI

Этот мастер нужен для быстрого запуска сервера FamilyOne на новом Windows-ПК.

Что он умеет:
- проверить VPS по SSH;
- получить FRP token с VPS по паролю;
- настроить `frpc` на текущем ПК;
- включить автозапуск на VPS и на ПК;
- запустить и остановить локальный стек;
- сделать health-check локально и по публичному домену.

## Быстрый запуск

Если Python уже установлен:

```powershell
cd C:\Users\RobotComp.ru\Documents\vs_ptoject\vue_project
.\scripts\run-pc-setup-ui.cmd
```

Либо:

```powershell
py -3 .\scripts\pc_server_setup_ui.py
```

## Как использовать на новом ПК

1. Скопируйте весь проект `vue_project` на новый ПК.
2. Откройте UI.
3. Заполните:
   - `VPS host`
   - `User`
   - `Password`
   - `Domain`
4. Нажмите `Full setup`.

UI сам:
- проверит VPS;
- включит автозапуск `frps/caddy` на VPS;
- прочитает FRP token;
- настроит `frpc` на новом ПК;
- включит автозапуск на ПК;
- запустит сервер;
- выполнит проверку.

## Автозапуск ПК

Логика такая:
- если UI запущен с админ-правами, будет создан `Scheduled Task` с запуском при старте Windows;
- если админ-прав нет, будет создан автозапуск через `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, то есть запуск после входа пользователя.

## Сборка EXE

Если хотите использовать UI как обычную Windows-программу без отдельного запуска `.py`, соберите `.exe`:

```powershell
cd C:\Users\RobotComp.ru\Documents\vs_ptoject\vue_project
.\scripts\build-pc-setup-ui.ps1
```

После этого появится файл:

```text
dist-tools\familyone-pc-setup-ui.exe
```

Лучше держать `.exe` рядом с проектом, чтобы он видел `start-server.ps1` и папку `scripts`.
