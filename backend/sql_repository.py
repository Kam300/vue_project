from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
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


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _table_exists(connection, table_name):
        return False
    cursor = connection.execute(f"PRAGMA table_info({table_name})")
    for row in cursor.fetchall():
        # row[1] is the column name regardless of row_factory because PRAGMA returns tuples
        try:
            name = row['name']  # type: ignore[index]
        except Exception:
            name = row[1]
        if name == column_name:
            return True
    return False


def _migration_001_backup_snapshots_last_change_ids(connection: sqlite3.Connection) -> None:
    """Add last_change_ids_json TEXT to backup_snapshots (idempotent)."""
    if not _table_exists(connection, 'backup_snapshots'):
        return
    if _column_exists(connection, 'backup_snapshots', 'last_change_ids_json'):
        return
    connection.execute(
        'ALTER TABLE backup_snapshots ADD COLUMN last_change_ids_json TEXT'
    )


def _migration_002_users_single_session_enabled(connection: sqlite3.Connection) -> None:
    """Add single_session_enabled INTEGER NOT NULL DEFAULT 1 to users (idempotent)."""
    if not _table_exists(connection, 'users'):
        return
    if _column_exists(connection, 'users', 'single_session_enabled'):
        return
    connection.execute(
        'ALTER TABLE users ADD COLUMN single_session_enabled INTEGER NOT NULL DEFAULT 1'
    )


def _migration_003_auth_sessions_create(connection: sqlite3.Connection) -> None:
    """Create auth_sessions table and supporting indexes (idempotent)."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_id       TEXT    NOT NULL,
            token_hash      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL,
            expires_at      TEXT    NOT NULL,
            revoked_at      TEXT,
            revoked_reason  TEXT,
            UNIQUE (token_hash)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active
            ON auth_sessions(user_id) WHERE revoked_at IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_device
            ON auth_sessions(user_id, device_id)
        """
    )


