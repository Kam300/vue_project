# Feature: multi-device-sync-safety, Property 4 / 5 / 6 / 10
"""Property-based tests for auth-session, revoked-token middleware, and audit completeness.

Validates Requirements:
  - 5.2, 5.3, 5.7  — single-session invariant + revoked-token handling
  - 6.1, 6.2, 6.3  — idempotent re-login per (user_id, device_id)
  - 7.1, 7.2       — middleware rejects revoked tokens with matching reason
  - 8.1, 8.2       — middleware applies to all /v2/* except the open set
  - 14.1-14.4      — audit completeness on conflict / force / revoke
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
from flask import Flask
from hypothesis import HealthCheck, assume, given, settings, strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import sql_repository  # noqa: E402
from sql_api_v2 import register_sql_api_v2  # noqa: E402
from sql_repository import (  # noqa: E402
    compute_server_version_tag,
    db_connect,
    issue_session,
    store_backup,
    utcnow_sql,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bootstrap_db(db_path: Path) -> None:
    """Create a minimal schema then run the additive migrations from sql_repository."""
    schema = """
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
        created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        storage_path TEXT NOT NULL,
        checksum_sha256 VARCHAR(128),
        size_bytes INTEGER,
        schema_version INTEGER NOT NULL,
        compression VARCHAR(64),
        members_count INTEGER NOT NULL DEFAULT 0,
        member_photos_count INTEGER NOT NULL DEFAULT 0,
        assets_count INTEGER NOT NULL DEFAULT 0,
        source VARCHAR(32) NOT NULL DEFAULT 'upload',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    );
    """
    connection = db_connect(db_path)
    try:
        connection.executescript(schema)
        connection.commit()
    finally:
        connection.close()
    sql_repository.run_migrations(db_path)


def _create_user(connection, *, display_name: str, single_session: int = 1) -> int:
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
            'WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?',
            (user_id, utcnow_sql()),
        ).fetchone()[0]
    )


def _set_single_session(connection, user_id: int, enabled: bool) -> None:
    connection.execute(
        'UPDATE users SET single_session_enabled = ? WHERE id = ?',
        (1 if enabled else 0, user_id),
    )


def _is_single_session(connection, user_id: int) -> bool:
    row = connection.execute(
        'SELECT single_session_enabled FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    return bool(row[0]) if row else False


def _make_archive(payload_byte: int = 0) -> bytes:
    """Build a minimal valid backup archive whose checksum varies with ``payload_byte``."""
    body = bytes([payload_byte]) * 16
    checksum = hashlib.sha256(body).hexdigest()
    manifest = {
        'schemaVersion': 1,
        'createdAtUtc': '2025-01-01T00:00:00Z',
        'compression': 'zip',
        'counts': {'members': 0, 'memberPhotos': 0, 'assets': 0},
        'checksumSha256': checksum,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest))
        zf.writestr('payload.bin', body)
    return buf.getvalue()


def _seed_archive(db_path: Path, base_dir: Path, user_id: int) -> str:
    """Force-write an initial snapshot and return its server_version_tag."""
    body, status = store_backup(
        db_path, base_dir, user_id, _make_archive(0),
        force=True, capabilities={'if-match-v1'},
    )
    assert status == 200
    return body['serverVersionTag']


def _current_tag(db_path: Path, tree_id: int) -> str | None:
    connection = db_connect(db_path)
    try:
        row = connection.execute(
            'SELECT updated_at, checksum_sha256 FROM backup_snapshots '
            'WHERE tree_id = ? ORDER BY datetime(updated_at) DESC, id DESC LIMIT 1',
            (tree_id,),
        ).fetchone()
        if row is None:
            return None
        return compute_server_version_tag(row['updated_at'], row['checksum_sha256'])
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Property 4: single-session invariant under interleaved logins and toggles
# Property 5: idempotent re-login per (user_id, device_id)
# ---------------------------------------------------------------------------

DEVICE_IDS = ['device-A', 'device-B', 'device-C', 'device-D']


class SingleSessionStateMachine(RuleBasedStateMachine):
    """**Validates: Requirements 5.2, 5.7, 6.1, 6.2, 6.3**.

    Rules: ``toggle(bool)`` flips ``users.single_session_enabled``;
    ``login(device_id)`` issues a session via ``issue_session``.
    Invariant after every step:
        ``active_session_count(user) <= 1 if single_session_enabled(user) else True``
    """

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / 'pbt.db'
        _bootstrap_db(self._db_path)
        connection = db_connect(self._db_path)
        try:
            self._user_id = _create_user(connection, display_name='alice', single_session=1)
            connection.commit()
        finally:
            connection.close()
        # Track tokens per device for the idempotent-relogin probe
        self._tokens_by_device: dict[str, list[str]] = {d: [] for d in DEVICE_IDS}

    def teardown(self) -> None:
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    @rule(enabled=st.booleans())
    def toggle(self, enabled: bool) -> None:
        # Mirror the production PATCH /v2/auth/settings semantics (design §3.5,
        # Req 5.7): when re-enabling single-session, revoke every other active
        # session in the same transaction so the invariant remains intact.
        connection = db_connect(self._db_path)
        try:
            connection.execute('BEGIN IMMEDIATE')
            _set_single_session(connection, self._user_id, enabled)
            if enabled:
                now = utcnow_sql()
                rows = connection.execute(
                    'SELECT id, device_id FROM auth_sessions '
                    'WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?',
                    (self._user_id, now),
                ).fetchall()
                # Keep at most one active row (the most recent) so the
                # invariant ``active <= 1`` holds; revoke all earlier rows.
                for r in rows[:-1]:
                    connection.execute(
                        "UPDATE auth_sessions SET revoked_at = ?, "
                        "revoked_reason = 'single_session_re_enabled' "
                        'WHERE id = ?',
                        (now, r['id']),
                    )
            connection.commit()
        finally:
            connection.close()

    @rule(device_id=st.sampled_from(DEVICE_IDS))
    def login(self, device_id: str) -> None:
        connection = db_connect(self._db_path)
        try:
            token = issue_session(connection, self._user_id, device_id)
            connection.commit()
        finally:
            connection.close()
        self._tokens_by_device[device_id].append(token)

    @invariant()
    def single_session_invariant(self) -> None:
        connection = db_connect(self._db_path)
        try:
            active = _count_active(connection, self._user_id)
            single = _is_single_session(connection, self._user_id)
        finally:
            connection.close()
        if single:
            assert active <= 1, (
                f'single_session=True but active={active} for user_id={self._user_id}'
            )

    @invariant()
    def idempotent_relogin_invariant(self) -> None:
        """Property 5: at most one active row per ``(user_id, device_id)``
        whenever ``single_session_enabled`` is on. With single-session disabled
        ``issue_session`` is a plain INSERT so multiple rows per device are
        allowed and the invariant is vacuous."""
        connection = db_connect(self._db_path)
        try:
            if not _is_single_session(connection, self._user_id):
                return
            rows = connection.execute(
                'SELECT device_id, COUNT(*) AS c FROM auth_sessions '
                'WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? '
                'GROUP BY device_id',
                (self._user_id, utcnow_sql()),
            ).fetchall()
        finally:
            connection.close()
        for r in rows:
            assert r['c'] <= 1, f"device {r['device_id']} has {r['c']} active rows"


TestSingleSessionStateMachine = SingleSessionStateMachine.TestCase
TestSingleSessionStateMachine.settings = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@settings(max_examples=100, deadline=None)
@given(repeats=st.integers(min_value=2, max_value=8),
       device_id=st.sampled_from(DEVICE_IDS))
def test_idempotent_relogin_property(repeats: int, device_id: str) -> None:
    """Property 5 — replay the same ``(provider_user_id, device_id)`` ``N`` times;
    exactly one active row remains for the pair.

    **Validates: Requirements 6.1, 6.2, 6.3**.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / 'pbt.db'
        _bootstrap_db(db_path)
        connection = db_connect(db_path)
        try:
            user_id = _create_user(connection, display_name='zoe', single_session=1)
            connection.commit()
            for _ in range(repeats):
                issue_session(connection, user_id, device_id)
                connection.commit()
            active = connection.execute(
                'SELECT COUNT(*) FROM auth_sessions '
                'WHERE user_id = ? AND device_id = ? AND revoked_at IS NULL '
                'AND expires_at > ?',
                (user_id, device_id, utcnow_sql()),
            ).fetchone()[0]
            assert active == 1, f'expected 1 active row, got {active}'

            total_active = _count_active(connection, user_id)
            assert total_active == 1, total_active
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# Property 6: revoked-token middleware
# ---------------------------------------------------------------------------

