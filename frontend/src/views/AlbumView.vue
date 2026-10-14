<script setup>
// Альбом: свой (/album/:id) или открытый по ссылке (/shared/:code).
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { canGoBack, goBack } from '../router'
import { api } from '../lib/api'
import { duration } from '../lib/format'
import { errorText, t, tp } from '../lib/i18n'
import { confirmDialog, haptic } from '../lib/telegram'
import { shareAlbum } from '../lib/share'
import { useAlbums } from '../stores/albums'
import { usePlayer } from '../stores/player'
import { useUi } from '../stores/ui'
import { useSession } from '../stores/session'
import AlbumArt from '../components/AlbumArt.vue'
import Icon from '../components/Icon.vue'
import TrackList from '../components/TrackList.vue'
import SkeletonRows from '../components/SkeletonRows.vue'

const route = useRoute()
const router = useRouter()
const albums = useAlbums()
const player = usePlayer()
const ui = useUi()
const session = useSession()
const toggling = ref(false)

const album = ref(null)
const tracks = ref(null)
const own = ref(false)
const error = ref('')
const saving = ref(false)

const bg = computed(() => album.value?.covers?.[0] || null)
const total = computed(() => (tracks.value || []).reduce((a, tr) => a + (tr.duration || 0), 0))
const context = computed(() => (own.value && album.value ? {
  albumId: album.value.id,
  onRemoved: (tr) => { tracks.value = tracks.value.filter((x) => x.id !== tr.id) },
} : null))

async function load() {
  error.value = ''
  try {
    const res = route.name === 'shared-album'
      ? await api.albums.shared(route.params.code)
      : await api.albums.get(route.params.id)
    album.value = res.album
    tracks.value = res.tracks
    own.value = res.own
  } catch (e) {
    error.value = e.status === 404 ? t('errors.album_not_found') : errorText(e)
  }
}

function play(shuffle) {
  if (!tracks.value?.length) return
  haptic.tap()
  player.playAll(tracks.value, shuffle)
}
async function share() {
  haptic.tap()
  const wasPublic = album.value.public
  try {
    await shareAlbum(album.value)
    album.value = { ...album.value, shared: true, public: true }
    if (!wasPublic) { ui.toast(t('album.opened')); albums.bump() }
  } catch (e) { ui.toast(errorText(e)) }
}
async function toggleAccess() {
  const next = !album.value.public
  if (!own.value && !(await confirmDialog(t('album.moderate_confirm')))) return
  toggling.value = true
  haptic.medium()
  try {
    const a = await api.albums.visibility(album.value.id, next)
    album.value = { ...album.value, ...a }
    albums.bump()
    ui.toast(next ? t('album.opened') : t('album.closed'))
    if (!own.value && !next) { if (canGoBack()) goBack(); else router.replace('/') }
  } catch (e) { ui.toast(errorText(e)) } finally { toggling.value = false }
}
function edit() {
  ui.openEditor({ mode: 'edit', album: album.value, onSaved: (a) => { album.value = { ...album.value, ...a } } })
}
async function remove() {
  if (!(await confirmDialog(t('album.delete_confirm', { name: album.value.name })))) return
  try {
    await albums.remove(album.value.id)
    haptic.success()
    ui.toast(t('album.deleted'))
    if (canGoBack()) goBack()
    else router.replace('/library')
  } catch (e) { ui.toast(errorText(e)) }
}
async function saveCopy() {
  saving.value = true
  try {
    const a = await api.albums.saveShared(route.params.code)
    albums.bump()
    haptic.success()
    ui.toast(t('album.saved_copy', { name: a.name }))
    router.replace({ name: 'album', params: { id: a.id } })
  } catch (e) {
    haptic.error()
    ui.toast(errorText(e, { n: albums.limit }))
  } finally { saving.value = false }
}

watch(() => [route.params.id, route.params.code], () => {
  if (route.name === 'album' || route.name === 'shared-album') { album.value = null; tracks.value = null; load() }
}, { immediate: true })
</script>

