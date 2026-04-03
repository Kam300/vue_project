from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class ProviderConfig:
    configured: bool


@dataclass(slots=True)
class AuthIdentitySnapshot:
    provider: str
    provider_user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    connected: bool = True


@dataclass(slots=True)
class AuthUserSnapshot:
    id: int
    display_name: str
    email: Optional[str]
    preferred_auth_provider: str
    providers: list[AuthIdentitySnapshot] = field(default_factory=list)


@dataclass(slots=True)
class BackupMetaSnapshot:
    schema_version: int
    exists: bool
    created_at_utc: Optional[str] = None
    updated_at_utc: Optional[str] = None
    compression: Optional[str] = None
    size_bytes: Optional[int] = None
    members_count: Optional[int] = None
    member_photos_count: Optional[int] = None
    assets_count: Optional[int] = None
    checksum_sha256: Optional[str] = None