# Paths that are gated by the bearer-token middleware and respond fast.
PROTECTED_V2_PATHS = [
    '/v2/backup/meta',
    '/v2/backup/download',
    '/v2/auth/settings',
    '/api/v2/backup/meta',
    '/api/v2/auth/settings',
]


REVOKED_REASONS = [
    'signed_in_on_other_device',
    'single_session_re_enabled',
    'manual_revocation',
]


def _insert_revoked_session(
    db_path: Path, user_id: int, device_id: str, raw_token: str, reason: str
) -> None:
    """Insert a session row directly and immediately mark it revoked.

    Mirrors the prod behaviour where the session was active first and then
    revoked (so ``expires_at`` is in the future to make sure the middleware
    short-circuits on ``revoked_at`` before checking expiry)."""
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = utcnow_sql()
    expires = '2099-12-31 23:59:59'
    connection = db_connect(db_path)
    try:
        connection.execute(
            'INSERT INTO auth_sessions '
            '(user_id, device_id, token_hash, created_at, expires_at, '
            'revoked_at, revoked_reason) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (user_id, device_id, token_hash, now, expires, now, reason),
        )
        connection.commit()
    finally:
        connection.close()


@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(
    raw_token=st.binary(min_size=16, max_size=64).map(
        lambda b: hashlib.sha256(b).hexdigest()
    ),
    path=st.sampled_from(PROTECTED_V2_PATHS),
    reason=st.sampled_from(REVOKED_REASONS),
)
def test_revoked_token_middleware_property(
    raw_token: str, path: str, reason: str
) -> None:
    """Property 6 — for any revoked token and any protected ``/v2/*`` path,
    the middleware MUST return ``401 session_revoked`` with the stored reason.

    **Validates: Requirements 5.3, 7.1, 7.2, 8.1, 8.2**.
    """
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        # Bootstrap schema BEFORE register_sql_api_v2 so additive migrations
        # find the base tables and only create the auth_sessions table.
        _bootstrap_db(base_dir / 'familyone.db')

        connection = db_connect(base_dir / 'familyone.db')
        try:
            user_id = _create_user(connection, display_name='m', single_session=1)
            connection.commit()
        finally:
            connection.close()

        _insert_revoked_session(
            base_dir / 'familyone.db', user_id, 'device-X', raw_token, reason
        )

        app = Flask(__name__)
        register_sql_api_v2(app, base_dir=base_dir)
        client = app.test_client()

        resp = client.get(path, headers={'Authorization': f'Bearer {raw_token}'})

        assert resp.status_code == 401, (
            f'{path} returned {resp.status_code} for revoked token'
        )
        body = resp.get_json()
        assert body == {'error': 'session_revoked', 'reason': reason}, body