def run_migrations(db_path: Path) -> None:
    """Run additive, idempotent schema migrations for multi-device sync safety.

    Migrations are applied in order:
      001_backup_snapshots_last_change_ids
      002_users_single_session_enabled
      003_auth_sessions_create

    Safe to invoke repeatedly: every step uses IF NOT EXISTS or PRAGMA-based
    guards so a fresh DB and an existing DB converge to the same target schema.
    """
    connection = db_connect(Path(db_path))
    try:
        connection.execute('BEGIN')
        _migration_001_backup_snapshots_last_change_ids(connection)
        _migration_002_users_single_session_enabled(connection)
        _migration_003_auth_sessions_create(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def compute_server_version_tag(updated_at_sql: str, checksum_sha256: str) -> str:
    """Compute the opaque ``Server_Version_Tag`` for a backup snapshot.

    Pure deterministic function: same inputs always produce the same output.

    The tag is ``sha256(updated_at_sql || "|" || checksum_sha256)`` encoded as
    a 64-character lowercase hex string. ``updated_at_sql`` is the value stored
    in ``backup_snapshots.updated_at`` (e.g. ``'YYYY-MM-DD HH:MM:SS.ffffff'``)
    and ``checksum_sha256`` is the 64-lowercase-hex SHA-256 of the archive.
    """
    payload = f"{updated_at_sql}|{checksum_sha256}".encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def parse_capabilities(req: Any) -> set[str]:
    """Parse the ``X-Client-Capabilities`` header into a lowercase token set.

    Tokens are comma-separated, whitespace-trimmed, and case-folded. An absent
    or empty header yields an empty set. ``req`` is any object exposing a
    ``headers`` mapping with a ``get`` method (e.g. a Flask ``Request``).
    """
    raw = ''
    headers = getattr(req, 'headers', None)
    if headers is not None:
        try:
            raw = headers.get('X-Client-Capabilities', '') or ''
        except Exception:
            raw = ''
    return {tok.strip().lower() for tok in raw.split(',') if tok.strip()}


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

    connection = db_connect(db_path)
    try:
        now = utcnow_sql()

        # 1) Уже есть Yandex-identity → берём её user_id
        existing_yandex = connection.execute(
            """
            SELECT * FROM auth_identities
            WHERE provider = 'yandex' AND provider_user_id = ?
            LIMIT 1
            """,
            (provider_user_id,),
        ).fetchone()

        target_user_id: int
        if existing_yandex:
            target_user_id = int(existing_yandex['user_id'])
        else:
            # 2) Есть гостевой local-user по device_id → апгрейдим его
            device_key = f'device:{normalized_device_id}'
            existing_local = connection.execute(
                """
                SELECT user_id FROM auth_identities
                WHERE provider = 'local' AND provider_user_id = ?
                LIMIT 1
                """,
                (device_key,),
            ).fetchone()

            if existing_local:
                target_user_id = int(existing_local['user_id'])
            else:
                # 3) Создаём нового user сразу с yandex (без local-фолбэка)
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        display_name, email, phone, preferred_auth_provider,
                        last_login_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'yandex', ?, ?, ?)
                    """,
                    (display_name, email, phone, now, now, now),
                )
                target_user_id = int(cursor.lastrowid)

        _ensure_user_settings(connection, target_user_id, normalized_device_id)

        profile_json = json.dumps(profile, ensure_ascii=False)
        if existing_yandex:
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
                    existing_yandex['id'],
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

        # Ensure ровно одна local-identity для этого device_id (для bootstrap по deviceId).
        # Не создаёт дубли — INSERT OR IGNORE по UNIQUE(provider, provider_user_id).
        device_key = f'device:{normalized_device_id}'
        connection.execute(
            """
            INSERT OR IGNORE INTO auth_identities (
                user_id, provider, provider_user_id, email, phone,
                display_name, avatar_url, profile_json, last_login_at,
                created_at, updated_at
            )
            VALUES (?, 'local', ?, NULL, NULL, ?, NULL, NULL, ?, ?, ?)
            """,
            (target_user_id, device_key, display_name, now, now, now),
        )
        # Если local-запись уже есть, но привязана к другому user — перепривязываем
        connection.execute(
            """
            UPDATE auth_identities
            SET user_id = ?, last_login_at = ?, updated_at = ?
            WHERE provider = 'local' AND provider_user_id = ? AND user_id != ?
            """,
            (target_user_id, now, now, device_key, target_user_id),
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
                'isAdmin': bool(user['is_admin']) if 'is_admin' in user.keys() else False,
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
    """Build the backup-meta payload for a snapshot row.

    The payload always carries a ``serverVersionTag`` key so clients can rely on
    its presence regardless of whether a snapshot exists:

    * ``exists=True``  -> ``serverVersionTag = compute_server_version_tag(
      row['updated_at'], row['checksum_sha256'])`` (deterministic, stable
      across reads with no intervening upload — Requirement 4.3).
    * ``exists=False`` -> ``serverVersionTag = None`` (explicitly null rather
      than omitted to keep the response shape uniform; clients treat ``null``
      the same as "no snapshot ever observed").
    """
    if row is None or not exists:
        return {
            'success': True,
            'exists': False,
            'schemaVersion': 1,
            'serverVersionTag': None,
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
        'serverVersionTag': compute_server_version_tag(
            row['updated_at'], row['checksum_sha256']
        ),
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


def issue_session(
    connection: sqlite3.Connection,
    user_id: int,
    device_id: str,
    *,
    ttl_days: int = 30,
) -> str:
    """Issue a new auth session token, enforcing single-session if enabled.

    Returns the raw token (only sha256(token) is persisted). Caller is
    responsible for transaction management — this helper does NOT commit.

    Behaviour (design.md §3.4):
      * Lookup the user's ``single_session_enabled`` flag.
      * If enabled, atomically revoke every currently-active session for the
        user (including any prior session for the same ``device_id``) with
        ``revoked_reason='signed_in_on_other_device'`` and append one
        ``audit_logs(action='session_revoked')`` row per revoked session.
      * Insert the new ``auth_sessions`` row and return the raw token.

    Raises ``ValueError`` if ``user_id`` does not exist.

    Satisfies Requirements 5.2, 5.7, 6.1, 6.2, 6.3, 14.4.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = utcnow_sql()
    expires = (
        (datetime.now(timezone.utc) + timedelta(days=ttl_days))
        .replace(tzinfo=None)
        .isoformat(sep=' ')
    )

    user_row = connection.execute(
        'SELECT single_session_enabled FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    if user_row is None:
        raise ValueError(f'unknown user_id={user_id}')
    single_session = bool(user_row['single_session_enabled'])

    if single_session:
        revoked_rows = connection.execute(
            'SELECT id, device_id FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?',
            (user_id, now),
        ).fetchall()
        if revoked_rows:
            connection.execute(
                "UPDATE auth_sessions "
                "SET revoked_at = ?, revoked_reason = 'signed_in_on_other_device' "
                "WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?",
                (now, user_id, now),
            )
            tree_id = _get_default_tree_id(connection, user_id)
            for r in revoked_rows:
                _audit_log(
                    connection,
                    tree_id,
                    user_id,
                    'session_revoked',
                    {
                        'device_id': r['device_id'],
                        'revoked_reason': 'signed_in_on_other_device',
                    },
                )

    connection.execute(
        'INSERT INTO auth_sessions '
        '(user_id, device_id, token_hash, created_at, expires_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (user_id, device_id, token_hash, now, expires),
    )
    return raw_token


def store_backup(
    db_path: Path,
    base_dir: Path,
    user_id: int,
    archive_bytes: bytes,
    *,
    if_match: str | None = None,
    force: bool = True,
    capabilities: set[str] | None = None,
    require_if_match: bool = False,
    last_change_ids: list[str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Persist a backup archive with optimistic-concurrency semantics.

    Implements the decision table from design.md §3.3 (Requirements 1.3–1.10,
    14.1–14.3, 15.1–15.3). Returns ``(body_dict, status_int)``.

    The keyword-only defaults are intentionally permissive (``force=True``,
    ``require_if_match=False``) so legacy positional callers retain the
    previous last-writer-wins behaviour until task 2.2 wires the Flask
    wrapper. Every successful response includes ``serverVersionTag`` and
    ``previousServerVersionTag`` (``None`` for the first snapshot).
    """
    meta = parse_backup_manifest(archive_bytes)
    caps = capabilities or set()
    last_change_ids_json = (
        json.dumps(list(last_change_ids)) if last_change_ids is not None else None
    )

    connection = db_connect(db_path)
    try:
        # Tree-id resolution may commit when bootstrapping a new user; resolve
        # it before BEGIN IMMEDIATE so the explicit transaction below is the
        # only writer holding the RESERVED lock.
        tree_id = _get_default_tree_id(connection, user_id)
        connection.execute('BEGIN IMMEDIATE')  # Req 1.9 — row-level write lock

        row = _get_backup_row(connection, tree_id)
        current_tag = (
            compute_server_version_tag(row['updated_at'], row['checksum_sha256'])
            if row is not None
            else None
        )
        legacy = 'if-match-v1' not in caps

        # ---- precondition gates ---------------------------------------------
        # Req 15.3: legacy clients can NEVER overwrite an existing snapshot,
        # not even with force=true. This gate runs BEFORE the force short-
        # circuit so legacy + force=true + exists still returns 426.
        if require_if_match and legacy and row is not None:
            payload = _make_backup_meta(row, True)
            payload['error'] = 'client_upgrade_required'
            connection.rollback()
            return (payload, 426)

        # 428 / 409 gates apply only to strict clients and are skipped on
        # force=true (Req 1.8). Legacy first-snapshot also flows through here.
        if not force and require_if_match and not legacy:
            if row is not None:
                if if_match is None:
                    # Req 1.5
                    payload = _make_backup_meta(row, True)
                    payload['error'] = 'precondition_required'
                    connection.rollback()
                    return (payload, 428)
                if if_match == '*' or if_match != current_tag:
                    # Req 1.4 / 1.7 — and Req 14.1 audit row.
                    _audit_log(
                        connection,
                        tree_id,
                        user_id,
                        'backup_conflict_rejected',
                        {'if_match': if_match, 'current': current_tag},
                    )
                    payload = _make_backup_meta(row, True)
                    payload['error'] = 'conflict'
                    connection.commit()
                    return (payload, 409)
            # row is None: accept as first snapshot (Req 1.6 covers If-Match: *).

        previous_tag = current_tag

        # ---- determine storage path -----------------------------------------
        if row is not None:
            relative_path = row['storage_path']
        else:
            folder_hash = hashlib.sha1(f'user:{user_id}'.encode('utf-8')).hexdigest()[:24]
            relative_path = os.path.join('backup_storage_sql', folder_hash, 'latest.zip')

        absolute_path = resolve_storage_path(base_dir, relative_path)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = absolute_path.with_suffix(absolute_path.suffix + '.tmp')

        try:
            # Stage the archive bytes next to the destination so the on-disk
            # publish can be made atomic (os.replace) only after SQL commit.
            temp_path.write_bytes(archive_bytes)

            now = utcnow_sql()
            size_bytes = len(archive_bytes)
            if row is not None:
                connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET created_by_user_id = ?, storage_path = ?, checksum_sha256 = ?,
                        size_bytes = ?, schema_version = ?, compression = ?, members_count = ?,
                        member_photos_count = ?, assets_count = ?, source = ?, updated_at = ?,
                        last_change_ids_json = ?
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
                        last_change_ids_json,
                        row['id'],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO backup_snapshots (
                        tree_id, created_by_user_id, storage_path, checksum_sha256, size_bytes,
                        schema_version, compression, members_count, member_photos_count,
                        assets_count, source, created_at, updated_at, last_change_ids_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        last_change_ids_json,
                    ),
                )

            new_tag = compute_server_version_tag(now, meta['checksumSha256'])

            if force:
                try:
                    _audit_log(
                        connection,
                        tree_id,
                        user_id,
                        'backup_force_overwrite',
                        {'previous': previous_tag, 'new': new_tag},
                    )
                except Exception:
                    # Req 14.3 — leave the snapshot unchanged.
                    connection.rollback()
                    try:
                        if temp_path.exists():
                            temp_path.unlink()
                    except Exception:
                        pass
                    return (
                        {
                            'error': 'audit_unavailable',
                            'serverVersionTag': previous_tag,
                        },
                        503,
                    )

            connection.commit()

            # Atomic on-disk publish AFTER the SQL transaction is durable so a
            # rolled-back transaction never leaves a half-written archive
            # under the storage_path referenced by the snapshot row.
            os.replace(str(temp_path), str(absolute_path))

            new_row = _get_backup_row(connection, tree_id)
            response = _make_backup_meta(new_row, True)
            response['previousServerVersionTag'] = previous_tag
            return (response, 200)
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            raise
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



# ============================================================
# ADMIN
# ============================================================

def is_user_admin(db_path: Path, user_id: int) -> bool:
    connection = db_connect(db_path)
    try:
        row = connection.execute(
            'SELECT is_admin FROM users WHERE id = ? LIMIT 1', (user_id,)
        ).fetchone()
        return bool(row and row['is_admin'])
    finally:
        connection.close()


def get_admin_stats(db_path: Path, base_dir: Path) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        def count(table: str) -> int:
            try:
                row = connection.execute(f'SELECT COUNT(*) AS c FROM {table}').fetchone()
                return int(row['c']) if row else 0
            except sqlite3.OperationalError:
                return 0

        users_total = count('users')
        admins_total = int(connection.execute(
            'SELECT COUNT(*) AS c FROM users WHERE is_admin = 1'
        ).fetchone()['c'])

        backup_storage = base_dir / 'backup_storage_sql'
        backup_files = []
        backup_total_bytes = 0
        if backup_storage.exists():
            for path in backup_storage.rglob('*.zip'):
                try:
                    size = path.stat().st_size
                    backup_total_bytes += size
                    backup_files.append({
                        'path': str(path.relative_to(base_dir)),
                        'size': size,
                        'mtime': datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
                    })
                except OSError:
                    continue

        db_size = 0
        try:
            db_size = db_path.stat().st_size
        except OSError:
            pass

        return {
            'users': {
                'total': users_total,
                'admins': admins_total,
            },
            'persons': count('persons'),
            'photos': count('photos'),
            'relationships': count('relationships'),
            'family_trees': count('family_trees'),
            'backups': {
                'count': count('backup_snapshots'),
                'total_bytes': backup_total_bytes,
                'files': len(backup_files),
            },
            'database': {
                'path': str(db_path),
                'size_bytes': db_size,
            },
            'audit_logs': count('audit_logs'),
            'face_encodings': count('face_encodings'),
        }
    finally:
        connection.close()


def list_users_admin(db_path: Path) -> list[dict[str, Any]]:
    connection = db_connect(db_path)
    try:
        rows = connection.execute("""
            SELECT u.id, u.display_name, u.email, u.phone, u.preferred_auth_provider,
                   u.is_admin, u.last_login_at, u.created_at,
                   (SELECT GROUP_CONCAT(provider, ',') FROM auth_identities WHERE user_id = u.id) AS providers,
                   (SELECT COUNT(*) FROM persons p
                    JOIN family_trees t ON t.id = p.tree_id
                    WHERE t.owner_user_id = u.id) AS persons_count,
                   (SELECT COUNT(*) FROM backup_snapshots b
                    JOIN family_trees t ON t.id = b.tree_id
                    WHERE t.owner_user_id = u.id) AS backups_count
            FROM users u
            ORDER BY u.created_at DESC
        """).fetchall()
        return [
            {
                'id': int(row['id']),
                'displayName': row['display_name'],
                'email': row['email'],
                'phone': row['phone'],
                'preferredAuthProvider': row['preferred_auth_provider'],
                'isAdmin': bool(row['is_admin']),
                'lastLoginAt': row['last_login_at'],
                'createdAt': row['created_at'],
                'providers': (row['providers'] or '').split(',') if row['providers'] else [],
                'personsCount': int(row['persons_count'] or 0),
                'backupsCount': int(row['backups_count'] or 0),
            }
            for row in rows
        ]
    finally:
        connection.close()


def set_user_admin(db_path: Path, user_id: int, is_admin: bool) -> None:
    connection = db_connect(db_path)
    try:
        connection.execute(
            'UPDATE users SET is_admin = ?, updated_at = ? WHERE id = ?',
            (1 if is_admin else 0, utcnow_sql(), user_id),
        )
        connection.commit()
    finally:
        connection.close()


def delete_user_admin(db_path: Path, base_dir: Path, user_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        row = connection.execute(
            'SELECT is_admin FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if row is None:
            return {'success': False, 'error': 'User not found'}
        if row['is_admin']:
            return {'success': False, 'error': 'Cannot delete admin user'}

        backup_rows = connection.execute("""
            SELECT b.storage_path FROM backup_snapshots b
            JOIN family_trees t ON t.id = b.tree_id
            WHERE t.owner_user_id = ?
        """, (user_id,)).fetchall()

        for br in backup_rows:
            try:
                p = resolve_storage_path(base_dir, br['storage_path'])
                if p.exists():
                    p.unlink()
                    try:
                        p.parent.rmdir()
                    except OSError:
                        pass
            except OSError:
                pass

        connection.execute('DELETE FROM users WHERE id = ?', (user_id,))
        connection.commit()
        return {'success': True}
    finally:
        connection.close()


def list_all_backups_admin(db_path: Path, base_dir: Path) -> list[dict[str, Any]]:
    connection = db_connect(db_path)
    try:
        rows = connection.execute("""
            SELECT b.*, u.display_name AS owner_name, u.email AS owner_email,
                   t.title AS tree_title
            FROM backup_snapshots b
            JOIN family_trees t ON t.id = b.tree_id
            LEFT JOIN users u ON u.id = t.owner_user_id
            ORDER BY datetime(b.updated_at) DESC
        """).fetchall()
        result = []
        for row in rows:
            absolute_path = resolve_storage_path(base_dir, row['storage_path'])
            result.append({
                'id': int(row['id']),
                'treeId': int(row['tree_id']),
                'treeTitle': row['tree_title'],
                'ownerUserId': int(row['created_by_user_id']) if row['created_by_user_id'] else None,
                'ownerName': row['owner_name'],
                'ownerEmail': row['owner_email'],
                'storagePath': row['storage_path'],
                'fileExists': absolute_path.exists(),
                'sizeBytes': int(row['size_bytes']) if row['size_bytes'] is not None else None,
                'membersCount': int(row['members_count']),
                'memberPhotosCount': int(row['member_photos_count']),
                'assetsCount': int(row['assets_count']),
                'compression': row['compression'],
                'checksumSha256': row['checksum_sha256'],
                'source': row['source'],
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at'],
            })
        return result
    finally:
        connection.close()


def delete_backup_admin(db_path: Path, base_dir: Path, backup_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        row = connection.execute(
            'SELECT * FROM backup_snapshots WHERE id = ?', (backup_id,)
        ).fetchone()
        if row is None:
            return {'success': False, 'error': 'Backup not found'}

        absolute_path = resolve_storage_path(base_dir, row['storage_path'])
        deleted = False
        if absolute_path.exists():
            absolute_path.unlink()
            deleted = True
            try:
                absolute_path.parent.rmdir()
            except OSError:
                pass

        connection.execute('DELETE FROM backup_snapshots WHERE id = ?', (backup_id,))
        connection.commit()
        return {'success': True, 'deleted': deleted}
    finally:
        connection.close()


def list_audit_logs_admin(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    connection = db_connect(db_path)
    try:
        rows = connection.execute("""
            SELECT a.*, u.display_name AS user_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY datetime(a.created_at) DESC
            LIMIT ?
        """, (int(limit),)).fetchall()
        return [
            {
                'id': int(row['id']),
                'treeId': int(row['tree_id']),
                'userId': int(row['user_id']) if row['user_id'] else None,
                'userName': row['user_name'],
                'action': row['action'],
                'entityType': row['entity_type'],
                'entityId': row['entity_id'],
                'detailsJson': row['details_json'],
                'createdAt': row['created_at'],
            }
            for row in rows
        ]
    finally:
        connection.close()


def list_face_encodings_admin(db_path: Path) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        rows = connection.execute("""
            SELECT fe.id, fe.person_id, fe.external_member_id, fe.model_version,
                   fe.is_active, fe.reference_photo_path, fe.created_at,
                   p.first_name, p.last_name
            FROM face_encodings fe
            LEFT JOIN persons p ON p.id = fe.person_id
            ORDER BY datetime(fe.created_at) DESC
        """).fetchall()

        encodings = [
            {
                'id': int(row['id']),
                'personId': int(row['person_id']),
                'personName': f"{row['first_name'] or ''} {row['last_name'] or ''}".strip() or None,
                'externalMemberId': row['external_member_id'],
                'modelVersion': row['model_version'],
                'isActive': bool(row['is_active']),
                'referencePhotoPath': row['reference_photo_path'],
                'createdAt': row['created_at'],
            }
            for row in rows
        ]
        return {
            'count': len(encodings),
            'encodings': encodings,
        }
    finally:
        connection.close()



def bulk_delete_users_admin(
    db_path: Path, base_dir: Path, user_ids: list[int], current_admin_id: int
) -> dict[str, Any]:
    """
    Удаляет пользователей из списка. Пропускает админов и текущего админа.
    Возвращает {deleted: int, skipped: list[{id, reason}]}.
    """
    deleted_count = 0
    skipped: list[dict[str, Any]] = []

    for uid in user_ids:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            skipped.append({'id': uid, 'reason': 'invalid_id'})
            continue
        if uid_int == current_admin_id:
            skipped.append({'id': uid_int, 'reason': 'self'})
            continue
        result = delete_user_admin(db_path, base_dir, uid_int)
        if result.get('success'):
            deleted_count += 1
        else:
            skipped.append({'id': uid_int, 'reason': result.get('error', 'unknown')})

    return {'success': True, 'deleted': deleted_count, 'skipped': skipped}



def delete_face_encoding_admin(db_path: Path, face_id: int) -> dict[str, Any]:
    connection = db_connect(db_path)
    try:
        row = connection.execute(
            'SELECT id, reference_photo_path FROM face_encodings WHERE id = ?',
            (face_id,),
        ).fetchone()
        if row is None:
            return {'success': False, 'error': 'Face encoding not found'}

        ref_path = row['reference_photo_path']
        connection.execute('DELETE FROM face_encodings WHERE id = ?', (face_id,))
        connection.commit()

        if ref_path:
            try:
                file_path = Path(ref_path)
                if not file_path.is_absolute():
                    file_path = Path(__file__).parent / file_path
                if file_path.exists():
                    file_path.unlink()
            except OSError:
                pass

        return {'success': True}
    finally:
        connection.close()
