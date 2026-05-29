"""Unit tests for sql_repository.issue_session.

Feature: multi-device-sync-safety, design §3.4 / tasks 3.1.
Validates Requirements 5.2, 5.7, 6.1, 6.2, 6.3, 14.4.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow running from repo root without installation.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sql_repository import (  # noqa: E402
    db_connect,
    issue_session,
    run_migrations,
    utcnow_sql,
)


_BASE_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(64),
    preferred_auth_provider VARCHAR(32) NOT NULL,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE family_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE tree_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE (tree_id, user_id)
);

CREATE TABLE user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    onboarding_completed BOOLEAN NOT NULL DEFAULT 0,
    privacy_consented BOOLEAN NOT NULL DEFAULT 0,
    pin_enabled BOOLEAN NOT NULL DEFAULT 0,
    pin_hash VARCHAR(255),
    tree_template VARCHAR(32) NOT NULL DEFAULT 'default',
    api_base_url VARCHAR(255) NOT NULL DEFAULT '',
    theme VARCHAR(32) NOT NULL DEFAULT 'light',
    app_lock_by_session BOOLEAN NOT NULL DEFAULT 0,
    device_id INTEGER,
    default_tree_id INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64),
    entity_id VARCHAR(128),
    details_json TEXT,
    created_at DATETIME NOT NULL
);

CREATE TABLE backup_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
    file_path VARCHAR(500) NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL,
    compression VARCHAR(32),
    members_count INTEGER NOT NULL DEFAULT 0,
    member_photos_count INTEGER NOT NULL DEFAULT 0,
    assets_count INTEGER NOT NULL DEFAULT 0
);
"""


def _bootstrap_db(db_path: Path) -> None:
    """Create the base schema then run additive migrations."""
    connection = db_connect(db_path)
    try:
        connection.executescript(_BASE_SCHEMA)
        connection.commit()
    finally:
        connection.close()
    run_migrations(db_path)


def _create_user(connection, *, display_name: str, single_session: int) -> int:
    now = utcnow_sql()
    cursor = connection.execute(
        'INSERT INTO users (display_name, preferred_auth_provider, '
        'created_at, updated_at, single_session_enabled) VALUES (?, ?, ?, ?, ?)',
        (display_name, 'local', now, now, single_session),
    )
    user_id = int(cursor.lastrowid)
    tree_cursor = connection.execute(
        'INSERT INTO family_trees (owner_user_id, title, created_at, updated_at) '
        'VALUES (?, ?, ?, ?)',
        (user_id, f'Tree of {display_name}', now, now),
    )
    tree_id = int(tree_cursor.lastrowid)
    connection.execute(
        'INSERT INTO tree_memberships (tree_id, user_id, role, created_at) '
        'VALUES (?, ?, ?, ?)',
        (tree_id, user_id, 'owner', now),
    )
    connection.execute(
        'INSERT INTO user_settings (user_id, default_tree_id, created_at, updated_at) '
        'VALUES (?, ?, ?, ?)',
        (user_id, tree_id, now, now),
    )
    return user_id


def _count_active(connection, user_id: int) -> int:
    return int(
        connection.execute(
            'SELECT COUNT(*) FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NULL',
            (user_id,),
        ).fetchone()[0]
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / 'test_issue_session.db'
    _bootstrap_db(path)
    return path


def test_first_call_leaves_one_active_row(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='alice', single_session=1)
        connection.commit()

        token = issue_session(connection, user_id, 'device-A')
        connection.commit()

        assert isinstance(token, str) and token
        assert _count_active(connection, user_id) == 1
    finally:
        connection.close()


def test_single_session_revokes_other_device(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='bob', single_session=1)
        connection.commit()

        issue_session(connection, user_id, 'device-A')
        connection.commit()

        issue_session(connection, user_id, 'device-B')
        connection.commit()

        active = connection.execute(
            'SELECT device_id FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NULL',
            (user_id,),
        ).fetchall()
        assert len(active) == 1
        assert active[0]['device_id'] == 'device-B'

        revoked = connection.execute(
            'SELECT device_id, revoked_reason FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NOT NULL',
            (user_id,),
        ).fetchall()
        assert len(revoked) == 1
        assert revoked[0]['device_id'] == 'device-A'
        assert revoked[0]['revoked_reason'] == 'signed_in_on_other_device'
    finally:
        connection.close()


def test_multi_session_allows_concurrent_devices(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='carol', single_session=0)
        connection.commit()

        issue_session(connection, user_id, 'device-A')
        connection.commit()

        issue_session(connection, user_id, 'device-B')
        connection.commit()

        assert _count_active(connection, user_id) == 2
    finally:
        connection.close()


def test_single_session_relogin_same_device(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='dave', single_session=1)
        connection.commit()

        issue_session(connection, user_id, 'device-A')
        connection.commit()

        issue_session(connection, user_id, 'device-A')
        connection.commit()

        active_rows = connection.execute(
            'SELECT id, device_id FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NULL',
            (user_id,),
        ).fetchall()
        assert len(active_rows) == 1
        assert active_rows[0]['device_id'] == 'device-A'

        revoked_rows = connection.execute(
            'SELECT revoked_reason FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NOT NULL',
            (user_id,),
        ).fetchall()
        assert len(revoked_rows) == 1
        assert revoked_rows[0]['revoked_reason'] == 'signed_in_on_other_device'
    finally:
        connection.close()


def test_audit_log_row_inserted_on_revocation(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='eve', single_session=1)
        connection.commit()

        issue_session(connection, user_id, 'device-A')
        connection.commit()

        issue_session(connection, user_id, 'device-B')
        connection.commit()

        audit_rows = connection.execute(
            'SELECT action, details_json FROM audit_logs '
            "WHERE user_id = ? AND action = 'session_revoked'",
            (user_id,),
        ).fetchall()
        assert len(audit_rows) == 1
        assert audit_rows[0]['action'] == 'session_revoked'
        assert 'device-A' in audit_rows[0]['details_json']
        assert 'signed_in_on_other_device' in audit_rows[0]['details_json']
    finally:
        connection.close()


def test_unknown_user_raises_value_error(db_path: Path) -> None:
    connection = db_connect(db_path)
    try:
        with pytest.raises(ValueError):
            issue_session(connection, 999_999, 'device-X')
    finally:
        connection.close()
