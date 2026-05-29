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
    delete_backup_admin,
    delete_face_encoding_admin,
    delete_user_admin,
    ensure_local_user,
    get_admin_stats,
    get_auth_snapshot,
    get_backup_meta,
    get_user_id_for_request,
    is_user_admin,
    list_all_backups_admin,
    list_audit_logs_admin,
    list_face_encodings_admin,
    list_users_admin,
    load_backup_path,
    resolve_user_snapshot,
    set_user_admin,
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
        allow_create=False,
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

    token_payload = _yandex_request_with_retry(
        method='POST',
        url='https://oauth.yandex.ru/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
        },
        timeout=30,
    )
    access_token = str(token_payload.get('access_token') or '').strip()
    if not access_token:
        raise ValueError('Yandex token response does not contain access_token')

    return _yandex_request_with_retry(
        method='GET',
        url='https://login.yandex.ru/info',
        params={'format': 'json'},
        headers={'Authorization': f'OAuth {access_token}'},
        timeout=30,
    )


def _yandex_request_with_retry(
    *,
    method: str,
    url: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """
    Выполняет запрос к Yandex OAuth/login API с ретраем по сетевым ошибкам
    (SSLError, ConnectionError, Timeout). Возвращает распарсенный JSON.
    """
    import time
    from requests.exceptions import (
        ConnectionError as RequestsConnectionError,
        SSLError,
        Timeout,
    )

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            if method == 'POST':
                response = requests.post(url, data=data, headers=headers, timeout=timeout)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (SSLError, RequestsConnectionError, Timeout) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(0.6 * attempt)  # 0.6s, 1.2s, ...

    raise ConnectionError(
        'Не удалось связаться с серверами Yandex (SSL / сеть оборвана). '
        'Попробуйте ещё раз через минуту, отключите VPN/прокси/антивирус, '
        'либо проверьте подключение к интернету. '
        f'Подробнее: {last_error}'
    )


def register_sql_api_v2(
    app,
    *,
    base_dir: Path,
    logger=None,
    face_encodings_db: dict | None = None,
    save_encodings_fn=None,
    reference_photos_dir: str | None = None,
) -> None:
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

    # ============================================================
    # PRESENCE TRACKER (in-memory)
    # ============================================================
    import threading
    import time as _time

    presence: dict[str, dict[str, Any]] = {}
    presence_lock = threading.Lock()
    PRESENCE_WINDOW_SEC = 90  # сколько секунд считаем юзера "онлайн" после последнего ping

    def _presence_touch(client_key: str, user_id: int | None) -> None:
        now = _time.time()
        with presence_lock:
            presence[client_key] = {
                'last_seen': now,
                'user_id': user_id,
            }
            # cleanup
            cutoff = now - PRESENCE_WINDOW_SEC
            stale = [k for k, v in presence.items() if v['last_seen'] < cutoff]
            for k in stale:
                presence.pop(k, None)

    def _presence_snapshot() -> dict[str, Any]:
        now = _time.time()
        cutoff = now - PRESENCE_WINDOW_SEC
        with presence_lock:
            active = [v for v in presence.values() if v['last_seen'] >= cutoff]
        authorized = sum(1 for v in active if v['user_id'])
        anonymous = len(active) - authorized
        return {
            'total': len(active),
            'authorized': authorized,
            'anonymous': anonymous,
            'window_seconds': PRESENCE_WINDOW_SEC,
        }

    @app.post('/api/v2/presence/ping')
    @app.post('/v2/presence/ping')
    def presence_ping():
        device_id = _request_device_id()
        # client key: device_id если есть, иначе IP
        client_key = device_id or (request.remote_addr or 'anonymous')
        user_id = None
        if device_id:
            try:
                user_id = get_user_id_for_request(
                    db_path,
                    device_id=device_id,
                    session_user_id=int(session.get('familyone_user_id'))
                    if session.get('familyone_user_id')
                    else None,
                    allow_create=False,
                )
            except Exception:
                user_id = None
        _presence_touch(client_key, user_id)
        return _json_response({'success': True})

    @app.get('/api/v2/auth/providers')
    @app.get('/v2/auth/providers')
    def auth_providers():
        return _json_response({'success': True, 'providers': _provider_flags()})

    @app.post('/api/v2/auth/bootstrap')
    @app.post('/v2/auth/bootstrap')
    def auth_bootstrap():
        # Не создаём гостевого пользователя на каждый заход.
        # Запись появится только при Яндекс-логине или загрузке бэкапа.
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

    # ============================================================
    # ADMIN ROUTES
    # ============================================================
    def _require_admin() -> tuple[int | None, Response | None]:
        user_id = _resolve_backup_user_id()
        if not user_id:
            return None, _json_response({'success': False, 'error': 'Auth is required'}, 401)
        if not is_user_admin(db_path, user_id):
            return None, _json_response({'success': False, 'error': 'Admin access required'}, 403)
        return user_id, None

    @app.get('/api/v2/admin/stats')
    @app.get('/v2/admin/stats')
    def admin_stats():
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            stats_data = get_admin_stats(db_path, base_dir)
            stats_data['presence'] = _presence_snapshot()
            return _json_response({'success': True, **stats_data})
        except Exception as error_obj:
            if logger:
                logger.exception('admin stats failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.get('/api/v2/admin/users')
    @app.get('/v2/admin/users')
    def admin_users_list():
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            users = list_users_admin(db_path)
            return _json_response({'success': True, 'users': users})
        except Exception as error_obj:
            if logger:
                logger.exception('admin users list failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.post('/api/v2/admin/users/<int:target_user_id>/admin')
    @app.post('/v2/admin/users/<int:target_user_id>/admin')
    def admin_users_set_admin(target_user_id):
        admin_id, error_response = _require_admin()
        if error_response is not None:
            return error_response
        payload = request.get_json(silent=True) or {}
        is_admin = bool(payload.get('isAdmin', False))
        if not is_admin and target_user_id == admin_id:
            return _json_response(
                {'success': False, 'error': 'Cannot revoke your own admin rights'}, 400
            )
        try:
            set_user_admin(db_path, target_user_id, is_admin)
            return _json_response({'success': True})
        except Exception as error_obj:
            if logger:
                logger.exception('admin set_admin failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.delete('/api/v2/admin/users/<int:target_user_id>')
    @app.delete('/v2/admin/users/<int:target_user_id>')
    def admin_users_delete(target_user_id):
        admin_id, error_response = _require_admin()
        if error_response is not None:
            return error_response
        if target_user_id == admin_id:
            return _json_response(
                {'success': False, 'error': 'Cannot delete your own account'}, 400
            )
        try:
            result = delete_user_admin(db_path, base_dir, target_user_id)
            status = 200 if result.get('success') else 400
            return _json_response(result, status)
        except Exception as error_obj:
            if logger:
                logger.exception('admin user delete failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.post('/api/v2/admin/users/bulk-delete')
    @app.post('/v2/admin/users/bulk-delete')
    def admin_users_bulk_delete():
        admin_id, error_response = _require_admin()
        if error_response is not None:
            return error_response
        payload = request.get_json(silent=True) or {}
        ids = payload.get('userIds') or payload.get('user_ids') or []
        if not isinstance(ids, list):
            return _json_response({'success': False, 'error': 'userIds must be an array'}, 400)
        try:
            from sql_repository import bulk_delete_users_admin
            result = bulk_delete_users_admin(db_path, base_dir, ids, admin_id)
            return _json_response(result)
        except Exception as error_obj:
            if logger:
                logger.exception('admin bulk delete failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.get('/api/v2/admin/backups')
    @app.get('/v2/admin/backups')
    def admin_backups_list():
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            backups = list_all_backups_admin(db_path, base_dir)
            return _json_response({'success': True, 'backups': backups})
        except Exception as error_obj:
            if logger:
                logger.exception('admin backups list failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.delete('/api/v2/admin/backups/<int:backup_id>')
    @app.delete('/v2/admin/backups/<int:backup_id>')
    def admin_backups_delete(backup_id):
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            result = delete_backup_admin(db_path, base_dir, backup_id)
            status = 200 if result.get('success') else 404
            return _json_response(result, status)
        except Exception as error_obj:
            if logger:
                logger.exception('admin backup delete failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.get('/api/v2/admin/audit')
    @app.get('/v2/admin/audit')
    def admin_audit_list():
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            limit = int(request.args.get('limit', 100))
        except ValueError:
            limit = 100
        try:
            logs_data = list_audit_logs_admin(db_path, limit=limit)
            return _json_response({'success': True, 'logs': logs_data})
        except Exception as error_obj:
            if logger:
                logger.exception('admin audit list failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.get('/api/v2/admin/faces')
    @app.get('/v2/admin/faces')
    def admin_faces_list():
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            # Читаем face_encodings_db из telegram_service (in-memory, актуальные данные)
            import sys
            ts = sys.modules.get('telegram_service') or sys.modules.get('__main__')
            face_db = getattr(ts, 'face_encodings_db', None) if ts else None
            ref_dir = getattr(ts, 'REFERENCE_PHOTOS_DIR', None) if ts else None

            if face_db and isinstance(face_db, dict):
                encodings = []
                for idx, (member_id, info) in enumerate(face_db.items()):
                    ref_photo_path = None
                    if ref_dir:
                        candidate = os.path.join(ref_dir, f"{member_id}.jpg")
                        if os.path.exists(candidate):
                            ref_photo_path = candidate
                    encodings.append({
                        'id': idx + 1,
                        'personId': 0,
                        'personName': info.get('name', ''),
                        'externalMemberId': str(member_id),
                        'modelVersion': 'face-recognition',
                        'isActive': True,
                        'referencePhotoPath': ref_photo_path,
                        'createdAt': None,
                    })
                return _json_response({
                    'success': True,
                    'count': len(encodings),
                    'encodings': encodings,
                })
            return _json_response({'success': True, **list_face_encodings_admin(db_path)})
        except Exception as error_obj:
            if logger:
                logger.exception('admin faces list failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)

    @app.delete('/api/v2/admin/faces/<int:face_id>')
    @app.delete('/v2/admin/faces/<int:face_id>')
    def admin_face_delete(face_id):
        _, error_response = _require_admin()
        if error_response is not None:
            return error_response
        try:
            if face_encodings_db is not None:
                member_ids = list(face_encodings_db.keys())
                idx = face_id - 1
                if 0 <= idx < len(member_ids):
                    member_id = member_ids[idx]
                    del face_encodings_db[member_id]
                    if reference_photos_dir:
                        photo_path = os.path.join(reference_photos_dir, f"{member_id}.jpg")
                        if os.path.exists(photo_path):
                            os.remove(photo_path)
                    if save_encodings_fn:
                        save_encodings_fn()
                    return _json_response({'success': True, 'message': f'Face {member_id} deleted'})
                return _json_response({'success': False, 'error': 'Face not found'}, 404)
            result = delete_face_encoding_admin(db_path, face_id)
            status = 200 if result.get('success') else 404
            return _json_response(result, status)
        except Exception as error_obj:
            if logger:
                logger.exception('admin face delete failed')
            return _json_response({'success': False, 'error': str(error_obj)}, 500)
