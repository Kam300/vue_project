# Full VPS Deploy

This path is separate from the current `frp` flow.

## Staging on VPS only

This keeps the current domain path untouched and deploys the full app to the VPS on `:8081`.

Run from Windows:

```powershell
cd C:\Users\RobotComp.ru\Documents\vs_ptoject\vue_project
.\scripts\deploy-full-vps.ps1 -VpsHost 64.188.90.80 -VpsUser root
```

Expected test URL:

```text
http://64.188.90.80:8081
```

## What it does

- uploads the current project to `/opt/familyone-vps`
- installs Node.js, Python, Caddy, build tools, and swap if needed
- builds the Vue frontend
- creates `backend/.venv` on Linux
- installs Python requirements
- creates a separate backend service: `familyone-backend-vps`
- adds a separate Caddy config in `/etc/caddy/conf.d/`

## Live switch later

After staging works, you can reuse the same script with a real site address and public origin.

Example:

```powershell
.\scripts\deploy-full-vps.ps1 -VpsHost 64.188.90.80 -VpsUser root -SiteAddress "app.example.com" -PublicOrigin "https://app.example.com" -ServiceName familyone-backend-live
```

Before using the live domain, make sure DNS points to the VPS and that there is no conflicting Caddy site for the same host.
