<script setup>
// Полный список открытых альбомов слушателей
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { t, tp } from '../lib/i18n'
import AlbumArt from '../components/AlbumArt.vue'
import Icon from '../components/Icon.vue'
import InfiniteLoader from '../components/InfiniteLoader.vue'
import ViewsBadge from '../components/ViewsBadge.vue'

const items = ref(null)
const next = ref(0)
const loading = ref(false)

async function load() {
  if (loading.value || next.value == null) return
  loading.value = true
  try {
    const res = await api.publicAlbums({ offset: next.value, limit: 20 })
    items.value = [...(items.value || []), ...res.items]
    next.value = res.next_offset
  } catch { items.value = items.value || [] } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('home.albums') }}</h1>
    <div v-if="items && !items.length" class="empty">
      <div class="empty-icon"><Icon name="album" /></div>
      <p>{{ t('albums.empty') }}</p>
    </div>
    <div class="grid">
      <template v-if="!items">
        <div v-for="i in 4" :key="i"><div class="skeleton sk" /></div>
      </template>
      <RouterLink
        v-for="a in items || []"
        :key="a.id"
        :to="{ name: 'shared-album', params: { code: a.share_param.slice(2) } }"
        class="card-a"
      >
        <div class="art-box"><AlbumArt :album="a" radius="18px" /><ViewsBadge :views="a.views" /></div>
        <b class="ellipsis">{{ a.name }}</b>
        <small class="ellipsis">{{ a.owner_name }} · {{ tp(a.track_count, 'units.tracks') }}</small>
      </RouterLink>
    </div>
    <InfiniteLoader v-if="items?.length" :disabled="loading || next == null" @load="load" />
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px 12px; }
.card-a { display: flex; flex-direction: column; gap: 2px; min-width: 0; transition: transform 0.15s var(--ease); }
.card-a:active { transform: scale(0.97); }
.card-a b { font-size: 15px; font-weight: 600; margin-top: 8px; }
.card-a small { font-size: 12.5px; color: var(--text-2); }
.sk { aspect-ratio: 1; border-radius: 18px; }
.art-box { position: relative; }
</style>
