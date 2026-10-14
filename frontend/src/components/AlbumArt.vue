<script setup>
// Обложка альбома: мозаика из обложек треков или градиент с иконкой.
import { computed } from 'vue'

const props = defineProps({
  album: { type: Object, required: true },
  radius: { type: String, default: '16px' },
})
const covers = computed(() => props.album.covers || [])
const gradient = computed(() => {
  // FNV-1a: похожие названия («Rock 1», «Rock 2») дают заметно разные цвета
  let h = 0x811c9dc5
  for (const ch of `${props.album.name}#${props.album.id}`) h = Math.imul(h ^ ch.codePointAt(0), 0x01000193) >>> 0
  h ^= h >>> 13
  const a = h % 360
  return `linear-gradient(140deg, hsl(${a} 62% 52%), hsl(${(a + 50) % 360} 58% 30%))`
})
</script>

<template>
  <div class="art" :style="{ borderRadius: radius, background: covers.length >= 1 ? '#15151a' : gradient }">
    <div v-if="covers.length >= 4" class="mosaic">
      <img v-for="c in covers.slice(0, 4)" :key="c" :src="c" alt="" loading="lazy" decoding="async" />
    </div>
    <img v-else-if="covers.length" :src="covers[0]" alt="" class="single" loading="lazy" decoding="async" />
    <span class="emoji" :class="{ badge: covers.length }">{{ album.icon }}</span>
  </div>
</template>

<style scoped>
.art {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  container-type: inline-size;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.07);
}
.mosaic { display: grid; grid-template-columns: 1fr 1fr; width: 100%; height: 100%; }
.mosaic img, .single { width: 100%; height: 100%; object-fit: cover; }
.emoji {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 40px;
  font-size: 38cqw;
  line-height: 1;
  filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.35));
}
.emoji.badge {
  inset: auto 6% 6% auto;
  width: 30%;
  height: 30%;
  font-size: 16px;
  font-size: 16cqw;
  border-radius: 30%;
  background: rgba(10, 10, 14, 0.55);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
</style>
