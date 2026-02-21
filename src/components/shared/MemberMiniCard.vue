<script setup lang="ts">
import type { FamilyMember } from '@/types/models'
import { ROLE_LABELS } from '@/types/models'

defineProps<{
  member: FamilyMember
  compact?: boolean
}>()
</script>

<template>
  <article class="member-card" :class="{ compact }">
    <img v-if="member.photoUri" :src="member.photoUri" class="avatar" alt="Фото профиля" />
    <div v-else class="avatar placeholder">👤</div>
    <div class="meta">
      <h3>{{ member.firstName }} {{ member.lastName }}</h3>
      <p>{{ ROLE_LABELS[member.role] }}</p>
      <small>{{ member.birthDate }}</small>
    </div>
  </article>
</template>

<style scoped>
.member-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid var(--color-glass-border);
  background: rgba(255, 255, 255, 0.03);
}

.member-card.compact {
  flex-direction: column;
  text-align: center;
  align-items: center;
}

.avatar {
  width: 54px;
  height: 54px;
  border-radius: 12px;
  object-fit: cover;
  border: 1px solid var(--color-glass-border);
}

.avatar.placeholder {
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.08);
}

.meta h3 {
  font-size: 0.95rem;
}

.meta p {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.meta small {
  color: var(--color-text-muted);
  font-size: 0.78rem;
}
</style>
