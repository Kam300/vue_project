import { getAllMembers } from '@/db/repositories'
import { ensureFaceApiPayload } from '@/utils/image'
import { listFaces, registerFace } from '@/services/api'
import { normalizeDateToDisplayFormat } from '@/utils/date'
import type { FamilyMember } from '@/types/models'

const LEGACY_MEMBER_ID_MOD = 1_000_000
const STABLE_SERVER_ID_PREFIX = 'fo1'
const FNV_OFFSET_BASIS_64 = 0xcbf29ce484222325n
const FNV_PRIME_64 = 0x100000001b3n
const FNV_MASK_64 = 0xffffffffffffffffn

type SyncIdentityMember = Pick<
  FamilyMember,
  'firstName' | 'lastName' | 'patronymic' | 'birthDate' | 'role'
>

function normalizeIdentityPart(value: string | null | undefined): string {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

function buildMemberIdentityInput(member: SyncIdentityMember): string {
  return [
    normalizeIdentityPart(member.lastName),
    normalizeIdentityPart(member.firstName),
    normalizeIdentityPart(member.patronymic || ''),
    normalizeDateToDisplayFormat(member.birthDate),
    normalizeIdentityPart(member.role)
  ].join('|')
}

function fnv1a64Hex(input: string): string {
  let hash = FNV_OFFSET_BASIS_64
  for (let i = 0; i < input.length; i += 1) {
    hash ^= BigInt(input.charCodeAt(i))
    hash = (hash * FNV_PRIME_64) & FNV_MASK_64
  }
  return hash.toString(16).padStart(16, '0')
}

function getStableMemberIdentityHash(member: SyncIdentityMember): string {
  return fnv1a64Hex(buildMemberIdentityInput(member))
}

function parseStableServerMemberId(raw: string): { deviceId: number; identityHash: string } | null {
  const matched = raw.match(/^fo1_(\d+)_([0-9a-f]{16})$/i)
  if (!matched) return null

  const deviceId = Number(matched[1])
  if (!Number.isFinite(deviceId) || deviceId <= 0) return null

  return {
    deviceId,
    identityHash: matched[2].toLowerCase()
  }
}

export function toLegacyServerMemberId(deviceId: number, memberId: number): string {
  return String(deviceId * LEGACY_MEMBER_ID_MOD + memberId)
}

export function toServerMemberId(deviceId: number, member: SyncIdentityMember | number): string {
  if (typeof member === 'number') {
    return toLegacyServerMemberId(deviceId, member)
  }

  const identityHash = getStableMemberIdentityHash(member)
  return `${STABLE_SERVER_ID_PREFIX}_${deviceId}_${identityHash}`
}

export function fromServerMemberId(serverId: number): number {
  return serverId % LEGACY_MEMBER_ID_MOD
}

export function resolveLocalMemberIdFromServer(
  rawServerMemberId: string | number,
  members: FamilyMember[],
  deviceId?: number
): number | null {
  const normalized = String(rawServerMemberId || '').trim()
  if (!normalized) return null

  const stable = parseStableServerMemberId(normalized)
  if (stable) {
    if (deviceId && stable.deviceId !== deviceId) {
      return null
    }

    for (const member of members) {
      if (!member.id) continue
      const memberHash = getStableMemberIdentityHash(member)
      if (memberHash === stable.identityHash) {
        return member.id
      }
    }
  }

  const numeric = Number(normalized)
  if (!Number.isFinite(numeric) || numeric <= 0) return null
  const direct = Math.floor(numeric)

  const directMatch = members.find((member) => member.id === direct)
  if (directMatch?.id) return directMatch.id

  const decoded = fromServerMemberId(direct)
  const decodedMatch = members.find((member) => member.id === decoded)
  if (decodedMatch?.id) return decodedMatch.id

  return null
}

export interface FaceSyncReport {
  registered: number
  skipped: number
  failed: number
}

export async function syncProfileFaces(deviceId: number): Promise<FaceSyncReport> {
  const members = await getAllMembers()
  const serverFaces = await listFaces()
  if (!serverFaces.success || !Array.isArray(serverFaces.faces)) {
    throw new Error(serverFaces.error || 'Не удалось получить список лиц с сервера')
  }

  const knownServerIds = new Set((serverFaces.faces || []).map((face) => String(face.member_id)))

  let registered = 0
  let skipped = 0
  let failed = 0

  for (const member of members) {
    if (!member.id || !member.photoUri) {
      skipped += 1
      continue
    }

    const serverId = toServerMemberId(deviceId, member)
    const legacyServerId = toLegacyServerMemberId(deviceId, member.id)
    if (knownServerIds.has(serverId) || knownServerIds.has(legacyServerId)) {
      skipped += 1
      continue
    }

    try {
      const imagePayload = await ensureFaceApiPayload(member.photoUri)
      const response = await registerFace({
        member_id: serverId,
        member_name: `${member.firstName} ${member.lastName}`.trim(),
        image: imagePayload
      })
      if (response.success) {
        knownServerIds.add(serverId)
        registered += 1
      } else {
        failed += 1
      }
    } catch {
      failed += 1
    }
  }

  return { registered, skipped, failed }
}
