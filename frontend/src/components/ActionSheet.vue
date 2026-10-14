<script setup>
import { computed } from 'vue'
import { useUi } from '../stores/ui'
import { usePlayer } from '../stores/player'
import { useLibrary } from '../stores/library'
import { useAlbums } from '../stores/albums'
import { artist } from '../lib/format'
import { errorText, t } from '../lib/i18n'
import { haptic, openTelegramLink } from '../lib/telegram'
import { shareTrack } from '../lib/share'
import Cover from './Cover.vue'
import Icon from './Icon.vue'

const ui = useUi()
const player = usePlayer()
const lib = useLibrary()
const albums = useAlbums()
const track = computed(() => ui.actionTrack)
const ctx = computed(() => ui.actionContext)

function run(fn, msg) {
  haptic.tap()
  fn()
  if (msg) ui.toast(msg)
  ui.closeActions()
}
function toAlbum() {
  const tr = track.value
  ui.closeActions()
  ui.openPicker(tr)
}
async function removeFromAlbum() {
  const tr = track.value
  const c = ctx.value
  ui.closeActions()
  try {
    await albums.removeTrack(c.albumId, tr.id)
    c.onRemoved?.(tr)
    ui.toast(t('album.removed'))
  } catch (e) { ui.toast(errorText(e)) }
}
</script>

<template>
  <Transition name="sheet">
    <div v-if="track" class="backdrop" @click.self="ui.closeActions()">
      <div class="sheet glass" role="dialog" aria-modal="true">
        <div class="grab" />
        <div class="head">
          <Cover :track="track" radius="10px" class="head-cover" />
          <div class="meta">
            <div class="title ellipsis">{{ track.title }}</div>
            <div class="sub ellipsis">{{ artist(track) }}</div>
          </div>
        </div>
        <button class="item" @click="run(() => player.playNext(track), t('actions.play_next_done'))"><Icon name="play-next" />{{ t('actions.play_next') }}</button>
        <button class="item" @click="run(() => player.addToQueue(track), t('actions.queue_done'))"><Icon name="queue" />{{ t('actions.add_queue') }}</button>
        <button class="item" @click="run(() => lib.toggleLike(track))">
          <Icon :name="lib.isLiked(track) ? 'heart-fill' : 'heart'" />{{ lib.isLiked(track) ? t('actions.unlike') : t('actions.like') }}
        </button>
        <button class="item" @click="toAlbum"><Icon name="album-plus" />{{ t('actions.to_album') }}</button>
        <button v-if="ctx?.albumId" class="item danger" @click="removeFromAlbum"><Icon name="trash" />{{ t('actions.remove_from_album') }}</button>
        <button class="item" @click="run(() => shareTrack(track))"><Icon name="send" />{{ t('actions.share') }}</button>
        <button v-if="track.post_url" class="item" @click="run(() => openTelegramLink(track.post_url))"><Icon name="external" />{{ t('actions.open_post') }}</button>
        <button class="item cancel" @click="ui.closeActions()">{{ t('common.cancel') }}</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(0, 0, 0, 0.5);
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.sheet {
  width: 100%;
  max-width: 560px;
  padding: 8px 12px calc(var(--safe-bottom) + 12px);
  border-radius: 24px 24px 0 0;
  border: 1px solid var(--border);
  border-bottom: 0;
  background: rgba(22, 22, 28, 0.86);
  max-height: 90vh;
  overflow-y: auto;
}
.grab { width: 38px; height: 5px; border-radius: 3px; background: var(--surface-3); margin: 0 auto 12px; }
.head { display: flex; align-items: center; gap: 12px; padding: 4px 8px 14px; border-bottom: 1px solid var(--border); margin-bottom: 6px; }
.head-cover { width: 48px; }
.meta { min-width: 0; }
.title { font-weight: 600; }
.sub { font-size: 13.5px; color: var(--text-2); }
.item {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 13px 10px;
  border-radius: 12px;
  font-size: 16px;
  text-align: left;
  transition: background 0.15s;
}
.item:active { background: var(--surface-2); }
.item .icon { color: var(--text-2); }
.item.danger, .item.danger .icon { color: var(--danger); }
.cancel { justify-content: center; color: var(--text-2); margin-top: 4px; background: var(--surface); }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.3s var(--ease); }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.4s var(--ease); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(100%); }
</style>
