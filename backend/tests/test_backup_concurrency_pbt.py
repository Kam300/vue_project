# Feature: multi-device-sync-safety, Property 1 / 2 / 3: Server_Version_Tag round-trip and concurrent-upload mutual exclusion
"""Property-based tests for ``store_backup`` optimistic-concurrency core.

Library: ``hypothesis``.

Validates Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10,
4.1, 4.3, 15.1, 15.2, 15.3.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

# Allow running from repo root without installation.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sql_repository import (  # noqa: E402
    compute_server_version_tag,
    db_connect,
    run_migrations,
    store_backup,
    utcnow_sql,
)


_HEX64 = re.compile(r'^[0-9a-f]{64}$')


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


def _bootstrap_db(db_path: Path) -> None:
    """Create the base schema then run additive migrations."""
    connection = db_connect(db_path)
    try:
        connection.executescript(_BASE_SCHEMA)
        connection.commit()
    finally:
        connection.close()
    run_migrations(db_path)


def _create_user_and_tree(connection) -> int:
    now = utcnow_sql()
    cursor = connection.execute(
        'INSERT INTO users (display_name, preferred_auth_provider, '
        'created_at, updated_at) VALUES (?, ?, ?, ?)',
        ('alice', 'local', now, now),
    )
    user_id = int(cursor.lastrowid)
    tree_cursor = connection.execute(
        'INSERT INTO family_trees (owner_user_id, title, created_at, updated_at) '
        'VALUES (?, ?, ?, ?)',
        (user_id, 'Tree of alice', now, now),
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


def _make_archive(payload_marker: bytes = b'') -> bytes:
    """Build a minimal valid backup archive accepted by parse_backup_manifest."""
    buf = io.BytesIO()
    manifest = {
        'schemaVersion': 1,
        'createdAtUtc': '2026-05-10T12:34:56.789012Z',
        'compression': 'zip',
        'counts': {'members': 0, 'memberPhotos': 0, 'assets': 0},
    }
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        if payload_marker:
            archive.writestr('marker.bin', payload_marker)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Property 1: compute_server_version_tag is a deterministic pure function.
# ---------------------------------------------------------------------------

@given(
    updated_at=st.text(min_size=1, max_size=64),
    checksum=st.text(min_size=1, max_size=64),
)
@settings(max_examples=200, deadline=None)
def test_property_1_compute_server_version_tag_pure_function(
    updated_at: str, checksum: str
) -> None:
    """**Validates: Requirements 1.2, 4.1, 4.3**

    Property 1: ``compute_server_version_tag(updated_at, checksum)`` is
    deterministic and yields a lowercase 64-char hexadecimal string.
    """
    tag1 = compute_server_version_tag(updated_at, checksum)
    tag2 = compute_server_version_tag(updated_at, checksum)
    assert tag1 == tag2
    assert _HEX64.match(tag1), tag1


# ---------------------------------------------------------------------------
# Property 2: Optimistic-concurrency upload semantics (decision table).
# ---------------------------------------------------------------------------

class BackupUploadStateMachine(RuleBasedStateMachine):
    """Stateful exploration of the design §3.3 decision table.

    **Validates: Requirements 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.10,
    15.1, 15.2, 15.3**

    Rules: ``seed_snapshot`` (legacy-first force-write to populate state)
    and ``upload(if_match, force, capability)`` (the unit under test).
    """

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._tmp.name)
        self.db_path = self.base_dir / 'familyone.db'
        _bootstrap_db(self.db_path)
        connection = db_connect(self.db_path)
        try:
            self.user_id = _create_user_and_tree(connection)
            connection.commit()
        finally:
            connection.close()

        # Mirror of the server's persisted state.
        self.exists: bool = False
        self.current_tag: str | None = None
        self.current_updated_at: str | None = None
        self._counter: int = 0

    def teardown(self) -> None:
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    # ---- helpers -----------------------------------------------------------

    def _read_updated_at(self) -> str | None:
        connection = db_connect(self.db_path)
        try:
            row = connection.execute(
                'SELECT updated_at FROM backup_snapshots '
                'ORDER BY id DESC LIMIT 1'
            ).fetchone()
            return row['updated_at'] if row else None
        finally:
            connection.close()

    @staticmethod
    def _expected_status(
        *,
        legacy: bool,
        exists: bool,
        force: bool,
        if_match: str | None,
        current_tag: str | None,
    ) -> int:
        """Decision table from design.md §3.3 / §7 Property 2."""
        if legacy:
            if not exists:
                return 200
            return 426
        # strict (capability == 'if-match-v1')
        if not exists:
            return 200
        if force:
            return 200
        # exists and not force
        if if_match is None:
            return 428
        if if_match == '*' or if_match != current_tag:
            return 409
        return 200

    # ---- rules -------------------------------------------------------------

    @rule()
    def seed_snapshot(self) -> None:
        """Force-write a fresh snapshot (legacy bootstrap path)."""
        self._counter += 1
        archive = _make_archive(f'seed-{self._counter}'.encode('utf-8'))
        prev_tag = self.current_tag
        prev_updated_at = self.current_updated_at

        body, status = store_backup(
            self.db_path,
            self.base_dir,
            self.user_id,
            archive,
            if_match=None,
            force=True,
            capabilities={'if-match-v1'},
            require_if_match=False,
            last_change_ids=None,
        )
        assert status == 200, (status, body)

        new_tag = body['serverVersionTag']
        new_updated_at = self._read_updated_at()
        assert new_tag is not None and _HEX64.match(new_tag)
        if prev_tag is not None:
            assert new_tag != prev_tag, (prev_tag, new_tag)
        if prev_updated_at is not None and new_updated_at is not None:
            assert new_updated_at > prev_updated_at, (
                prev_updated_at,
                new_updated_at,
            )
        self.current_tag = new_tag
        self.current_updated_at = new_updated_at
        self.exists = True
        # Guarantee microsecond progress on platforms with low-res clocks.
        time.sleep(0.001)

    @rule(
        if_match_kind=st.sampled_from(('absent', 'star', 'current', 'random')),
        force=st.booleans(),
        capability=st.booleans(),
    )
    def upload(
        self, if_match_kind: str, force: bool, capability: bool
    ) -> None:
        self._counter += 1
        archive = _make_archive(
            f'upload-{self._counter}-{if_match_kind}-{force}-{capability}'.encode(
                'utf-8'
            )
        )
        if if_match_kind == 'absent':
            if_match: str | None = None
        elif if_match_kind == 'star':
            if_match = '*'
        elif if_match_kind == 'current':
            if_match = self.current_tag  # may be None pre-seed; that's a valid case
        else:  # random
            if_match = hashlib.sha256(
                f'rand-{self._counter}'.encode('utf-8')
            ).hexdigest()

        caps: set[str] = {'if-match-v1'} if capability else set()
        legacy = not capability
        prev_tag = self.current_tag
        prev_updated_at = self.current_updated_at

        body, status = store_backup(
            self.db_path,
            self.base_dir,
            self.user_id,
            archive,
            if_match=if_match,
            force=force,
            capabilities=caps,
            require_if_match=True,
            last_change_ids=None,
        )

        expected = self._expected_status(
            legacy=legacy,
            exists=self.exists,
            force=force,
            if_match=if_match,
            current_tag=self.current_tag,
        )
        assert status == expected, (
            f'status={status} expected={expected} '
            f'legacy={legacy} exists={self.exists} force={force} '
            f'if_match_kind={if_match_kind} current_tag={self.current_tag} '
            f'body={body}'
        )

        if status == 200:
            new_tag = body['serverVersionTag']
            assert new_tag is not None and _HEX64.match(new_tag)
            assert new_tag != prev_tag, (prev_tag, new_tag)
            new_updated_at = self._read_updated_at()
            if prev_updated_at is not None and new_updated_at is not None:
                assert new_updated_at > prev_updated_at, (
                    prev_updated_at,
                    new_updated_at,
                )
            self.current_tag = new_tag
            self.current_updated_at = new_updated_at
            self.exists = True
            time.sleep(0.001)

    # ---- invariants --------------------------------------------------------

    @invariant()
    def tag_shape_invariant(self) -> None:
        """When a snapshot exists the tracked tag is well-formed (Req 4.1)."""
        if self.exists:
            assert self.current_tag is not None
            assert _HEX64.match(self.current_tag), self.current_tag


TestBackupUploadStateMachine = BackupUploadStateMachine.TestCase
TestBackupUploadStateMachine.settings = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


# ---------------------------------------------------------------------------
# Property 3: Concurrent-upload mutual exclusion (Req 1.9).
# ---------------------------------------------------------------------------

@given(n=st.integers(min_value=2, max_value=8))
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_property_3_concurrent_upload_mutual_exclusion(n: int) -> None:
    """**Validates: Requirement 1.9**

    Property 3: ``N >= 2`` concurrent uploads observing the same starting
    tag yield exactly one ``200 OK`` (with a new tag) and ``N - 1``
    ``409 Conflict`` responses whose body's ``serverVersionTag`` is either
    the original or the new tag.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        db_path = base_dir / 'familyone.db'
        _bootstrap_db(db_path)

        connection = db_connect(db_path)
        try:
            user_id = _create_user_and_tree(connection)
            connection.commit()
        finally:
            connection.close()

        # Seed an initial snapshot so all racers see the same starting tag.
        seed_archive = _make_archive(b'seed')
        seed_body, seed_status = store_backup(
            db_path,
            base_dir,
            user_id,
            seed_archive,
            if_match=None,
            force=True,
            capabilities={'if-match-v1'},
            require_if_match=False,
            last_change_ids=None,
        )
        assert seed_status == 200, (seed_status, seed_body)
        starting_tag = seed_body['serverVersionTag']
        assert _HEX64.match(starting_tag)

        archives = [
            _make_archive(f'race-{n}-{idx}'.encode('utf-8')) for idx in range(n)
        ]
        barrier = threading.Barrier(n)

        def _upload(idx: int):
            barrier.wait()
            return store_backup(
                db_path,
                base_dir,
                user_id,
                archives[idx],
                if_match=starting_tag,
                force=False,
                capabilities={'if-match-v1'},
                require_if_match=True,
                last_change_ids=None,
            )

        with ThreadPoolExecutor(max_workers=n) as executor:
            results = list(executor.map(_upload, range(n)))

        statuses = [status for _body, status in results]
        assert statuses.count(200) == 1, statuses
        assert statuses.count(409) == n - 1, statuses

        winners = [body for body, status in results if status == 200]
        new_tag = winners[0]['serverVersionTag']
        assert _HEX64.match(new_tag), new_tag
        assert new_tag != starting_tag

        for body, status in results:
            if status == 409:
                tag_in_body = body.get('serverVersionTag')
                assert tag_in_body in (starting_tag, new_tag), (
                    tag_in_body,
                    starting_tag,
                    new_tag,
                )
