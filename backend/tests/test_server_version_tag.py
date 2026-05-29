"""Smoke tests for compute_server_version_tag and parse_capabilities.

Feature: multi-device-sync-safety, design §3.2 / §3.7.
Acceptance check for task 1.2: determinism and 64-char lowercase hex output.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

# Allow running from repo root without installation.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sql_repository import compute_server_version_tag, parse_capabilities  # noqa: E402


_HEX64 = re.compile(r'^[0-9a-f]{64}$')


class _FakeReq:
    def __init__(self, value: str | None) -> None:
        self.headers = {} if value is None else {'X-Client-Capabilities': value}


def test_compute_server_version_tag_is_deterministic() -> None:
    updated_at = '2026-05-10 12:34:56.789012'
    checksum = 'a' * 64
    first = compute_server_version_tag(updated_at, checksum)
    second = compute_server_version_tag(updated_at, checksum)
    assert first == second


def test_compute_server_version_tag_returns_lowercase_64_hex() -> None:
    tag = compute_server_version_tag('2026-05-10 12:34:56.789012', 'b' * 64)
    assert _HEX64.match(tag), tag
    assert len(tag) == 64
    assert tag == tag.lower()


def test_compute_server_version_tag_matches_sha256_payload_format() -> None:
    updated_at = '2026-05-10 12:34:56.789012'
    checksum = 'c' * 64
    expected = hashlib.sha256(f'{updated_at}|{checksum}'.encode('utf-8')).hexdigest()
    assert compute_server_version_tag(updated_at, checksum) == expected


def test_compute_server_version_tag_changes_with_inputs() -> None:
    base = compute_server_version_tag('2026-05-10 12:34:56.789012', 'd' * 64)
    diff_ts = compute_server_version_tag('2026-05-10 12:34:56.789013', 'd' * 64)
    diff_sum = compute_server_version_tag('2026-05-10 12:34:56.789012', 'e' * 64)
    assert base != diff_ts
    assert base != diff_sum


def test_parse_capabilities_lowercases_and_trims_tokens() -> None:
    req = _FakeReq('  IF-Match-V1 ,  Foo  ,bar')
    assert parse_capabilities(req) == {'if-match-v1', 'foo', 'bar'}


def test_parse_capabilities_handles_empty_and_missing_headers() -> None:
    assert parse_capabilities(_FakeReq(None)) == set()
    assert parse_capabilities(_FakeReq('')) == set()
    assert parse_capabilities(_FakeReq('   ,, ,')) == set()


def test_parse_capabilities_dedupes_repeated_tokens() -> None:
    req = _FakeReq('if-match-v1, IF-MATCH-V1 , if-match-v1')
    assert parse_capabilities(req) == {'if-match-v1'}
