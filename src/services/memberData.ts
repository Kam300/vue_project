import type { FamilyMember } from '@/types/models'
import { ROLE_LABELS } from '@/types/models'
import {
  deleteAllMembers,
  getAllMembers,
  patchAppSettings,
  upsertMember
} from '@/db/repositories'
import { normalizeDateToDisplayFormat } from '@/utils/date'

function fingerprint(member: Pick<FamilyMember, 'firstName' | 'lastName' | 'patronymic' | 'birthDate' | 'role'>): string {
  return [
    member.lastName.trim().toLowerCase(),
    member.firstName.trim().toLowerCase(),
    (member.patronymic || '').trim().toLowerCase(),
    normalizeDateToDisplayFormat(member.birthDate),
    member.role
  ].join('|')
}

export function exportMembersToJson(members: FamilyMember[]): string {
  const payload = members.map((member) => ({
    id: member.id || 0,
    firstName: member.firstName,
    lastName: member.lastName,
    patronymic: member.patronymic || '',
    gender: member.gender,
    birthDate: normalizeDateToDisplayFormat(member.birthDate),
    role: member.role,
    phoneNumber: member.phoneNumber || '',
    fatherId: member.fatherId ?? null,
    motherId: member.motherId ?? null,
    weddingDate: member.weddingDate || '',
    maidenName: member.maidenName || ''
  }))
  return JSON.stringify(payload, null, 2)
}

export function exportMembersToCsv(members: FamilyMember[]): string {
  const header = [
    'ID',
    'Имя',
    'Фамилия',
    'Отчество',
    'Пол',
    'Дата рождения',
    'Телефон',
    'Роль',
    'Дата свадьбы',
    'Девичья фамилия'
  ]
  const lines = members.map((member) =>
    [
      member.id || '',
      member.firstName,
      member.lastName,
      member.patronymic || '',
      member.gender,
      normalizeDateToDisplayFormat(member.birthDate),
      member.phoneNumber || '',
      ROLE_LABELS[member.role],
      member.weddingDate || '',
      member.maidenName || ''
    ]
      .map((value) => `"${String(value).replace(/"/g, '""')}"`)
      .join(',')
  )
  return [header.join(','), ...lines].join('\n')
}

function normalizeIncomingMember(raw: Partial<FamilyMember>): FamilyMember {
  return {
    id: typeof raw.id === 'number' ? raw.id : undefined,
    firstName: String(raw.firstName || '').trim(),
    lastName: String(raw.lastName || '').trim(),
    patronymic: (raw.patronymic || '').toString().trim() || null,
    gender: raw.gender === 'FEMALE' ? 'FEMALE' : 'MALE',
    birthDate: normalizeDateToDisplayFormat(String(raw.birthDate || '')),
    phoneNumber: (raw.phoneNumber || '').toString().trim() || null,
    role: (raw.role || 'OTHER') as FamilyMember['role'],
    photoUri: null,
    maidenName: (raw.maidenName || '').toString().trim() || null,
    fatherId: typeof raw.fatherId === 'number' ? raw.fatherId : null,
    motherId: typeof raw.motherId === 'number' ? raw.motherId : null,
    weddingDate: raw.weddingDate ? normalizeDateToDisplayFormat(String(raw.weddingDate)) : null
  }
}

export async function importMembersFromJsonText(
  jsonText: string,
  mode: 'merge' | 'replace'
): Promise<{
  inserted: number
  skipped: number
  relationsUpdated: number
}> {
  const parsed = JSON.parse(jsonText)
  if (!Array.isArray(parsed)) {
    throw new Error('JSON должен содержать массив членов семьи')
  }

  const normalizedIncoming = parsed.map((entry) => normalizeIncomingMember(entry as Partial<FamilyMember>))
  const currentMembers = mode === 'replace' ? [] : await getAllMembers()

  if (mode === 'replace') {
    await deleteAllMembers()
  }

  const incomingIdToNewId = new Map<number, number>()
  const insertedByFingerprint = new Map<string, number>()

  let inserted = 0
  let skipped = 0

  for (const incoming of normalizedIncoming) {
    const key = fingerprint(incoming)
    const duplicate = currentMembers.find((member) => fingerprint(member) === key)
    if (duplicate) {
      skipped += 1
      if (incoming.id && duplicate.id) incomingIdToNewId.set(incoming.id, duplicate.id)
      continue
    }

    const memberId = await upsertMember({
      ...incoming,
      fatherId: null,
      motherId: null,
      id: undefined
    })
    inserted += 1
    insertedByFingerprint.set(key, memberId)
    if (incoming.id) incomingIdToNewId.set(incoming.id, memberId)
  }

  const membersAfterInsert = await getAllMembers()
  let relationsUpdated = 0

  for (const incoming of normalizedIncoming) {
    const key = fingerprint(incoming)
    const localId =
      (incoming.id ? incomingIdToNewId.get(incoming.id) : undefined) || insertedByFingerprint.get(key)

    if (!localId) continue

    const localMember = membersAfterInsert.find((member) => member.id === localId)
    if (!localMember) continue

    const nextFatherId =
      incoming.fatherId && incomingIdToNewId.has(incoming.fatherId)
        ? incomingIdToNewId.get(incoming.fatherId) || null
        : localMember.fatherId || null

    const nextMotherId =
      incoming.motherId && incomingIdToNewId.has(incoming.motherId)
        ? incomingIdToNewId.get(incoming.motherId) || null
        : localMember.motherId || null

    if (nextFatherId !== localMember.fatherId || nextMotherId !== localMember.motherId) {
      await upsertMember({
        ...localMember,
        fatherId: nextFatherId,
        motherId: nextMotherId
      })
      relationsUpdated += 1
    }
  }

  await patchAppSettings({ appLockBySession: false })

  return { inserted, skipped, relationsUpdated }
}
