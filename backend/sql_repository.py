from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DISPLAY_NAME = 'Локальный пользователь Семейного древа'


def utcnow_sql() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' ')


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def db_connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def _provider_key(provider: str, provider_user_id: str) -> tuple[str, str]:
    return provider.strip().lower(), provider_user_id.strip()


def _query_user_by_identity(
    connection: sqlite3.Connection, provider: str, provider_user_id: str
) -> sqlite3.Row | None:
    provider, provider_user_id = _provider_key(provider, provider_user_id)
    return connection.execute(
        """
        SELECT u.*
        FROM auth_identities ai
        JOIN users u ON u.id = ai.user_id
        WHERE ai.provider = ? AND ai.provider_user_id = ?
        LIMIT 1
        """,
        (provider, provider_user_id),
    ).fetchone()


def _get_user_row(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()


def _get_default_tree_id(connection: sqlite3.Connection, user_id: int) -> int:
    settings = connection.execute(
        'SELECT default_tree_id FROM user_settings WHERE user_id = ? LIMIT 1', (user_id,)
    ).fetchone()
    if settings and settings['default_tree_id']:
        return int(settings['default_tree_id'])

    tree_row = connection.execute(
        'SELECT id FROM family_trees WHERE owner_user_id = ? ORDER BY id ASC LIMIT 1', (user_id,)
    ).fetchone()
    if tree_row:
        return int(tree_row['id'])

    now = utcnow_sql()
    cursor = connection.execute(
        """
        INSERT INTO family_trees (owner_user_id, title, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, 'Основное семейное древо', None, now, now),
    )
    tree_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT OR IGNORE INTO tree_memberships (tree_id, user_id, role, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (tree_id, user_id, 'owner', now),
    )
    connection.execute(
        """
        INSERT INTO user_settings (
            user_id, onboarding_completed, privacy_consented, pin_enabled, pin_hash,
            tree_template, api_base_url, theme, app_lock_by_session, device_id,
            default_tree_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            default_tree_id = excluded.default_tree_id,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            1,
            1,
            0,
            None,
            'modern',
            '/api',
            'system',
            0,
            None,
            tree_id,
            now,
            now,
        ),
    )
    connection.commit()
    return tree_id


def _ensure_user_settings(
    connection: sqlite3.Connection, user_id: int, device_id: str | None = None
) -> int:
    tree_id = _get_default_tree_id(connection, user_id)
    row = connection.execute(
        'SELECT id, device_id FROM user_settings WHERE user_id = ? LIMIT 1', (user_id,)
    ).fetchone()
    now = utcnow_sql()
    if row:
        if device_id and not row['device_id']:
            connection.execute(
                'UPDATE user_settings SET device_id = ?, updated_at = ? WHERE id = ?',
                (int(device_id), now, row['id']),
            )
            connection.commit()
        return tree_id

    connection.execute(
        """
        INSERT INTO user_settings (
            user_id, onboarding_completed, privacy_consented, pin_enabled, pin_hash,
            tree_template, api_base_url, theme, app_lock_by_session, device_id,
            default_tree_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            1,
            1,
            0,
            None,
            'modern',
            '/api',
            'system',
            0,
            int(device_id) if device_id else None,
            tree_id,
            now,
            now,
        ),
    )
    connection.commit()
    return tree_id


def ensure_local_user(
    db_path: Path, device_id: str, display_name: str | None = None
) -> dict[str, Any]:
    normalized_device_id = str(device_id or '').strip()
    if not normalized_device_id:
        raise ValueError('Device ID is required')

    device_key = f'device:{normalized_device_id}'
    connection = db_connect(db_path)
    try:
        user = _query_user_by_identity(connection, 'local', device_key)
        now = utcnow_sql()
        normalized_display_name = (display_name or DEFAULT_DISPLAY_NAME).strip() or DEFAULT_DISPLAY_NAME

        if user is None:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    display_name, email, phone, preferred_auth_provider,
                    last_login_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (normalized_display_name, None, None, 'local', now, now, now),
            )
            user_id = int(cursor.lastrowid)
            tree_id = _get_default_tree_id(connection, user_id)
            connection.execute(
                """
                INSERT INTO auth_identities (
                    user_id, provider, provider_user_id, email, phone,
                    display_name, avatar_url, profile_json, last_login_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    'local',
                    device_key,
                    None,
                    None,
                    normalized_display_name,
                    None,
                    None,
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO tree_memberships (tree_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (tree_id, user_id, 'owner', now),
            )
            _ensure_user_settings(connection, user_id, normalized_device_id)
            connection.commit()
            user = _get_user_row(connection, user_id)
        else:
            user_id = int(user['id'])
            _ensure_user_settings(connection, user_id, normalized_device_id)
            connection.execute(
                'UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?',
                (now, now, user_id),
            )
            connection.execute(
                """
                UPDATE auth_identities
                SET last_login_at = ?, updated_at = ?, display_name = COALESCE(display_name, ?)
                WHERE provider = 'local' AND provider_user_id = ?
                """,
                (now, now, normalized_display_name, device_key),
            )
            connection.commit()

        return get_auth_snapshot(db_path, int(user['id']))
    finally:
        connection.close()


def _ensure_local_identity_link(
    connection: sqlite3.Connection, user_id: int, device_id: str, display_name: str | None = None
) -> None:
    device_key = f'device:{device_id}'
    now = utcnow_sql()
    row = connection.execute(
        """
        SELECT id FROM auth_identities
        WHERE provider = 'local' AND provider_user_id = ?
        LIMIT 1
        """,
        (device_key,),
    ).fetchone()
    if row:
        connection.execute(
            """
            UPDATE auth_identities
            SET user_id = ?, display_name = ?, last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (user_id, display_name or DEFAULT_DISPLAY_NAME, now, now, row['id']),
        )
        return

    connection.execute(
        """
        INSERT INTO auth_identities (
            user_id, provider, provider_user_id, email, phone,
            display_name, avatar_url, profile_json, last_login_at,
            created_at, updated_at
        )
        VALUES (?, 'local', ?, NULL, NULL, ?, NULL, NULL, ?, ?, ?)
        """,
        (user_id, device_key, display_name or DEFAULT_DISPLAY_NAME, now, now, now),
    )


def attach_yandex_identity(db_path: Path, device_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    normalized_device_id = str(device_id or '').strip()
    if not normalized_device_id:
        raise ValueError('Device ID is required')

    provider_user_id = str(profile.get('id') or profile.get('psuid') or profile.get('login') or '').strip()
    if not provider_user_id:
        raise ValueError('Yandex profile does not contain a stable user id')

    display_name = (
        str(profile.get('real_name') or profile.get('display_name') or profile.get('login') or '').strip()
        or DEFAULT_DISPLAY_NAME
    )
    email = str(profile.get('default_email') or '').strip() or None
    phone = str(profile.get('default_phone') or '').strip() or None
    avatar_url = str(profile.get('default_avatar_id') or '').strip() or None

    local_snapshot = ensure_local_user(db_path, normalized_device_id, display_name)
    local_user_id = int(local_snapshot['user']['id'])

    connection = db_connect(db_path)
    try:
        now = utcnow_sql()
        existing_identity = connection.execute(
            """
            SELECT * FROM auth_identities
            WHERE provider = 'yandex' AND provider_user_id = ?
            LIMIT 1
            """,
            (provider_user_id,),
        ).fetchone()
        target_user_id = int(existing_identity['user_id']) if existing_identity else local_user_id

        _ensure_user_settings(connection, target_user_id, normalized_device_id)
        _ensure_local_identity_link(connection, target_user_id, normalized_device_id, display_name)

        profile_json = json.dumps(profile, ensure_ascii=False)
        if existing_identity:
            connection.execute(
                """
                UPDATE auth_identities
                SET user_id = ?, email = ?, phone = ?, display_name = ?,
                    avatar_url = ?, profile_json = ?, last_login_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    target_user_id,
                    email,
                    phone,
                    display_name,
                    avatar_url,
                    profile_json,
                    now,
                    now,
                    existing_identity['id'],
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO auth_identities (
                    user_id, provider, provider_user_id, email, phone,
                    display_name, avatar_url, profile_json, last_login_at,
                    created_at, updated_at
                )
                VALUES (?, 'yandex', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_user_id,
                    provider_user_id,
                    email,
                    phone,
                    display_name,
                    avatar_url,
                    profile_json,
                    now,
                    now,
                    now,
                ),
            )

        connection.execute(
            """
            UPDATE users
            SET display_name = ?, email = ?, phone = ?, preferred_auth_provider = 'yandex',
                last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (display_name, email, phone, now, now, target_user_id),
        )
        connection.commit()
        return get_auth_snapshot(db_path, target_user_id)
    finally:
        connection.close()


def get_auth_snapshot(db_path: Path, user_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        user = _get_user_row(connection, user_id)
        if user is None:
            raise ValueError(f'User {user_id} not found')

        identities = connection.execute(
            """
            SELECT provider, provider_user_id, email, phone, display_name, avatar_url
            FROM auth_identities
            WHERE user_id = ?
            ORDER BY
                CASE provider
                    WHEN 'yandex' THEN 1
                    WHEN 'vk' THEN 2
                    ELSE 9
                END,
                id ASC
            """,
            (user_id,),
        ).fetchall()
        providers = [
            {
                'provider': row['provider'],
                'providerUserId': row['provider_user_id'],
                'displayName': row['display_name'],
                'email': row['email'],
                'phone': row['phone'],
                'avatarUrl': row['avatar_url'],
                'connected': True,
            }
            for row in identities
        ]
        return {
            'user': {
                'id': int(user['id']),
                'displayName': user['display_name'],
                'email': user['email'],
                'preferredAuthProvider': user['preferred_auth_provider'],
                'providers': providers,
            }
        }
    finally:
        connection.close()


def resolve_user_snapshot(
    db_path: Path,
    device_id: str | None = None,
    session_user_id: int | None = None,
    display_name: str | None = None,
    allow_create: bool = False,
) -> dict[str, Any] | None:
    normalized_device_id = str(device_id or '').strip()

    if normalized_device_id:
        if allow_create:
            return ensure_local_user(db_path, normalized_device_id, display_name)
        device_key = f'device:{normalized_device_id}'
        connection = db_connect(db_path)
        try:
            user = _query_user_by_identity(connection, 'local', device_key)
            if user:
                return get_auth_snapshot(db_path, int(user['id']))
        finally:
            connection.close()

    if session_user_id:
        try:
            return get_auth_snapshot(db_path, int(session_user_id))
        except Exception:
            return None

    return None


def get_user_id_for_request(
    db_path: Path,
    device_id: str | None = None,
    session_user_id: int | None = None,
    display_name: str | None = None,
    allow_create: bool = False,
) -> int | None:
    snapshot = resolve_user_snapshot(
        db_path,
        device_id=device_id,
        session_user_id=session_user_id,
        display_name=display_name,
        allow_create=allow_create,
    )
    if snapshot:
        return int(snapshot['user']['id'])
    return None


def resolve_storage_path(base_dir: Path, storage_path: str) -> Path:
    candidate = Path(storage_path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def _get_backup_row(connection: sqlite3.Connection, tree_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM backup_snapshots
        WHERE tree_id = ?
        ORDER BY datetime(updated_at) DESC, id DESC
        LIMIT 1
        """,
        (tree_id,),
    ).fetchone()


def _make_backup_meta(row: sqlite3.Row | None, exists: bool) -> dict[str, Any]:
    if row is None or not exists:
        return {
            'success': True,
            'exists': False,
            'schemaVersion': 1,
        }

    return {
        'success': True,
        'exists': True,
        'schemaVersion': int(row['schema_version']),
        'createdAtUtc': row['created_at'].replace(' ', 'T') + 'Z' if row['created_at'] else None,
        'updatedAtUtc': row['updated_at'].replace(' ', 'T') + 'Z' if row['updated_at'] else None,
        'compression': row['compression'],
        'sizeBytes': int(row['size_bytes']) if row['size_bytes'] is not None else None,
        'membersCount': int(row['members_count']) if row['members_count'] is not None else None,
        'memberPhotosCount': int(row['member_photos_count']) if row['member_photos_count'] is not None else None,
        'assetsCount': int(row['assets_count']) if row['assets_count'] is not None else None,
        'checksumSha256': row['checksum_sha256'],
    }


def get_backup_meta(db_path: Path, base_dir: Path, user_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        tree_id = _get_default_tree_id(connection, user_id)
        row = _get_backup_row(connection, tree_id)
        if row is None:
            return _make_backup_meta(None, False)

        absolute_path = resolve_storage_path(base_dir, row['storage_path'])
        if not absolute_path.exists():
            return _make_backup_meta(row, False)

        return _make_backup_meta(row, True)
    finally:
        connection.close()


def parse_backup_manifest(archive_bytes: bytes) -> dict[str, Any]:
    checksum = hashlib.sha256(archive_bytes).hexdigest()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        try:
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
        except KeyError as error:
            raise ValueError('Backup archive does not contain manifest.json') from error
        except Exception as error:
            raise ValueError('Backup archive manifest is invalid') from error

    counts = manifest.get('counts') or {}
    return {
        'schemaVersion': int(manifest.get('schemaVersion') or 1),
        'createdAtUtc': manifest.get('createdAtUtc') or utcnow_iso(),
        'updatedAtUtc': manifest.get('createdAtUtc') or utcnow_iso(),
        'compression': manifest.get('compression') or 'zip',
        'membersCount': int(counts.get('members') or 0),
        'memberPhotosCount': int(counts.get('memberPhotos') or 0),
        'assetsCount': int(counts.get('assets') or 0),
        'checksumSha256': manifest.get('checksumSha256') or checksum,
    }


def _audit_log(connection: sqlite3.Connection, tree_id: int, user_id: int, action: str, details: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO audit_logs (
            tree_id, user_id, action, entity_type, entity_id, details_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tree_id, user_id, action, 'backup', None, json.dumps(details, ensure_ascii=False), utcnow_sql()),
    )


def store_backup(db_path: Path, base_dir: Path, user_id: int, archive_bytes: bytes) -> dict[str, Any]:
    meta = parse_backup_manifest(archive_bytes)
    connection = db_connect(db_path)
    try:
        tree_id = _get_default_tree_id(connection, user_id)
        row = _get_backup_row(connection, tree_id)
        if row is not None:
            relative_path = row['storage_path']
        else:
            folder_hash = hashlib.sha1(f'user:{user_id}'.encode('utf-8')).hexdigest()[:24]
            relative_path = os.path.join('backup_storage_sql', folder_hash, 'latest.zip')

        absolute_path = resolve_storage_path(base_dir, relative_path)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(archive_bytes)

        now = utcnow_sql()
        size_bytes = len(archive_bytes)
        if row is not None:
            connection.execute(
                """
                UPDATE backup_snapshots
                SET created_by_user_id = ?, storage_path = ?, checksum_sha256 = ?,
                    size_bytes = ?, schema_version = ?, compression = ?, members_count = ?,
                    member_photos_count = ?, assets_count = ?, source = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    user_id,
                    relative_path,
                    meta['checksumSha256'],
                    size_bytes,
                    meta['schemaVersion'],
                    meta['compression'],
                    meta['membersCount'],
                    meta['memberPhotosCount'],
                    meta['assetsCount'],
                    'upload',
                    now,
                    row['id'],
                ),
            )
            created_at = row['created_at']
        else:
            connection.execute(
                """
                INSERT INTO backup_snapshots (
                    tree_id, created_by_user_id, storage_path, checksum_sha256, size_bytes,
                    schema_version, compression, members_count, member_photos_count,
                    assets_count, source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tree_id,
                    user_id,
                    relative_path,
                    meta['checksumSha256'],
                    size_bytes,
                    meta['schemaVersion'],
                    meta['compression'],
                    meta['membersCount'],
                    meta['memberPhotosCount'],
                    meta['assetsCount'],
                    'upload',
                    now,
                    now,
                ),
            )
            created_at = now

        response_meta = {
            'success': True,
            'exists': True,
            'schemaVersion': meta['schemaVersion'],
            'createdAtUtc': meta['createdAtUtc'] or created_at.replace(' ', 'T') + 'Z',
            'updatedAtUtc': meta['updatedAtUtc'] or now.replace(' ', 'T') + 'Z',
            'compression': meta['compression'],
            'sizeBytes': size_bytes,
            'membersCount': meta['membersCount'],
            'memberPhotosCount': meta['memberPhotosCount'],
            'assetsCount': meta['assetsCount'],
            'checksumSha256': meta['checksumSha256'],
        }
        _audit_log(connection, tree_id, user_id, 'backup_upload', response_meta)
        connection.commit()
        return response_meta
    finally:
        connection.close()


def load_backup_path(db_path: Path, base_dir: Path, user_id: int) -> Path:
    connection = db_connect(db_path)
    try:
        tree_id = _get_default_tree_id(connection, user_id)
        row = _get_backup_row(connection, tree_id)
        if row is None:
            raise FileNotFoundError('Backup not found')
        absolute_path = resolve_storage_path(base_dir, row['storage_path'])
        if not absolute_path.exists():
            raise FileNotFoundError('Backup not found')
        return absolute_path
    finally:
        connection.close()


def delete_backup(db_path: Path, base_dir: Path, user_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        tree_id = _get_default_tree_id(connection, user_id)
        row = _get_backup_row(connection, tree_id)
        if row is None:
            return {'success': True, 'schemaVersion': 1, 'deleted': False}

        absolute_path = resolve_storage_path(base_dir, row['storage_path'])
        deleted = False
        if absolute_path.exists():
            absolute_path.unlink()
            deleted = True
            try:
                absolute_path.parent.rmdir()
            except OSError:
                pass

        connection.execute('DELETE FROM backup_snapshots WHERE id = ?', (row['id'],))
        _audit_log(
            connection,
            tree_id,
            user_id,
            'backup_delete',
            {'success': True, 'schemaVersion': int(row['schema_version']), 'deleted': deleted},
        )
        connection.commit()
        return {'success': True, 'schemaVersion': int(row['schema_version']), 'deleted': deleted}
    finally:
        connection.close()