# ---------------------------------------------------------------------------
# Property 10: audit completeness on every consequential server action
# ---------------------------------------------------------------------------

class AuditCompletenessStateMachine(RuleBasedStateMachine):
    """**Validates: Requirements 14.1, 14.2, 14.3, 14.4**.

    State machine over ``{conflict, force, revoke}`` events.
    Invariant: count of ``audit_logs`` rows by action equals the number of
    triggering events.
    """

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self._base = Path(self._tmp.name)
        self._db_path = self._base / 'familyone.db'
        _bootstrap_db(self._db_path)

        connection = db_connect(self._db_path)
        try:
            self._user_id = _create_user(
                connection, display_name='audit', single_session=1
            )
            connection.commit()
            tree_row = connection.execute(
                'SELECT id FROM family_trees WHERE owner_user_id = ? LIMIT 1',
                (self._user_id,),
            ).fetchone()
            self._tree_id = int(tree_row[0])
        finally:
            connection.close()

        # Seed an initial snapshot so subsequent conflicts have a current_tag.
        self._last_tag = _seed_archive(self._db_path, self._base, self._user_id)
        self._payload = 1

        # Expected counts per action.
        self._expected_force = 1  # the seed write itself is a force overwrite
        self._expected_conflict = 0
        self._expected_revoke = 0

    def teardown(self) -> None:
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    @rule()
    def conflict(self) -> None:
        # Send a strict (require_if_match) upload with a wrong If-Match — must 409.
        body, status = store_backup(
            self._db_path,
            self._base,
            self._user_id,
            _make_archive(self._payload),
            if_match='deadbeef' * 8,
            force=False,
            capabilities={'if-match-v1'},
            require_if_match=True,
        )
        self._payload = (self._payload + 1) % 256
        assert status == 409, (status, body)
        self._expected_conflict += 1

    @rule()
    def force(self) -> None:
        body, status = store_backup(
            self._db_path,
            self._base,
            self._user_id,
            _make_archive(self._payload),
            force=True,
            capabilities={'if-match-v1'},
        )
        self._payload = (self._payload + 1) % 256
        assert status == 200, (status, body)
        self._last_tag = body['serverVersionTag']
        self._expected_force += 1

    @rule(device_id=st.sampled_from(DEVICE_IDS))
    def revoke(self, device_id: str) -> None:
        # ``issue_session`` revokes every currently-active row for the user
        # (including a prior row for the same device — Req 6.3 idempotent
        # re-login) and emits one audit_logs(session_revoked) row per
        # revoked session inside the same transaction.
        connection = db_connect(self._db_path)
        try:
            before = connection.execute(
                'SELECT COUNT(*) FROM auth_sessions '
                'WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?',
                (self._user_id, utcnow_sql()),
            ).fetchone()[0]
            issue_session(connection, self._user_id, device_id)
            connection.commit()
        finally:
            connection.close()
        self._expected_revoke += int(before)

    @invariant()
    def audit_counts_match(self) -> None:
        connection = db_connect(self._db_path)
        try:
            rows = connection.execute(
                "SELECT action, COUNT(*) AS c FROM audit_logs "
                "WHERE user_id = ? GROUP BY action",
                (self._user_id,),
            ).fetchall()
        finally:
            connection.close()
        counts = {r['action']: int(r['c']) for r in rows}
        assert counts.get('backup_force_overwrite', 0) == self._expected_force, (
            'force', counts, self._expected_force,
        )
        assert counts.get('backup_conflict_rejected', 0) == self._expected_conflict, (
            'conflict', counts, self._expected_conflict,
        )
        assert counts.get('session_revoked', 0) == self._expected_revoke, (
            'revoke', counts, self._expected_revoke,
        )


