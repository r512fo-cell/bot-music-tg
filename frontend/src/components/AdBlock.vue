<script setup>
// Рекламный блок для размещения (home / library). Нет активной рекламы — ничего не выводим.
import { onActivated, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { haptic, openLink } from '../lib/telegram'
import AdCard from './AdCard.vue'

const props = defineProps({ placement: { type: String, required: true } })
const ad = ref(null)
let loadedAt = 0

async function load() {
  if (Date.now() - loadedAt < 120_000) return
  loadedAt = Date.now()
  try { ad.value = (await api.ads(props.placement)).ad } catch { ad.value = null }
}
function click() {
  if (!ad.value?.button_url) return
  haptic.tap()
  api.adClick(ad.value.id).catch(() => {})
  openLink(ad.value.button_url)
}

onMounted(load)
onActivated(load)
</script>

<template>
  <Transition name="ad">
    <div v-if="ad"><AdCard :ad="ad" @click="click" /></div>
  </Transition>
</template>

<style scoped>
.ad-enter-active { transition: opacity 0.4s var(--ease), transform 0.4s var(--ease); }
.ad-enter-from { opacity: 0; transform: translateY(6px); }
</style>
