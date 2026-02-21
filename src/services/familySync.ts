import { getAllMembers } from '@/db/repositories'
import { ensureFaceApiPayload } from '@/utils/image'
import { listFaces, registerFace } from '@/services/api'

export function toServerMemberId(deviceId: number, memberId: number): number {
  return deviceId * 1_000_000 + memberId
}

export function fromServerMemberId(serverId: number): number {
  return serverId % 1_000_000
}

export interface FaceSyncReport {
  registered: number
  skipped: number
  failed: number
}

export async function syncProfileFaces(deviceId: number): Promise<FaceSyncReport> {
  const members = await getAllMembers()
  const serverFaces = await listFaces().catch(() => ({ success: false, faces: [] as never[] }))
  const knownServerIds = new Set((serverFaces.faces || []).map((face) => String(face.member_id)))

  let registered = 0
  let skipped = 0
  let failed = 0

  for (const member of members) {
    if (!member.id || !member.photoUri) {
      skipped += 1
      continue
    }

    const serverId = toServerMemberId(deviceId, member.id)
    if (knownServerIds.has(String(serverId))) {
      skipped += 1
      continue
    }

    try {
      const imagePayload = await ensureFaceApiPayload(member.photoUri)
      const response = await registerFace({
        member_id: String(serverId),
        member_name: `${member.firstName} ${member.lastName}`.trim(),
        image: imagePayload
      })
      if (response.success) {
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