TestAuditCompletenessStateMachine = AuditCompletenessStateMachine.TestCase
TestAuditCompletenessStateMachine.settings = settings(
    max_examples=100,
    deadline=None,
    stateful_step_count=20,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


# ---------------------------------------------------------------------------
# Property 10 (audit-failure clause): on simulated audit-insert failure during
# a force=true overwrite, the snapshot is unchanged and the response is
# ``503 audit_unavailable``. Uses monkeypatch on ``_audit_log`` to raise.
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(payload=st.integers(min_value=1, max_value=255))
def test_audit_failure_during_force_yields_503(payload: int) -> None:
    """**Validates: Requirements 14.3, 14.4**.

    When ``_audit_log`` raises during a force overwrite, ``store_backup`` MUST
    rollback and return ``503 audit_unavailable``. The snapshot row left in
    the DB is the previous one (unchanged ``updated_at``/``checksum_sha256``).
    """
    # Hypothesis does not inject pytest fixtures into @given functions, so
    # use a manual MonkeyPatch instance.
    mp = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            db_path = base_dir / 'familyone.db'
            _bootstrap_db(db_path)
            connection = db_connect(db_path)
            try:
                user_id = _create_user(
                    connection, display_name='audit-fail', single_session=1
                )
                connection.commit()
            finally:
                connection.close()

            # Seed an initial snapshot.
            seed_tag = _seed_archive(db_path, base_dir, user_id)

            # Capture the on-disk snapshot row before the failing call.
            connection = db_connect(db_path)
            try:
                before = connection.execute(
                    'SELECT updated_at, checksum_sha256, size_bytes '
                    'FROM backup_snapshots ORDER BY id DESC LIMIT 1'
                ).fetchone()
            finally:
                connection.close()

            real_audit = sql_repository._audit_log

            def _flaky(connection, tree_id, uid, action, details):
                if action == 'backup_force_overwrite':
                    raise RuntimeError('simulated audit failure')
                return real_audit(connection, tree_id, uid, action, details)

            mp.setattr(sql_repository, '_audit_log', _flaky)

            body, status = store_backup(
                db_path, base_dir, user_id, _make_archive(payload),
                force=True, capabilities={'if-match-v1'},
            )

            assert status == 503, (status, body)
            assert body['error'] == 'audit_unavailable'
            assert body['serverVersionTag'] == seed_tag

            # Snapshot row must be unchanged.
            connection = db_connect(db_path)
            try:
                after = connection.execute(
                    'SELECT updated_at, checksum_sha256, size_bytes '
                    'FROM backup_snapshots ORDER BY id DESC LIMIT 1'
                ).fetchone()
            finally:
                connection.close()
            assert before['updated_at'] == after['updated_at']
            assert before['checksum_sha256'] == after['checksum_sha256']
            assert before['size_bytes'] == after['size_bytes']
    finally:
        mp.undo()
