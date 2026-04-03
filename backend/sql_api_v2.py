from __future__ import annotations

import base64
import json
import os
import secrets
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from flask import Response, redirect, request, send_file, session

from sql_repository import (
    attach_yandex_identity,
    delete_backup,
    ensure_local_user,
    get_auth_snapshot,
    get_backup_meta,
    get_user_id_for_request,
    load_backup_path,
    resolve_user_snapshot,
    store_backup,
)


def _json_response(data: dict[str, Any], status: int = 200) -> Response:
    payload = json.dumps(data, ensure_ascii=False)
    return Response(
        payload,
        status=status,
        mimetype='application/json',
        headers={'Content-Length': str(len(payload.encode('utf-8')))},
    )


def _html_response(html: str, status: int = 200) -> Response:
    return Response(html, status=status, mimetype='text/html; charset=utf-8')


def _provider_flags() -> dict[str, dict[str, bool]]:
    return {
        'yandex': {
            'configured': bool(
                str(os.environ.get('YANDEX_CLIENT_ID') or '').strip()
                and str(os.environ.get('YANDEX_CLIENT_SECRET') or '').strip()
            )
        },
        'vk': {'configured': False},
    }


def _request_device_id() -> str:
    device_id = str(request.headers.get('X-FamilyOne-Device') or '').strip()
    if device_id:
        return device_id

    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        device_id = str(payload.get('deviceId') or payload.get('device_id') or '').strip()
        if device_id:
            return device_id

    return str(request.args.get('device_id') or '').strip()


def _request_display_name(default_name: str = 'Веб-клиент Семейного древа') -> str:
    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        display_name = str(payload.get('displayName') or payload.get('display_name') or '').strip()
        if display_name:
            return display_name
    return default_name


def _public_origin() -> str:
    return str(os.environ.get('PUBLIC_ORIGIN') or 'https://totalcode.online').rstrip('/')


def _bootstrap_snapshot(db_path: Path) -> dict[str, Any]:
    device_id = _request_device_id()
    display_name = _request_display_name()
    session_user_id = session.get('familyone_user_id')
    snapshot = resolve_user_snapshot(
        db_path,
        device_id=device_id,
        session_user_id=int(session_user_id) if session_user_id else None,
        display_name=display_name,
        allow_create=bool(device_id),
    )
    if snapshot is None:
        return {
            'success': True,
            'providers': _provider_flags(),
            'auth': {'authenticated': False, 'user': None},
        }

    return {
        'success': True,
        'providers': _provider_flags(),
        'auth': {
            'authenticated': True,
            'user': snapshot['user'],
        },
    }


