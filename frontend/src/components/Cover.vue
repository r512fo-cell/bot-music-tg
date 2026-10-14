<script setup>
import { computed, ref, watch } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  track: { type: Object, default: null },
  size: { type: String, default: 's' }, // s | l
  radius: { type: String, default: '12px' },
  eager: { type: Boolean, default: false },
})

const loaded = ref(false)
const failed = ref(false)
const url = computed(() => props.track?.cover?.[props.size] || null)
const src = computed(() => (url.value && !failed.value ? url.value : null))
// Компонент переиспользуется для разных треков (мини-плеер, списки): сбрасываем состояние
watch(url, () => { loaded.value = false; failed.value = false })

// Детерминированный градиент для треков без обложки
const fallback = computed(() => {
  const s = `${props.track?.performer || ''}${props.track?.title || ''}${props.track?.id || 0}`
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  const a = h % 360
  const b = (a + 40 + (h % 80)) % 360
  return `linear-gradient(135deg, hsl(${a} 55% 42%), hsl(${b} 60% 26%))`
})
</script>

<template>
  <div class="cover" :style="{ borderRadius: radius, background: src && loaded ? 'transparent' : fallback }">
    <img
      v-if="src"
      :src="src"
      :class="{ show: loaded }"
      :loading="eager ? 'eager' : 'lazy'"
      decoding="async"
      alt=""
      draggable="false"
      @load="loaded = true"
      @error="failed = true"
    />
    <Icon v-if="!src" name="music" class="ph" />
    <slot />
  </div>
</template>

<style scoped>
.cover {
  position: relative;
  overflow: hidden;
  aspect-ratio: 1;
  flex-shrink: 0;
  isolation: isolate;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity 0.35s var(--ease);
}
img.show { opacity: 1; }
.ph {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 38%;
  height: 38%;
  color: rgba(255, 255, 255, 0.55);
}
</style>
