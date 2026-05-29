import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { FamilyMember, MemberPhoto } from '@/types/models'
import {
  addMemberPhoto,
  clearMemberPhotos,
  deleteAllMembers,
  deleteMember,
  deleteMemberPhoto,
  getAllMembers,
  getAllPhotos,
  getMemberById,
  getMemberPhotos,
  upsertMember
} from '@/db/repositories'
import { imageSha256, makePerceptualHash } from '@/utils/image'
import { useAppStore } from '@/stores/appStore'
import { deleteFace, clearAllFaces } from '@/services/api'
import { toServerMemberId } from '@/services/familySync'
import { withPendingChange } from '@/stores/withPendingChange'

export const useMemberStore = defineStore('members', () => {
  const members = ref<FamilyMember[]>([])
  const photos = ref<MemberPhoto[]>([])
  // not synced — UI-only loading flag
  const loading = ref(false)

  const membersById = computed(() => new Map(members.value.map((member) => [member.id as number, member])))

  // not synced — read-only refresh of local IndexedDB into Pinia state
  async function refresh(): Promise<void> {
    loading.value = true
    try {
      const [nextMembers, nextPhotos] = await Promise.all([getAllMembers(), getAllPhotos()])
      members.value = nextMembers
      photos.value = nextPhotos
    } finally {
      loading.value = false
    }
  }

  async function saveMember(member: FamilyMember): Promise<number> {
    const isCreate = member.id === undefined || member.id === null
    return withPendingChange(
      isCreate ? 'member.create' : 'member.update',
      isCreate ? '' : String(member.id),
      member,
      async () => {
        const memberId = await upsertMember(member)
        await refresh()
        return memberId
      }
    )
  }

  async function removeMember(memberId: number): Promise<void> {
    await withPendingChange(
      'member.delete',
      String(memberId),
      { memberId },
      async () => {
        // Удаляем лицо с сервера распознавания (параллельно с локальным удалением).
        // Ошибка сети не должна блокировать локальное удаление.
        try {
          const appStore = useAppStore()
          const serverId = toServerMemberId(appStore.settings.deviceId, memberId)
          await deleteFace(serverId)
        } catch (reason) {
          // eslint-disable-next-line no-console
          console.warn('[memberStore] deleteFace on server failed:', reason)
        }
        await deleteMember(memberId)
        await refresh()
      }
    )
  }

  async function removeAllMembers(): Promise<void> {
    await withPendingChange(
      'tree.metadata.update',
      '',
      { action: 'clear-all-members' },
      async () => {
        try {
          const appStore = useAppStore()
          await clearAllFaces(appStore.settings.deviceId)
        } catch (reason) {
          // eslint-disable-next-line no-console
          console.warn('[memberStore] clearAllFaces on server failed:', reason)
        }
        await deleteAllMembers()
        await refresh()
      }
    )
  }

  async function removeAllMemberPhotos(memberId: number): Promise<void> {
    await withPendingChange(
      'member.update',
      String(memberId),
      { memberId, action: 'clear-photos' },
      async () => {
        await clearMemberPhotos(memberId)
        await refresh()
      }
    )
  }

  async function addPhotoToMember(
    memberId: number,
    photoUri: string,
    options: {
      description?: string
      isProfilePhoto?: boolean
    } = {}
  ): Promise<'saved' | 'duplicate'> {
    // Duplicate detection runs BEFORE we enqueue anything, so a no-op upload
    // does not pollute the Pending_Changes_Buffer.
    const newHash = await makePerceptualHash(photoUri)
    const currentPhotos = await getMemberPhotos(memberId)
    for (const existing of currentPhotos) {
      try {
        const existingHash = existing.imageHash || (await makePerceptualHash(existing.photoUri))
        if (existingHash === newHash) {
          return 'duplicate'
        }
      } catch {
        // ignore corrupted image and continue
      }
    }

    const exactHash = await imageSha256(photoUri).catch(() => '')

    return withPendingChange(
      'member.update',
      String(memberId),
      {
        memberId,
        action: 'add-photo',
        description: options.description ?? '',
        isProfilePhoto: Boolean(options.isProfilePhoto)
      },
      async () => {
        await addMemberPhoto({
          memberId,
          photoUri,
          dateAdded: Date.now(),
          description: options.description || '',
          isProfilePhoto: Boolean(options.isProfilePhoto),
          imageHash: newHash || exactHash
        })

        if (options.isProfilePhoto) {
          const member = await getMemberById(memberId)
          if (member) {
            await upsertMember({ ...member, photoUri })
          }
        }

        await refresh()
        return 'saved' as const
      }
    )
  }

  async function removePhoto(photoId: number): Promise<void> {
    // Resolve the owning memberId for the targetId before wrapping.
    const owning = photos.value.find((p) => p.id === photoId)
    const ownerMemberId = owning?.memberId
    await withPendingChange(
      'member.update',
      ownerMemberId !== undefined ? String(ownerMemberId) : '',
      { photoId, memberId: ownerMemberId },
      async () => {
        await deleteMemberPhoto(photoId)
        await refresh()
      }
    )
  }

  return {
    members,
    photos,
    loading,
    membersById,
    refresh,
    saveMember,
    removeMember,
    removeAllMembers,
    removeAllMemberPhotos,
    addPhotoToMember,
    removePhoto
  }
})