def _encode_state(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode_state(raw_state: str) -> dict[str, Any]:
    padding = '=' * (-len(raw_state) % 4)
    decoded = base64.urlsafe_b64decode((raw_state + padding).encode('ascii'))
    return json.loads(decoded.decode('utf-8'))


def _render_popup(provider: str, status: str, message: str) -> str:
    payload = json.dumps(
        {
            'source': 'familyone-auth',
            'provider': provider,
            'status': status,
            'message': message,
        },
        ensure_ascii=False,
    )
    safe_message = json.dumps(message, ensure_ascii=False)
    title = 'Подключение завершено' if status == 'success' else 'Не удалось завершить вход'
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #0b0e17;
      color: #f4f7ff;
      font: 16px/1.5 Segoe UI, Arial, sans-serif;
    }}
    .card {{
      width: min(92vw, 420px);
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(17, 22, 34, 0.94);
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(0,0,0,0.28);
    }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    p {{ margin: 0 0 18px; color: #ced7f5; }}
    button {{
      border: none;
      border-radius: 14px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 600;
      color: white;
      background: linear-gradient(135deg, #7c5cfc, #f472b6);
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <main class="card">
    <h1>{title}</h1>
    <p id="message"></p>
    <button type="button" onclick="window.close()">Закрыть окно</button>
  </main>
  <script>
    const payload = {payload};
    const message = {safe_message};
    document.getElementById('message').textContent = message;
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage(payload, '*');
      }}
    }} catch (error) {{
      console.error(error);
    }}
    setTimeout(() => {{
      try {{ window.close(); }} catch (error) {{ console.error(error); }}
    }}, 700);
  </script>
</body>
</html>"""


def _redirect_to_mobile(app_redirect_uri: str, provider: str, status: str, message: str) -> Response:
    query = urllib.parse.urlencode(
        {
            'provider': provider,
            'status': status,
            'message': message,
        }
    )
    separator = '&' if '?' in app_redirect_uri else '?'
    return redirect(f'{app_redirect_uri}{separator}{query}')


def _yandex_redirect_uri(mobile: bool) -> str:
    suffix = '/api/v2/auth/yandex/mobile/callback' if mobile else '/api/v2/auth/yandex/callback'
    return f'{_public_origin()}{suffix}'


def _exchange_yandex_code(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id = str(os.environ.get('YANDEX_CLIENT_ID') or '').strip()
    client_secret = str(os.environ.get('YANDEX_CLIENT_SECRET') or '').strip()
    token_response = requests.post(
        'https://oauth.yandex.ru/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
        },
        timeout=30,
    )
    token_response.raise_for_status()
    token_payload = token_response.json()
    access_token = str(token_payload.get('access_token') or '').strip()
    if not access_token:
        raise ValueError('Yandex token response does not contain access_token')

    profile_response = requests.get(
        'https://login.yandex.ru/info',
        params={'format': 'json'},
        headers={'Authorization': f'OAuth {access_token}'},
        timeout=30,
    )
    profile_response.raise_for_status()
    return profile_response.json()


def register_sql_api_v2(app, *, base_dir: Path, logger=None) -> None:
    db_path = base_dir / 'familyone.db'
    app.secret_key = str(os.environ.get('SESSION_SECRET_KEY') or secrets.token_hex(32))
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['MAX_CONTENT_LENGTH'] = max(
        int(app.config.get('MAX_CONTENT_LENGTH') or 0),
        int(os.environ.get('BACKUP_MAX_FILE_MB') or '250') * 1024 * 1024,
    )

    if logger:
        logger.info('SQL v2 API enabled, database=%s', db_path)

    @app.get('/api/v2/auth/providers')
    @app.get('/v2/auth/providers')
    def auth_providers():
        return _json_response({'success': True, 'providers': _provider_flags()})

    @app.post('/api/v2/auth/bootstrap')
    @app.post('/v2/auth/bootstrap')
    def auth_bootstrap():
        device_id = _request_device_id()
        if device_id:
            ensure_local_user(db_path, device_id, _request_display_name('Веб-клиент Семейного древа'))
        return _json_response(_bootstrap_snapshot(db_path))

    @app.get('/api/v2/auth/me')
    @app.get('/v2/auth/me')
    def auth_me():
        return _json_response(_bootstrap_snapshot(db_path))

    @app.post('/api/v2/auth/logout')
    @app.post('/v2/auth/logout')
    def auth_logout():
        session.clear()
        return _json_response({'success': True})

    @app.get('/api/v2/auth/yandex/start')
    @app.get('/v2/auth/yandex/start')
    def auth_yandex_start():
        if not _provider_flags()['yandex']['configured']:
            return _json_response({'success': False, 'error': 'Yandex ID is not configured'}, 503)

        device_id = _request_device_id()
        if not device_id:
            return _json_response({'success': False, 'error': 'Device ID is required'}, 400)

        state = _encode_state({'deviceId': device_id, 'mode': 'web'})
        auth_url = (
            'https://oauth.yandex.ru/authorize?'
            + urllib.parse.urlencode(
                {
                    'response_type': 'code',
                    'client_id': os.environ.get('YANDEX_CLIENT_ID', ''),
                    'redirect_uri': _yandex_redirect_uri(mobile=False),
                    'state': state,
                }
            )
        )
        return redirect(auth_url)

    @app.get('/api/v2/auth/yandex/mobile/start')
    @app.get('/v2/auth/yandex/mobile/start')
    def auth_yandex_mobile_start():
        if not _provider_flags()['yandex']['configured']:
            return _json_response({'success': False, 'error': 'Yandex ID is not configured'}, 503)

        device_id = _request_device_id()
        app_redirect_uri = str(request.args.get('app_redirect_uri') or '').strip()
        if not device_id or not app_redirect_uri:
            return _json_response(
                {'success': False, 'error': 'device_id and app_redirect_uri are required'},
                400,
            )

        state = _encode_state(
            {
                'deviceId': device_id,
                'mode': 'mobile',
                'appRedirectUri': app_redirect_uri,
            }
        )
        auth_url = (
            'https://oauth.yandex.ru/authorize?'
            + urllib.parse.urlencode(
                {
                    'response_type': 'code',
                    'client_id': os.environ.get('YANDEX_CLIENT_ID', ''),
                    'redirect_uri': _yandex_redirect_uri(mobile=True),
                    'state': state,
                }
            )
        )
        return redirect(auth_url)

    @app.get('/api/v2/auth/yandex/callback')
    @app.get('/v2/auth/yandex/callback')
    def auth_yandex_callback():
        error = str(request.args.get('error') or '').strip()
        state_raw = str(request.args.get('state') or '').strip()
        if not state_raw:
            return _html_response(_render_popup('yandex', 'error', 'Не удалось завершить вход: отсутствует state'), 400)

        try:
            state = _decode_state(state_raw)
        except Exception:
            return _html_response(_render_popup('yandex', 'error', 'Не удалось завершить вход: повреждён state'), 400)

        if error:
            message = str(request.args.get('error_description') or error)
            return _html_response(_render_popup('yandex', 'error', message), 400)

        code = str(request.args.get('code') or '').strip()
        if not code:
            return _html_response(_render_popup('yandex', 'error', 'Не удалось завершить вход: отсутствует code'), 400)

        try:
            profile = _exchange_yandex_code(code, _yandex_redirect_uri(mobile=False))
            snapshot = attach_yandex_identity(db_path, str(state.get('deviceId') or ''), profile)
            session['familyone_user_id'] = int(snapshot['user']['id'])
            session['familyone_device_id'] = str(state.get('deviceId') or '')
            session.modified = True
            return _html_response(_render_popup('yandex', 'success', 'Яндекс ID подключен'))
        except Exception as error_obj:
            if logger:
                logger.exception('Yandex web callback failed')
            return _html_response(_render_popup('yandex', 'error', str(error_obj)), 500)

    @app.get('/api/v2/auth/yandex/mobile/callback')
    @app.get('/v2/auth/yandex/mobile/callback')
    def auth_yandex_mobile_callback():
        error = str(request.args.get('error') or '').strip()
        state_raw = str(request.args.get('state') or '').strip()
        if not state_raw:
            return _json_response({'success': False, 'error': 'Missing state'}, 400)

        try:
            state = _decode_state(state_raw)
        except Exception:
            return _json_response({'success': False, 'error': 'Invalid state'}, 400)

        app_redirect_uri = str(state.get('appRedirectUri') or '').strip()
        if not app_redirect_uri:
            return _json_response({'success': False, 'error': 'Missing app redirect uri'}, 400)

        if error:
            message = str(request.args.get('error_description') or error)
            return _redirect_to_mobile(app_redirect_uri, 'yandex', 'error', message)

        code = str(request.args.get('code') or '').strip()
        if not code:
            return _redirect_to_mobile(app_redirect_uri, 'yandex', 'error', 'Не удалось завершить вход: отсутствует code')

        try:
            profile = _exchange_yandex_code(code, _yandex_redirect_uri(mobile=True))
            snapshot = attach_yandex_identity(db_path, str(state.get('deviceId') or ''), profile)
            session['familyone_user_id'] = int(snapshot['user']['id'])
            session['familyone_device_id'] = str(state.get('deviceId') or '')
            session.modified = True
            return _redirect_to_mobile(app_redirect_uri, 'yandex', 'success', 'Яндекс ID подключен')
        except Exception as error_obj:
            if logger:
                logger.exception('Yandex mobile callback failed')
            return _redirect_to_mobile(app_redirect_uri, 'yandex', 'error', str(error_obj))

    def _resolve_backup_user_id() -> int | None:
        device_id = _request_device_id()
        return get_user_id_for_request(
            db_path,
            device_id=device_id,
            session_user_id=int(session.get('familyone_user_id')) if session.get('familyone_user_id') else None,
            display_name=_request_display_name(),
            allow_create=bool(device_id),
        )

    @app.get('/api/v2/backup/meta')
    @app.get('/v2/backup/meta')
    def backup_meta_v2():
        user_id = _resolve_backup_user_id()
        if not user_id:
            return _json_response({'success': False, 'error': 'Backup auth is required'}, 401)
        return _json_response(get_backup_meta(db_path, base_dir, user_id))

    @app.post('/api/v2/backup/upload')
    @app.post('/v2/backup/upload')
    def backup_upload_v2():
        user_id = _resolve_backup_user_id()
        if not user_id:
            return _json_response({'success': False, 'error': 'Backup auth is required'}, 401)

        backup_file = request.files.get('backup_file')
        if backup_file is None:
            return _json_response({'success': False, 'error': 'backup_file is required'}, 400)

        try:
            archive_bytes = backup_file.read()
            meta = store_backup(db_path, base_dir, user_id, archive_bytes)
            return _json_response(meta)
        except Exception as error_obj:
            if logger:
                logger.exception('backup upload failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 400)

    @app.get('/api/v2/backup/download')
    @app.get('/v2/backup/download')
    def backup_download_v2():
        user_id = _resolve_backup_user_id()
        if not user_id:
            return _json_response({'success': False, 'error': 'Backup auth is required'}, 401)

        try:
            archive_path = load_backup_path(db_path, base_dir, user_id)
        except FileNotFoundError:
            return _json_response({'success': False, 'error': 'Backup not found'}, 404)
        except Exception as error_obj:
            if logger:
                logger.exception('backup download failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

        return send_file(
            archive_path,
            as_attachment=True,
            download_name='familyone_backup.zip',
            mimetype='application/zip',
            conditional=True,
        )

    @app.delete('/api/v2/backup')
    @app.delete('/v2/backup')
    def backup_delete_v2():
        user_id = _resolve_backup_user_id()
        if not user_id:
            return _json_response({'success': False, 'error': 'Backup auth is required'}, 401)

        try:
            result = delete_backup(db_path, base_dir, user_id)
            return _json_response(result)
        except Exception as error_obj:
            if logger:
                logger.exception('backup delete failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)
