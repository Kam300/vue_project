import JSZip from 'jszip'
import type { FamilyMember, MemberPhoto } from '@/types/models'
import { addMemberPhoto, getAllMembers, getAllPhotos, getMemberPhotos, upsertMember } from '@/db/repositories'
import { compressImageToJpeg, dataUrlToBlob, fileToDataUrl, imageSha256 } from '@/utils/image'
import { sha256FromString } from '@/utils/crypto'
import { normalizeDateToDisplayFormat } from '@/utils/date'

export interface BackupArchiveBuildResult {
  file: Blob
  schemaVersion: number
  createdAtUtc: string
  membersCount: number
  memberPhotosCount: number
  assetsCount: number
  sizeBytes: number
  checksumSha256: string
}

export interface BackupRestoreReport {
  membersInserted: number
  membersMatched: number
  photosAdded: number
  photosSkippedDuplicates: number
  errors: number
}

interface BackupMemberRecord {
  backupMemberKey: string
  firstName: string
  lastName: string
  patronymic: string
  gender: FamilyMember['gender']
  birthDate: string
  role: FamilyMember['role']
  phoneNumber: string
  maidenName: string
  weddingDate: string
  fatherBackupKey: string | null
  motherBackupKey: string | null
  profilePhotoAssetId: string | null
}

interface BackupPhotoRecord {
  backupMemberKey: string
  photoAssetId: string
  dateAdded: number
  description: string
  isProfilePhoto: boolean
}

function memberFingerprint(member: {
  firstName: string
  lastName: string
  patronymic?: string | null
  birthDate: string
  role: FamilyMember['role']
}): string {
  return [
    member.lastName.trim().toLowerCase(),
    member.firstName.trim().toLowerCase(),
    (member.patronymic || '').trim().toLowerCase(),
    normalizeDateToDisplayFormat(member.birthDate),
    member.role
  ].join('|')
}

async function getAssetIdFromImage(dataUrl: string): Promise<{ assetId: string; blob: Blob }> {
  const sourceBlob = await dataUrlToBlob(dataUrl)
  const jpegBlob = await compressImageToJpeg(sourceBlob, { maxEdge: 1280, quality: 0.8 })
  const assetHash = await imageSha256(jpegBlob)
  return { assetId: assetHash, blob: jpegBlob }
}

async function blobToUint8Array(blob: Blob): Promise<Uint8Array> {
  return new Uint8Array(await blob.arrayBuffer())
}

