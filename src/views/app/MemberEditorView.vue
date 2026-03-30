<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MemberForm from '@/components/forms/MemberForm.vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AppIcon from '@/components/shared/AppIcon.vue'
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
const savingNoteType = ref<'success' | 'warning' | ''>('')
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
  savingNoteType.value = ''
  try {
    const savedId = await memberStore.saveMember(payload)
    if (payload.photoUri) {
      try {
        const imagePayload = await ensureFaceApiPayload(payload.photoUri)
        const serverId = toServerMemberId(appStore.settings.deviceId, {
          ...payload
        })
        const result = await registerFace({
          member_id: serverId,
          member_name: `${payload.firstName} ${payload.lastName}`.trim(),
          image: imagePayload
        })
        if (result.success) {
          savingNoteType.value = 'success'
          savingNote.value = 'Профиль сохранен, лицо зарегистрировано в AI.'
        } else {
          savingNoteType.value = 'warning'
          savingNote.value = `Профиль сохранен, но AI регистрация не выполнена: ${result.error || 'ошибка'}`
        }
      } catch (error) {
        savingNoteType.value = 'warning'
        savingNote.value = `Профиль сохранен, но AI регистрация завершилась ошибкой: ${
          (error as Error).message
        }`
      }
    } else {
      savingNoteType.value = 'success'
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
        :icon="isCreateMode ? 'person_add' : 'edit'"
        :title="isCreateMode ? 'Новый член семьи' : 'Профиль и редактирование'"
        subtitle="Поля, семейные связи, фото профиля и галерея"
      />

      <!-- Profile preview for existing member -->
      <div v-if="!isCreateMode && currentMember" class="profile-preview">
        <div class="preview-avatar-wrap">
          <img v-if="currentMember.photoUri" :src="currentMember.photoUri" class="preview-avatar" />
          <div v-else class="preview-avatar placeholder">
            <AppIcon name="person" :size="28" />
          </div>
        </div>
        <div class="preview-info">
          <h2>{{ currentMember.firstName }} {{ currentMember.lastName }}</h2>
          <p v-if="currentMember.patronymic">{{ currentMember.patronymic }}</p>
          <p v-if="currentMember.socialRoles" class="tradition-line">{{ currentMember.socialRoles }}</p>
        </div>
      </div>

      <MemberForm
        :model-value="currentMember"
        :all-members="memberStore.members"
        :busy="busy"
        :submit-text="isCreateMode ? 'Создать профиль' : 'Сохранить изменения'"
        @submit="saveMember"
        @cancel="router.push('/app/members')"
      />

      <!-- Saving note -->
      <div v-if="savingNote" class="save-note" :class="{ success: savingNoteType === 'success', warning: savingNoteType === 'warning' }">
        {{ savingNote }}
      </div>

      <!-- Gallery section -->
      <article class="app-card gallery-card" v-if="!isCreateMode && currentMember?.id">
        <div class="gallery-head">
          <h2 class="with-icon">
            <AppIcon name="photo_library" :size="20" />
            Галерея фото
          </h2>
          <div class="btn-row">
            <button class="btn-action" @click="openAddPhoto">
              <AppIcon name="add" :size="16" />
              Добавить фото
            </button>
            <button class="btn-action danger" @click="deleteCurrentMember">
              <AppIcon name="delete" :size="16" />
              Удалить профиль
            </button>
          </div>
        </div>

        <div class="empty-state" v-if="!memberPhotos.length">
          <span class="empty-state-icon">
            <AppIcon name="photo_camera" :size="32" />
          </span>
          <p>Фото галереи пока отсутствуют.</p>
        </div>

        <div v-else class="gallery-grid">
          <figure v-for="photo in memberPhotos" :key="photo.id" class="gallery-item">
            <img :src="photo.photoUri" alt="Фото члена семьи" />
            <figcaption>
              <span>{{ new Date(photo.dateAdded).toLocaleString('ru-RU') }}</span>
              <button class="btn-action danger" @click="deletePhoto(photo.id)">
                <AppIcon name="close" :size="16" />
              </button>
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
.profile-preview {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding: 16px;
  background: var(--color-glass);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-lg);
}

.preview-avatar-wrap {
  flex-shrink: 0;
}

.preview-avatar {
  width: 72px;
  height: 72px;
  border-radius: 16px;
  object-fit: cover;
  border: 2px solid rgba(124, 92, 252, 0.3);
  box-shadow: 0 0 20px rgba(124, 92, 252, 0.15);
}

.preview-avatar.placeholder {
  display: grid;
  place-items: center;
  background: var(--color-surface);
  font-size: 2rem;
}

.preview-info h2 {
  font-size: 1.3rem;
  font-weight: 700;
}

.preview-info p {
  color: var(--color-text-secondary);
}

.tradition-line {
  color: var(--color-accent-light);
}

.save-note {
  margin-top: 12px;
  padding: 12px 16px;
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  border: 1px solid var(--color-glass-border);
  animation: fadeInUp 0.3s ease-out;
}

.save-note.success {
  border-color: rgba(52, 211, 153, 0.3);
  background: rgba(52, 211, 153, 0.06);
}

.save-note.warning {
  border-color: rgba(251, 191, 36, 0.3);
  background: rgba(251, 191, 36, 0.06);
}

.gallery-card {
  margin-top: 16px;
  padding: 20px;
}

.gallery-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.gallery-head h2 {
  font-size: 1.1rem;
}

.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.gallery-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}

.gallery-item {
  border: 1px solid var(--color-glass-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--input-bg);
  transition: all var(--transition-normal);
}

.gallery-item:hover {
  border-color: rgba(124, 92, 252, 0.3);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
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
  padding: 8px 10px;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
</style>
