<script setup>
import { computed, onActivated, ref, watch } from 'vue'
import { api } from '../lib/api'
import { t, tp } from '../lib/i18n'
import { duration, storage } from '../lib/format'
import { haptic } from '../lib/telegram'
import { useLibrary } from '../stores/library'
import { useAlbums } from '../stores/albums'
import { usePlayer } from '../stores/player'
import { useUi } from '../stores/ui'
import AdBlock from '../components/AdBlock.vue'
import AlbumArt from '../components/AlbumArt.vue'
import Icon from '../components/Icon.vue'
import TrackList from '../components/TrackList.vue'
import SkeletonRows from '../components/SkeletonRows.vue'

defineOptions({ name: 'LibraryView' })

const lib = useLibrary()
const albums = useAlbums()
const player = usePlayer()
const ui = useUi()
const TABS = ['favorites', 'albums', 'history']
const tab = ref(TABS.includes(storage.get('library.tab')) ? storage.get('library.tab') : 'favorites')
const favorites = ref(null)
const history = ref(null)
let favVersion = -1
let albumsVersion = -1

async function refresh() {
  try {
    if (tab.value === 'favorites' && (favorites.value == null || favVersion !== lib.favoritesVersion)) {
      const v = lib.favoritesVersion
      favorites.value = (await api.favorites({ limit: 100 })).items
      favVersion = v // версию запоминаем только после успешной загрузки
    }
    if (tab.value === 'albums' && (albums.items == null || albumsVersion !== albums.version)) {
      const v = albums.version
      await albums.load()
      albumsVersion = v
    }
    if (tab.value === 'history') history.value = (await api.history()).items
  } catch {}
}
const list = computed(() => (tab.value === 'favorites' ? favorites.value : history.value))

function playAll(shuffle) { player.playAll(list.value, shuffle) }
function setTab(id) { tab.value = id; haptic.select(); storage.set('library.tab', id) }
function createAlbum() {
  if (!albums.canCreate) { haptic.error(); ui.toast(albums.blockText); return }
  ui.openEditor({ mode: 'create' })
}

watch(tab, refresh)
watch(() => albums.version, () => { if (tab.value === 'albums') refresh() })
onActivated(refresh) // внутри KeepAlive срабатывает и при первом показе
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('library.title') }}</h1>
    <div class="segmented" role="tablist">
      <button v-for="id in TABS" :key="id" role="tab" :aria-selected="tab === id" :class="{ on: tab === id }" @click="setTab(id)">
        <Icon :name="{ favorites: 'heart', albums: 'album', history: 'clock' }[id]" :size="16" />{{ t(`library.${id}`) }}
      </button>
      <span class="slider" :style="{ transform: `translateX(${TABS.indexOf(tab) * 100}%)` }" />
    </div>

    <!-- Реклама: над списком -->
    <AdBlock placement="library" class="lib-ad" />

    <!-- ========== Альбомы -->
    <template v-if="tab === 'albums'">
      <div class="albums-head">
        <span class="muted">{{ t('album.slots', { used: albums.items?.length ?? 0, max: albums.limit }) }}</span>
      </div>
      <div class="albums">
        <button class="album-card create" :class="{ disabled: !albums.canCreate }" @click="createAlbum">
          <span class="create-art"><Icon name="plus" :size="30" /></span>
          <b>{{ t('album.new') }}</b>
          <small>{{ albums.canCreate ? t('album.new_hint') : albums.blockText }}</small>
        </button>
        <template v-if="albums.items">
          <RouterLink v-for="a in albums.items" :key="a.id" :to="{ name: 'album', params: { id: a.id } }" class="album-card">
            <AlbumArt :album="a" radius="18px" />
            <b class="ellipsis">{{ a.name }}</b>
            <small>{{ tp(a.track_count, 'units.tracks') }}<template v-if="a.duration"> · {{ duration(a.duration) }}</template></small>
          </RouterLink>
        </template>
        <template v-else>
          <div v-for="i in 3" :key="i" class="album-card"><div class="skeleton sk-art" /></div>
        </template>
      </div>
    </template>

    <!-- ========== Избранное / История -->
    <template v-else>
      <div v-if="list?.length" class="actions">
        <button class="btn btn-primary" @click="playAll(false)"><Icon name="play" :size="18" />{{ t('common.listen') }}</button>
        <button class="btn" @click="playAll(true)"><Icon name="shuffle" :size="18" />{{ t('common.shuffle') }}</button>
      </div>
      <SkeletonRows v-if="list == null" :count="6" />
      <TrackList v-else-if="list.length" :tracks="list" />
      <div v-else class="empty">
        <div class="empty-icon"><Icon :name="tab === 'favorites' ? 'heart' : 'clock'" /></div>
        <p>{{ tab === 'favorites' ? t('library.favorites_empty') : t('library.history_empty') }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.segmented {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  padding: 4px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
}
.segmented button {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  transition: color 0.2s;
  white-space: nowrap;
}
.segmented button.on { color: var(--text); }
.slider {
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc((100% - 8px) / 3);
  height: 38px;
  border-radius: 10px;
  background: var(--surface-3);
  transition: transform 0.35s var(--ease);
}
.lib-ad { margin-top: 14px; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0 10px; }

.albums-head { margin: 16px 2px 10px; font-size: 13px; }
.albums { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px 12px; }
.album-card { display: flex; flex-direction: column; gap: 3px; min-width: 0; text-align: left; transition: transform 0.15s var(--ease); }
.album-card:active { transform: scale(0.97); }
.album-card b { font-size: 15px; font-weight: 600; margin-top: 7px; }
.album-card small { font-size: 12.5px; color: var(--text-2); }
.create-art {
  aspect-ratio: 1;
  border-radius: 18px;
  display: grid;
  place-items: center;
  color: var(--accent);
  border: 1.5px dashed rgba(255, 255, 255, 0.2);
  background: rgb(var(--accent-rgb) / 0.06);
}
.create.disabled { opacity: 0.55; }
.sk-art { aspect-ratio: 1; border-radius: 18px; }
@media (max-width: 350px) { .segmented button { font-size: 12.5px; gap: 4px; } }
</style>
