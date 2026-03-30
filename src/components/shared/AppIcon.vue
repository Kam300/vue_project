<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
    filled?: boolean
    label?: string
  }>(),
  {
    size: 20,
    filled: false,
    label: ''
  }
)

function resolveSize(): string {
  return typeof props.size === 'number' ? `${props.size}px` : props.size
}
</script>

<template>
  <span
    class="app-icon material-symbols-outlined"
    :class="{ filled }"
    :style="{ fontSize: resolveSize() }"
    :aria-label="label || undefined"
    :aria-hidden="label ? 'false' : 'true'"
    >{{ name }}</span
  >
</template>

<style scoped>
.app-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  font-variation-settings:
    'FILL' 0,
    'wght' 500,
    'GRAD' 0,
    'opsz' 24;
}

.app-icon.filled {
  font-variation-settings:
    'FILL' 1,
    'wght' 500,
    'GRAD' 0,
    'opsz' 24;
}
</style>
