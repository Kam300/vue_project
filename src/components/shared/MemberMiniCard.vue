<script setup lang="ts">
import type { FamilyMember } from '@/types/models'
import { ROLE_LABELS } from '@/types/models'
import AppIcon from '@/components/shared/AppIcon.vue'

defineProps<{
  member: FamilyMember
  compact?: boolean
}>()
</script>

<template>
  <article class="member-card" :class="{ compact }">
    <div class="avatar-wrap">
      <img v-if="member.photoUri" :src="member.photoUri" class="avatar" alt="Фото профиля" />
      <div v-else class="avatar placeholder">
        <AppIcon name="person" :size="22" />
      </div>
    </div>
    <div class="meta">
      <h3>{{ member.firstName }} {{ member.lastName }}</h3>
      <p>{{ ROLE_LABELS[member.role] }}</p>
      <small v-if="member.socialRoles" class="tradition-line">{{ member.socialRoles }}</small>
      <small v-if="member.birthDate">{{ member.birthDate }}</small>
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
  background: var(--input-bg);
  transition: all var(--transition-normal);
}

.member-card:hover {
  border-color: var(--card-hover-border);
  background: var(--card-hover-bg);
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.member-card.compact {
  flex-direction: column;
  text-align: center;
  align-items: center;
}

.avatar-wrap {
  position: relative;
  flex-shrink: 0;
}

.avatar {
  width: 54px;
  height: 54px;
  border-radius: 12px;
  object-fit: cover;
  border: 1px solid var(--color-glass-border);
  transition: all var(--transition-fast);
}

.member-card:hover .avatar {
  border-color: var(--color-accent);
  box-shadow: 0 0 14px rgba(124, 92, 252, 0.3);
}

.avatar.placeholder {
  display: grid;
  place-items: center;
  background: var(--color-surface);
  font-size: 1.5rem;
}

.meta h3 {
  font-size: 0.95rem;
  font-weight: 600;
}

.meta p {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.meta small {
  color: var(--color-text-muted);
  font-size: 0.78rem;
}

.tradition-line {
  color: var(--color-accent-light);
}
</style>
