<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FamilyMember } from '@/types/models'
import { GENDER_OPTIONS, ROLE_OPTIONS, ROLE_LABELS } from '@/types/models'
import { normalizeDateToDisplayFormat } from '@/utils/date'
import { normalizePhone } from '@/utils/phone'
import { memberSchema } from '@/utils/validation'
import { compressImageToJpeg, fileToDataUrl } from '@/utils/image'

const props = defineProps<{
  modelValue?: FamilyMember | null
  allMembers: FamilyMember[]
  submitText?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  submit: [payload: FamilyMember]
  cancel: []
}>()

const form = reactive<FamilyMember>({
  firstName: '',
  lastName: '',
  patronymic: '',
  gender: 'MALE',
  birthDate: '',
  phoneNumber: '',
  role: 'OTHER',
  photoUri: '',
  maidenName: '',
  fatherId: null,
  motherId: null,
  weddingDate: ''
})

const errors = reactive<Record<string, string>>({})

function syncFromModel(source?: FamilyMember | null): void {
  const normalized = source || {
    firstName: '',
    lastName: '',
    patronymic: '',
    gender: 'MALE',
    birthDate: '',
    phoneNumber: '',
    role: 'OTHER',
    photoUri: '',
    maidenName: '',
    fatherId: null,
    motherId: null,
    weddingDate: ''
  }

  Object.assign(form, {
    ...normalized,
    birthDate: normalizeDateToDisplayFormat(normalized.birthDate || ''),
    weddingDate: normalized.weddingDate
      ? normalizeDateToDisplayFormat(normalized.weddingDate)
      : '',
    phoneNumber: normalized.phoneNumber || ''
  })
}

watch(
  () => props.modelValue,
  (value) => syncFromModel(value),
  { immediate: true }
)

const fatherOptions = computed(() =>
  props.allMembers.filter(
    (member) =>
      member.id !== props.modelValue?.id &&
      member.gender === 'MALE' &&
      ['FATHER', 'GRANDFATHER', 'UNCLE'].includes(member.role)
  )
)

const motherOptions = computed(() =>
  props.allMembers.filter(
    (member) =>
      member.id !== props.modelValue?.id &&
      member.gender === 'FEMALE' &&
      ['MOTHER', 'GRANDMOTHER', 'AUNT'].includes(member.role)
  )
)

const showWedding = computed(
  () => !['SON', 'DAUGHTER', 'GRANDSON', 'GRANDDAUGHTER', 'NEPHEW', 'NIECE'].includes(form.role)
)

const fileInputRef = ref<HTMLInputElement | null>(null)

async function onFileSelected(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  if (!target.files?.[0]) return
  const compressed = await compressImageToJpeg(target.files[0], { maxEdge: 1280, quality: 0.85 })
  form.photoUri = await fileToDataUrl(compressed)
  target.value = ''
}

function openFilePicker(): void {
  fileInputRef.value?.click()
}

function clearErrors(): void {
  for (const key of Object.keys(errors)) {
    delete errors[key]
  }
}

function submitForm(): void {
  clearErrors()
  const payload: FamilyMember = {
    id: props.modelValue?.id,
    ...form,
    firstName: form.firstName.trim(),
    lastName: form.lastName.trim(),
    patronymic: form.patronymic?.trim() || null,
    phoneNumber: form.phoneNumber ? normalizePhone(form.phoneNumber) : null,
    birthDate: normalizeDateToDisplayFormat(form.birthDate),
    weddingDate: showWedding.value && form.weddingDate ? normalizeDateToDisplayFormat(form.weddingDate) : null,
    maidenName: form.maidenName?.trim() || null,
    fatherId: form.fatherId || null,
    motherId: form.motherId || null,
    photoUri: form.photoUri || null
  }

  const result = memberSchema.safeParse(payload)
  if (!result.success) {
    for (const issue of result.error.issues) {
      const key = String(issue.path[0] || 'form')
      errors[key] = issue.message
    }
    return
  }

  emit('submit', payload)
}
</script>

