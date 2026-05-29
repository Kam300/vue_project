"""Smoke tests for the bearer-token middleware and PATCH /v2/auth/settings.

Feature: multi-device-sync-safety, design §3.4 / §3.5, tasks 3.3 / 3.4.
Validates Requirements 5.3, 5.5, 5.6, 7.1, 7.2, 8.1, 8.2, 9.3, 9.4, 14.4.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from flask import Flask

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sql_api_v2 import register_sql_api_v2  # noqa: E402
from sql_repository import (  # noqa: E402
    db_connect,
    issue_session,
    utcnow_sql,
)


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


@pytest.fixture()
def app_client(tmp_path: Path):
    base_dir = tmp_path
    # Register the v2 API — this also runs migrations against base_dir/familyone.db.
    app = Flask(__name__)
    register_sql_api_v2(app, base_dir=base_dir)
    db_path = base_dir / 'familyone.db'

    connection = db_connect(db_path)
    try:
        user_id = _create_user(connection, display_name='alice', single_session=1)
        token_a = issue_session(connection, user_id, 'device-A')
        connection.commit()
    finally:
        connection.close()

    return app.test_client(), db_path, user_id, token_a


def test_open_path_does_not_require_token(app_client) -> None:
    client, _db, _uid, _tok = app_client
    resp = client.post('/v2/presence/ping')
    assert resp.status_code == 200


def test_unknown_token_returns_401_session_unknown(app_client) -> None:
    client, _db, _uid, _tok = app_client
    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': True},
        headers={'Authorization': 'Bearer not-a-real-token'},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {'error': 'session_unknown'}


def test_revoked_token_returns_401_session_revoked(app_client) -> None:
    client, db_path, user_id, token_a = app_client

    # Revoke alice's token by re-issuing on a different device with single-session.
    connection = db_connect(db_path)
    try:
        issue_session(connection, user_id, 'device-B')
        connection.commit()
    finally:
        connection.close()

    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': True},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp.status_code == 401
    body = resp.get_json()
    assert body['error'] == 'session_revoked'
    assert body['reason'] == 'signed_in_on_other_device'


def test_expired_token_returns_401_session_expired(app_client) -> None:
    client, db_path, _uid, token_a = app_client

    # Force the session to be expired.
    connection = db_connect(db_path)
    try:
        token_hash = hashlib.sha256(token_a.encode('utf-8')).hexdigest()
        connection.execute(
            "UPDATE auth_sessions SET expires_at = '2000-01-01 00:00:00' "
            'WHERE token_hash = ?',
            (token_hash,),
        )
        connection.commit()
    finally:
        connection.close()

    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': True},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {'error': 'session_expired'}


def test_settings_patch_invalid_payload(app_client) -> None:
    client, _db, _uid, token_a = app_client
    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': 'yes'},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp.status_code == 400
    assert resp.get_json() == {'success': False, 'error': 'invalid_payload'}


def test_settings_patch_disable_single_session_keeps_other_sessions(app_client) -> None:
    client, db_path, user_id, token_a = app_client

    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': False},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {'success': True, 'singleSessionEnabled': False, 'revokedSessions': 0}

    # Confirm the user flag flipped.
    connection = db_connect(db_path)
    try:
        flag = connection.execute(
            'SELECT single_session_enabled FROM users WHERE id = ?', (user_id,)
        ).fetchone()[0]
        assert flag == 0
    finally:
        connection.close()


def test_settings_patch_enable_revokes_other_sessions_and_audits(app_client) -> None:
    client, db_path, user_id, token_a = app_client

    # First disable single-session so we can issue a 2nd active session.
    resp_off = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': False},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp_off.status_code == 200

    connection = db_connect(db_path)
    try:
        issue_session(connection, user_id, 'device-B')
        connection.commit()
    finally:
        connection.close()

    # Now re-enable single-session via alice's session — device-B must be revoked.
    resp = client.patch(
        '/v2/auth/settings',
        json={'singleSessionEnabled': True},
        headers={'Authorization': f'Bearer {token_a}'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['singleSessionEnabled'] is True
    assert body['revokedSessions'] == 1

    connection = db_connect(db_path)
    try:
        active = connection.execute(
            'SELECT device_id FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL',
            (user_id,),
        ).fetchall()
        assert len(active) == 1
        assert active[0]['device_id'] == 'device-A'

        revoked = connection.execute(
            'SELECT device_id, revoked_reason FROM auth_sessions '
            'WHERE user_id = ? AND revoked_at IS NOT NULL',
            (user_id,),
        ).fetchall()
        assert any(
            r['device_id'] == 'device-B'
            and r['revoked_reason'] == 'single_session_re_enabled'
            for r in revoked
        )

        audit = connection.execute(
            "SELECT details_json FROM audit_logs "
            "WHERE user_id = ? AND action = 'session_revoked' "
            "AND details_json LIKE '%single_session_re_enabled%'",
            (user_id,),
        ).fetchall()
        assert len(audit) == 1
        assert 'device-B' in audit[0]['details_json']
    finally:
        connection.close()