export async function createBackupArchive(
  appVersion = String(import.meta.env.VITE_APP_VERSION || '1.0.0')
): Promise<BackupArchiveBuildResult> {
  const members = await getAllMembers()
  const photos = await getAllPhotos()
  const createdAtUtc = new Date().toISOString()
  const schemaVersion = 1
  const zip = new JSZip()

  const memberKeyById = new Map<number, string>()
  for (const member of members) {
    if (member.id) memberKeyById.set(member.id, `member_${member.id}`)
  }

  const assets = new Map<string, Uint8Array>()
  const profileAssetByMemberKey = new Map<string, string | null>()

  for (const member of members) {
    const key = member.id ? memberKeyById.get(member.id) : null
    if (!key) continue
    if (!member.photoUri) {
      profileAssetByMemberKey.set(key, null)
      continue
    }

    try {
      const { assetId, blob } = await getAssetIdFromImage(member.photoUri)
      if (!assets.has(assetId)) {
        assets.set(assetId, await blobToUint8Array(blob))
      }
      profileAssetByMemberKey.set(key, assetId)
    } catch {
      profileAssetByMemberKey.set(key, null)
    }
  }

  const memberPhotosPayload: BackupPhotoRecord[] = []
  for (const photo of photos) {
    const memberKey = memberKeyById.get(photo.memberId)
    if (!memberKey) continue
    try {
      const { assetId, blob } = await getAssetIdFromImage(photo.photoUri)
      if (!assets.has(assetId)) {
        assets.set(assetId, await blobToUint8Array(blob))
      }
      memberPhotosPayload.push({
        backupMemberKey: memberKey,
        photoAssetId: assetId,
        dateAdded: photo.dateAdded,
        description: photo.description || '',
        isProfilePhoto: photo.isProfilePhoto
      })
    } catch {
      // skip invalid images
    }
  }

  const membersPayload: BackupMemberRecord[] = members
    .filter((member) => member.id)
    .map((member) => {
      const backupKey = memberKeyById.get(member.id as number) as string
      return {
        backupMemberKey: backupKey,
        firstName: member.firstName,
        lastName: member.lastName,
        patronymic: member.patronymic || '',
        gender: member.gender,
        birthDate: normalizeDateToDisplayFormat(member.birthDate),
        role: member.role,
        phoneNumber: member.phoneNumber || '',
        maidenName: member.maidenName || '',
        weddingDate: member.weddingDate || '',
        fatherBackupKey:
          member.fatherId && memberKeyById.has(member.fatherId) ? memberKeyById.get(member.fatherId)! : null,
        motherBackupKey:
          member.motherId && memberKeyById.has(member.motherId) ? memberKeyById.get(member.motherId)! : null,
        profilePhotoAssetId: profileAssetByMemberKey.get(backupKey) || null
      }
    })

  const membersJson = JSON.stringify(membersPayload)
  const photosJson = JSON.stringify(memberPhotosPayload)
  const checksumInput =
    membersJson + photosJson + Array.from(assets.keys()).sort((a, b) => a.localeCompare(b)).join('')
  const checksumSha256 = await sha256FromString(checksumInput)

  const manifestJson = JSON.stringify(
    {
      schemaVersion,
      createdAtUtc,
      appVersion,
      compression: 'jpeg_1280_q80',
      counts: {
        members: membersPayload.length,
        memberPhotos: memberPhotosPayload.length,
        assets: assets.size
      },
      checksumSha256
    },
    null,
    2
  )

  zip.file('manifest.json', manifestJson)
  zip.file('members.json', JSON.stringify(membersPayload, null, 2))
  zip.file('member_photos.json', JSON.stringify(memberPhotosPayload, null, 2))

  for (const [assetId, bytes] of assets.entries()) {
    zip.file(`assets/${assetId}.jpg`, bytes)
  }

  const file = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE' })

  return {
    file,
    schemaVersion,
    createdAtUtc,
    membersCount: membersPayload.length,
    memberPhotosCount: memberPhotosPayload.length,
    assetsCount: assets.size,
    sizeBytes: file.size,
    checksumSha256
  }
}