<template>
  <form class="app-card member-form" @submit.prevent="submitForm">
    <div class="form-grid">
      <div class="field">
        <label>Имя</label>
        <input v-model="form.firstName" type="text" />
        <span v-if="errors.firstName" class="error">{{ errors.firstName }}</span>
      </div>
      <div class="field">
        <label>Фамилия</label>
        <input v-model="form.lastName" type="text" />
        <span v-if="errors.lastName" class="error">{{ errors.lastName }}</span>
      </div>
      <div class="field">
        <label>Отчество (не обязательно)</label>
        <input v-model="form.patronymic" type="text" />
      </div>
      <div class="field">
        <label>Пол</label>
        <select v-model="form.gender">
          <option v-for="option in GENDER_OPTIONS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>Дата рождения (dd.MM.yyyy)</label>
        <input v-model="form.birthDate" type="text" placeholder="01.01.2000" />
        <span v-if="errors.birthDate" class="error">{{ errors.birthDate }}</span>
      </div>
      <div class="field">
        <label>Роль</label>
        <select v-model="form.role">
          <option v-for="option in ROLE_OPTIONS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>Телефон</label>
        <input v-model="form.phoneNumber" type="text" placeholder="+79991234567" />
        <span v-if="errors.phoneNumber" class="error">{{ errors.phoneNumber }}</span>
      </div>
      <div class="field">
        <label>Девичья фамилия</label>
        <input v-model="form.maidenName" type="text" />
      </div>
      <div class="field" v-if="showWedding">
        <label>Дата свадьбы (не обязательно)</label>
        <input v-model="form.weddingDate" type="text" placeholder="10.10.2015" />
        <span v-if="errors.weddingDate" class="error">{{ errors.weddingDate }}</span>
      </div>
      <div class="field">
        <label>Отец</label>
        <select v-model.number="form.fatherId">
          <option :value="null">Не выбран</option>
          <option v-for="member in fatherOptions" :key="member.id" :value="member.id">
            {{ member.firstName }} {{ member.lastName }} ({{ ROLE_LABELS[member.role] }})
          </option>
        </select>
      </div>
      <div class="field">
        <label>Мать</label>
        <select v-model.number="form.motherId">
          <option :value="null">Не выбрана</option>
          <option v-for="member in motherOptions" :key="member.id" :value="member.id">
            {{ member.firstName }} {{ member.lastName }} ({{ ROLE_LABELS[member.role] }})
          </option>
        </select>
      </div>
    </div>

    <div class="photo-field">
      <div class="photo-preview">
        <img v-if="form.photoUri" :src="form.photoUri" alt="Фото" />
        <div v-else class="photo-empty">Фото не выбрано</div>
      </div>
      <div class="btn-row">
        <button type="button" class="btn-action" @click="openFilePicker">Выбрать фото</button>
        <button type="button" class="btn-action danger" @click="form.photoUri = ''" :disabled="!form.photoUri">
          Удалить фото
        </button>
      </div>
      <input
        ref="fileInputRef"
        type="file"
        accept="image/*"
        style="display: none"
        @change="onFileSelected"
      />
    </div>

    <div class="btn-row submit-row">
      <button class="btn-action primary" type="submit" :disabled="busy">
        {{ submitText || 'Сохранить' }}
      </button>
      <button class="btn-action" type="button" @click="emit('cancel')" :disabled="busy">Отмена</button>
    </div>
  </form>
</template>

<style scoped>
.member-form {
  padding: 20px;
}

.photo-field {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.photo-preview {
  width: 140px;
  height: 140px;
  border-radius: 12px;
  border: 1px solid var(--color-glass-border);
  overflow: hidden;
}

.photo-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.photo-empty {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--color-text-muted);
  font-size: 0.82rem;
}

.submit-row {
  margin-top: 18px;
}
</style>
