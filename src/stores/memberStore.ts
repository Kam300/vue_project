import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { FamilyMember, MemberPhoto } from '@/types/models'
import {
  addMemberPhoto,
  clearMemberPhotos,
  deleteMember,
  deleteMemberPhoto,
  getAllMembers,
  getAllPhotos,
  getMemberById,
  getMemberPhotos,
  upsertMember
} from '@/db/repositories'
import { imageSha256, makePerceptualHash } from '@/utils/image'

export const useMemberStore = defineStore('members', () => {
  const members = ref<FamilyMember[]>([])
  const photos = ref<MemberPhoto[]>([])
  const loading = ref(false)

  const membersById = computed(() => new Map(members.value.map((member) => [member.id as number, member])))

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
    const memberId = await upsertMember(member)
    await refresh()
    return memberId
  }

  async function removeMember(memberId: number): Promise<void> {
    await deleteMember(memberId)
    await refresh()
  }

  async function removeAllMemberPhotos(memberId: number): Promise<void> {
    await clearMemberPhotos(memberId)
    await refresh()
  }

  async function addPhotoToMember(
    memberId: number,
    photoUri: string,
    options: {
      description?: string
      isProfilePhoto?: boolean
    } = {}
  ): Promise<'saved' | 'duplicate'> {
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
    return 'saved'
  }

  async function removePhoto(photoId: number): Promise<void> {
    await deleteMemberPhoto(photoId)
    await refresh()
  }

  return {
    members,
    photos,
    loading,
    membersById,
    refresh,
    saveMember,
    removeMember,
    removeAllMemberPhotos,
    addPhotoToMember,
    removePhoto
  }
})