export async function restoreBackupArchive(file: Blob): Promise<BackupRestoreReport> {
  const zip = await JSZip.loadAsync(file)
  const manifestText = await zip.file('manifest.json')?.async('string')
  const membersText = await zip.file('members.json')?.async('string')
  const photosText = await zip.file('member_photos.json')?.async('string')

  if (!manifestText || !membersText || !photosText) {
    throw new Error('Архив backup неполный (manifest/members/member_photos)')
  }

  const manifest = JSON.parse(manifestText) as { schemaVersion?: number }
  if (!manifest.schemaVersion || manifest.schemaVersion < 1) {
    throw new Error('Неподдерживаемая версия backup schema')
  }

  const backupMembers = JSON.parse(membersText) as BackupMemberRecord[]
  const backupPhotos = JSON.parse(photosText) as BackupPhotoRecord[]
  if (!Array.isArray(backupMembers) || !Array.isArray(backupPhotos)) {
    throw new Error('Некорректный формат backup')
  }

  const existingMembers = await getAllMembers()
  const fingerprintIndex = new Map(existingMembers.map((member) => [memberFingerprint(member), member]))
  const backupKeyToLocalId = new Map<string, number>()
  const pendingRelations: Array<{ localId: number; fatherKey: string | null; motherKey: string | null }> = []

  let membersInserted = 0
  let membersMatched = 0
  let photosAdded = 0
  let photosSkippedDuplicates = 0
  let errors = 0

  for (const record of backupMembers) {
    const key = memberFingerprint(record)
    const existing = fingerprintIndex.get(key)
    if (existing?.id) {
      backupKeyToLocalId.set(record.backupMemberKey, existing.id)
      membersMatched += 1
    } else {
      const localId = await upsertMember({
        firstName: record.firstName,
        lastName: record.lastName,
        patronymic: record.patronymic || null,
        gender: record.gender || 'MALE',
        birthDate: normalizeDateToDisplayFormat(record.birthDate),
        role: record.role || 'OTHER',
        phoneNumber: record.phoneNumber || null,
        fatherId: null,
        motherId: null,
        weddingDate: record.weddingDate || null,
        maidenName: record.maidenName || null,
        photoUri: null
      })
      backupKeyToLocalId.set(record.backupMemberKey, localId)
      membersInserted += 1
    }

    const localId = backupKeyToLocalId.get(record.backupMemberKey)
    if (localId) {
      pendingRelations.push({
        localId,
        fatherKey: record.fatherBackupKey,
        motherKey: record.motherBackupKey
      })
    }
  }

  const latestMembers = await getAllMembers()
  const latestById = new Map(latestMembers.map((member) => [member.id as number, member]))

  for (const relation of pendingRelations) {
    const member = latestById.get(relation.localId)
    if (!member) continue
    const fatherId = relation.fatherKey ? backupKeyToLocalId.get(relation.fatherKey) || null : member.fatherId || null
    const motherId = relation.motherKey ? backupKeyToLocalId.get(relation.motherKey) || null : member.motherId || null
    if (fatherId !== member.fatherId || motherId !== member.motherId) {
      await upsertMember({ ...member, fatherId, motherId })
    }
  }

  const photoHashesByMember = new Map<number, Set<string>>()

  async function ensureMemberHashes(memberId: number): Promise<Set<string>> {
    if (photoHashesByMember.has(memberId)) return photoHashesByMember.get(memberId)!
    const hashes = new Set<string>()
    const photos = await getMemberPhotos(memberId)
    for (const photo of photos) {
      if (!photo.photoUri) continue
      try {
        hashes.add(await imageSha256(photo.photoUri))
      } catch {
        // ignore invalid photo in db
      }
    }
    photoHashesByMember.set(memberId, hashes)
    return hashes
  }

  const profileAssignments: Array<{ localId: number; assetId: string }> = []

  for (const photoRecord of backupPhotos) {
    const localId = backupKeyToLocalId.get(photoRecord.backupMemberKey)
    if (!localId) {
      errors += 1
      continue
    }

    const assetEntry =
      zip.file(`assets/${photoRecord.photoAssetId}.jpg`) ||
      zip.file(`assets/${photoRecord.photoAssetId}.jpeg`) ||
      zip.file(`assets/${photoRecord.photoAssetId}.png`)

    if (!assetEntry) {
      errors += 1
      continue
    }

    const assetBlob = await assetEntry.async('blob')
    const dataUrl = await fileToDataUrl(assetBlob)
    const hash = await imageSha256(dataUrl)
    const knownHashes = await ensureMemberHashes(localId)

    if (knownHashes.has(hash)) {
      photosSkippedDuplicates += 1
      continue
    }

    await addMemberPhoto({
      memberId: localId,
      photoUri: dataUrl,
      dateAdded: photoRecord.dateAdded || Date.now(),
      description: photoRecord.description || '',
      isProfilePhoto: photoRecord.isProfilePhoto,
      imageHash: hash
    })
    knownHashes.add(hash)
    photosAdded += 1
  }

  for (const memberRecord of backupMembers) {
    if (!memberRecord.profilePhotoAssetId) continue
    const localId = backupKeyToLocalId.get(memberRecord.backupMemberKey)
    if (!localId) continue
    profileAssignments.push({ localId, assetId: memberRecord.profilePhotoAssetId })
  }

  const membersAfterPhotos = await getAllMembers()
  const membersMap = new Map(membersAfterPhotos.map((member) => [member.id as number, member]))

  for (const profile of profileAssignments) {
    const member = membersMap.get(profile.localId)
    if (!member || member.photoUri) continue

    const assetEntry =
      zip.file(`assets/${profile.assetId}.jpg`) ||
      zip.file(`assets/${profile.assetId}.jpeg`) ||
      zip.file(`assets/${profile.assetId}.png`)
    if (!assetEntry) continue

    const assetBlob = await assetEntry.async('blob')
    const dataUrl = await fileToDataUrl(assetBlob)
    await upsertMember({ ...member, photoUri: dataUrl })
  }

  return {
    membersInserted,
    membersMatched,
    photosAdded,
    photosSkippedDuplicates,
    errors
  }
}
