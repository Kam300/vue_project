<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MemberForm from '@/components/forms/MemberForm.vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useMemberStore } from '@/stores/memberStore'
import { useAppStore } from '@/stores/appStore'
import type { FamilyMember } from '@/types/models'
import { ensureFaceApiPayload } from '@/utils/image'
import { registerFace } from '@/services/api'
import { toServerMemberId } from '@/services/familySync'

const route = useRoute()
const router = useRouter()
const memberStore = useMemberStore()
const appStore = useAppStore()

const busy = ref(false)
const savingNote = ref('')
const addPhotoInput = ref<HTMLInputElement | null>(null)

const memberId = computed(() => Number(route.params.id || 0) || 0)
const isCreateMode = computed(() => route.path.endsWith('/new'))

const currentMember = computed(() => {
  if (isCreateMode.value) return null
  return memberStore.members.find((member) => member.id === memberId.value) || null
})

const memberPhotos = computed(() =>
  memberStore.photos
    .filter((photo) => photo.memberId === memberId.value)
    .sort((a, b) => b.dateAdded - a.dateAdded)
)

onMounted(async () => {
  if (!memberStore.members.length) {
    await memberStore.refresh()
  }
})

async function saveMember(payload: FamilyMember): Promise<void> {
  busy.value = true
  savingNote.value = ''
  try {
    const savedId = await memberStore.saveMember(payload)
    if (payload.photoUri) {
      try {
        const imagePayload = await ensureFaceApiPayload(payload.photoUri)
        const serverId = toServerMemberId(appStore.settings.deviceId, savedId)
        const result = await registerFace({
          member_id: String(serverId),
          member_name: `${payload.firstName} ${payload.lastName}`.trim(),
          image: imagePayload
        })
        savingNote.value = result.success
          ? 'Профиль сохранен, лицо зарегистрировано в AI.'
          : `Профиль сохранен, но AI регистрация не выполнена: ${result.error || 'ошибка'}`
      } catch (error) {
        savingNote.value = `Профиль сохранен, но AI регистрация завершилась ошибкой: ${
          (error as Error).message
        }`
      }
    } else {
      savingNote.value = 'Профиль сохранен.'
    }

    if (isCreateMode.value) {
      await router.replace(`/app/members/${savedId}`)
    } else {
      await memberStore.refresh()
    }
  } finally {
    busy.value = false
  }
}

function openAddPhoto(): void {
  addPhotoInput.value?.click()
}

async function onAddGalleryPhoto(event: Event): Promise<void> {
  if (!memberId.value) return
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  const dataUrl = await (await import('@/utils/image')).fileToDataUrl(file)
  await memberStore.addPhotoToMember(memberId.value, dataUrl, { isProfilePhoto: false })
  target.value = ''
}

async function deletePhoto(photoId: number | undefined): Promise<void> {
  if (!photoId) return
  if (!window.confirm('Удалить выбранное фото?')) return
  await memberStore.removePhoto(photoId)
}

async function deleteCurrentMember(): Promise<void> {
  if (!currentMember.value?.id) return
  if (!window.confirm('Удалить члена семьи и все его фото?')) return
  await memberStore.removeMember(currentMember.value.id)
  await router.replace('/app/members')
}
</script>

<template>
  <section class="app-page">
    <div class="app-container">
      <PageHeader
        :title="isCreateMode ? 'Новый член семьи' : 'Профиль и редактирование'"
        subtitle="Поля, семейные связи, фото профиля и галерея"
      />

      <MemberForm
        :model-value="currentMember"
        :all-members="memberStore.members"
        :busy="busy"
        :submit-text="isCreateMode ? 'Создать профиль' : 'Сохранить изменения'"
        @submit="saveMember"
        @cancel="router.push('/app/members')"
      />

      <article class="app-card gallery-card" v-if="!isCreateMode && currentMember?.id">
        <div class="gallery-head">
          <h2>Галерея фото</h2>
          <div class="btn-row">
            <button class="btn-action" @click="openAddPhoto">Добавить фото в галерею</button>
            <button class="btn-action danger" @click="deleteCurrentMember">Удалить профиль</button>
          </div>
        </div>
        <div class="status-line" v-if="savingNote">{{ savingNote }}</div>
        <div class="empty-state" v-if="!memberPhotos.length">Фото галереи пока отсутствуют.</div>
        <div v-else class="gallery-grid">
          <figure v-for="photo in memberPhotos" :key="photo.id" class="gallery-item">
            <img :src="photo.photoUri" alt="Фото члена семьи" />
            <figcaption>
              <span>{{ new Date(photo.dateAdded).toLocaleString('ru-RU') }}</span>
              <button class="btn-action danger" @click="deletePhoto(photo.id)">Удалить</button>
            </figcaption>
          </figure>
        </div>
        <input
          ref="addPhotoInput"
          type="file"
          accept="image/*"
          style="display: none"
          @change="onAddGalleryPhoto"
        />
      </article>
    </div>
  </section>
</template>

<style scoped>
.gallery-card {
  margin-top: 16px;
  padding: 16px;
}

.gallery-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.gallery-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}

.gallery-item {
  border: 1px solid var(--color-glass-border);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
}

.gallery-item img {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
}

.gallery-item figcaption {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px;
  font-size: 0.78rem;
}
</style>
