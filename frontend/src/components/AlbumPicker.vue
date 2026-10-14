<script setup>
// «Добавить в альбом»: отметки альбомов, где уже есть трек, переключение одним нажатием.
import { computed, ref, watch } from 'vue'
import { useUi } from '../stores/ui'
import { useAlbums } from '../stores/albums'
import { api } from '../lib/api'
import { artist } from '../lib/format'
import { errorText, t, tp } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import AlbumArt from './AlbumArt.vue'
import Cover from './Cover.vue'
import Icon from './Icon.vue'

const ui = useUi()
const albums = useAlbums()
const track = computed(() => ui.pickerTrack)
const list = ref(null)
const busy = ref(new Set())

watch(track, async (tr) => {
  list.value = null
  if (!tr) return
  try {
    const res = await api.albums.list(tr.id)
    list.value = res.items
    albums.items = res.items.map(({ has_track, ...a }) => a)
  } catch (e) {
    ui.toast(errorText(e))
    ui.closePicker()
  }
})

async function toggle(a) {
  if (busy.value.has(a.id)) return
  busy.value = new Set([...busy.value, a.id])
  const had = a.has_track
  a.has_track = !had
  haptic.select()
  try {
    if (had) await albums.removeTrack(a.id, track.value.id)
    else await albums.addTrack(a.id, track.value.id)
    a.track_count += had ? -1 : 1
    ui.toast(had ? t('album.removed_from', { name: a.name }) : t('album.added_to', { name: a.name }))
  } catch (e) {
    a.has_track = had
    ui.toast(errorText(e, { n: albums.limit }))
    haptic.error()
  } finally {
    const s = new Set(busy.value); s.delete(a.id); busy.value = s
  }
}

function createNew() {
  const tr = track.value
  ui.closePicker()
  ui.openEditor({ mode: 'create', trackId: tr.id })
}
const full = computed(() => albums.restricted || (list.value?.length || 0) >= albums.limit)
</script>

<template>
  <Transition name="sheet">
    <div v-if="track" class="backdrop" @click.self="ui.closePicker()">
      <div class="sheet glass" role="dialog" aria-modal="true">
        <div class="grab" />
        <div class="head">
          <Cover :track="track" radius="10px" class="head-cover" />
          <div class="meta">
            <div class="label">{{ t('album.add_title') }}</div>
            <div class="title ellipsis">{{ artist(track) }} — {{ track.title }}</div>
          </div>
        </div>

        <button class="row new" :disabled="full" @click="createNew">
          <span class="new-icon"><Icon name="plus" :size="22" /></span>
          <span class="row-text">
            <b>{{ t('album.new') }}</b>
            <small>{{ full ? albums.blockText : t('album.slots', { used: list?.length ?? 0, max: albums.limit }) }}</small>
          </span>
        </button>

        <div v-if="list == null" class="loading"><span class="spinner" /></div>
        <button v-for="a in list || []" :key="a.id" class="row" :class="{ on: a.has_track }" @click="toggle(a)">
          <AlbumArt :album="a" radius="10px" class="row-art" />
          <span class="row-text">
            <b class="ellipsis">{{ a.name }}</b>
            <small>{{ tp(a.track_count, 'units.tracks') }}</small>
          </span>
          <span class="check" :class="{ on: a.has_track }"><Icon v-if="a.has_track" name="check" :size="16" /></span>
        </button>

        <button class="btn done" @click="ui.closePicker()">{{ t('common.done') }}</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 85;
  background: rgba(0, 0, 0, 0.55);
  -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px);
  display: flex; align-items: flex-end; justify-content: center;
}
.sheet {
  width: 100%; max-width: 560px; max-height: 85vh; overflow-y: auto;
  padding: 8px 14px calc(var(--safe-bottom) + 14px);
  border-radius: 24px 24px 0 0;
  border: 1px solid var(--border); border-bottom: 0;
  background: rgba(22, 22, 28, 0.9);
}
.grab { width: 38px; height: 5px; border-radius: 3px; background: var(--surface-3); margin: 0 auto 12px; }
.head { display: flex; align-items: center; gap: 12px; padding: 0 4px 14px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }
.head-cover { width: 44px; }
.meta { min-width: 0; }
.label { font-size: 12.5px; color: var(--text-2); }
.title { font-weight: 600; font-size: 15px; }
.row {
  display: flex; align-items: center; gap: 12px; width: 100%;
  padding: 8px 6px; border-radius: 14px; text-align: left;
  transition: background 0.15s;
}
.row:active { background: var(--surface-2); }
.row:disabled { opacity: 0.55; }
.row-art { width: 48px; flex-shrink: 0; }
.new-icon {
  width: 48px; height: 48px; border-radius: 12px; display: grid; place-items: center; flex-shrink: 0;
  border: 1.5px dashed rgba(255, 255, 255, 0.25); color: var(--accent);
}
.row-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.row-text b { font-weight: 600; font-size: 15.5px; }
.row-text small { font-size: 12.5px; color: var(--text-2); }
.check {
  width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  border: 2px solid rgba(255, 255, 255, 0.22); color: #fff;
  transition: background 0.2s, border-color 0.2s, transform 0.25s var(--ease-spring);
}
.check.on { background: var(--accent); border-color: var(--accent); transform: scale(1.05); }
.loading { display: grid; place-items: center; padding: 20px; }
.spinner { width: 22px; height: 22px; border-radius: 50%; border: 2.5px solid rgba(255,255,255,.2); border-top-color: #fff; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.done { width: 100%; margin-top: 10px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.3s var(--ease); }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.4s var(--ease); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(100%); }
</style>