<template>
  <div class="page album-page">
    <div class="hero-bg" aria-hidden="true">
      <img v-if="bg" :src="bg" alt="" />
    </div>

    <div v-if="error" class="empty">
      <div class="empty-icon"><Icon name="album" /></div>
      <p>{{ error }}</p>
    </div>

    <template v-else>
      <header class="head">
        <AlbumArt v-if="album" :album="album" radius="24px" class="art" />
        <div v-else class="skeleton art" />
        <h1 class="name">{{ album?.name || ' ' }}</h1>
        <p class="meta muted">
          <template v-if="tracks">{{ tp(tracks.length, 'units.tracks') }}<template v-if="total"> · {{ duration(total) }}</template></template>
        </p>
        <p v-if="album && !own && album.owner_name" class="owner faint">
          {{ t('album.by', { name: album.owner_name }) }}<span v-if="album.owner_vip" class="vip-star" :title="t('premium.badge')">⭐</span>
        </p>
        <!-- просмотры видны только у открытого альбома -->
        <Transition name="fade">
          <span v-if="album?.public && album.views != null" class="views" :title="t('album.views_hint')">
            <Icon name="eye" :size="15" />{{ tp(album.views, 'units.views') }}
          </span>
        </Transition>
      </header>

      <div class="actions">
        <button class="btn btn-primary" :disabled="!tracks?.length" @click="play(false)"><Icon name="play" :size="18" />{{ t('common.listen') }}</button>
        <button class="btn" :disabled="!tracks?.length" @click="play(true)"><Icon name="shuffle" :size="18" />{{ t('common.shuffle') }}</button>
      </div>
      <div v-if="album" class="tools">
        <template v-if="own">
          <button class="access" :class="{ open: album.public }" :disabled="toggling" @click="toggleAccess">
            <Icon :name="album.public ? 'lock' : 'unlock'" :size="18" />
            {{ album.public ? t('album.close_access') : t('album.open_access') }}
          </button>
          <div class="tool-row">
            <button class="tool" @click="share"><Icon name="send" :size="18" />{{ t('actions.share') }}</button>
            <button class="tool" @click="edit"><Icon name="edit" :size="18" />{{ t('common.edit') }}</button>
            <button class="tool danger" @click="remove"><Icon name="trash" :size="18" />{{ t('common.delete') }}</button>
          </div>
          <p class="access-hint faint">{{ album.public ? t('album.public_hint') : t('album.private_hint') }}</p>
        </template>
        <template v-else>
          <button class="tool wide" :disabled="saving" @click="saveCopy"><Icon name="album-plus" :size="18" />{{ t('album.save_copy') }}</button>
          <button v-if="session.isAdmin && album.public" class="tool wide danger" :disabled="toggling" @click="toggleAccess">
            <Icon name="lock" :size="18" />{{ t('album.moderate_close') }}
          </button>
        </template>
      </div>

      <SkeletonRows v-if="tracks == null" :count="5" />
      <TrackList v-else-if="tracks.length" :tracks="tracks" :context="context" />
      <div v-else class="empty">
        <div class="empty-icon"><Icon name="music" /></div>
        <p>{{ own ? t('album.empty_own') : t('album.empty') }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.hero-bg { position: absolute; inset: 0 0 auto 0; height: 380px; z-index: -1; overflow: hidden; pointer-events: none; }
.hero-bg img { width: 100%; height: 100%; object-fit: cover; filter: blur(50px) saturate(1.5); opacity: 0.35; transform: scale(1.3); }
.hero-bg::after { content: ''; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(9, 9, 11, 0.2), var(--bg)); }
.head { display: flex; flex-direction: column; align-items: center; text-align: center; padding-top: 18px; }
.art { width: min(56vw, 210px); aspect-ratio: 1; box-shadow: 0 24px 50px -20px rgba(0, 0, 0, 0.85); }
.name { font-size: 25px; font-weight: 800; letter-spacing: -0.02em; margin-top: 18px; word-break: break-word; }
.meta { font-size: 14px; margin-top: 4px; min-height: 20px; }
.owner { font-size: 13px; margin-top: 2px; }
.vip-star { margin-left: 4px; font-size: 11px; }
.views {
  display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; padding: 5px 11px;
  border-radius: 999px; font-size: 12.5px; font-weight: 600; color: var(--text-2);
  background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border);
}
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 18px; }
.tools { display: grid; gap: 8px; margin: 10px 0 14px; }
.tool-row { display: flex; gap: 8px; }
.access {
  display: flex; align-items: center; justify-content: center; gap: 8px; height: 44px; border-radius: 14px;
  font-size: 14.5px; font-weight: 700; color: #fff;
  background: rgba(61, 220, 151, 0.16); border: 1px solid rgba(61, 220, 151, 0.4);
  transition: transform 0.15s var(--ease), background 0.25s, border-color 0.25s;
}
.access.open { background: var(--surface); border-color: var(--border); color: var(--text-2); }
.access:active { transform: scale(0.97); }
.access:disabled { opacity: 0.6; }
.access-hint { font-size: 12.5px; text-align: center; }
.tool {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 38px; border-radius: 12px; font-size: 13.5px; font-weight: 600; color: var(--text-2);
  background: var(--surface); border: 1px solid var(--border);
  transition: transform 0.15s var(--ease);
}
.tool:active { transform: scale(0.96); }
.tool.danger { color: var(--danger); }
.tool:disabled { opacity: 0.5; }
</style>
