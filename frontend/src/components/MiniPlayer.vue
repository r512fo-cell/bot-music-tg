<script setup>
import { usePlayer } from '../stores/player'
import { useLibrary } from '../stores/library'
import { artist } from '../lib/format'
import { t } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import Cover from './Cover.vue'
import Icon from './Icon.vue'

const player = usePlayer()
const lib = useLibrary()
let startX = 0
let startY = 0

function open() { haptic.tap(); player.sheetOpen = true }
function touchStart(e) { startX = e.touches[0].clientX; startY = e.touches[0].clientY }
function touchEnd(e) {
  const dx = e.changedTouches[0].clientX - startX
  const dy = startY - e.changedTouches[0].clientY
  if (dy > 30 && Math.abs(dy) > Math.abs(dx)) open()
  else if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
    haptic.tap()
    dx < 0 ? player.next() : player.prev()
  }
}
const act = (fn) => { haptic.tap(); fn() }
</script>

<template>
  <Transition name="mini">
    <div
      v-if="player.current"
      class="mini glass"
      :style="{ '--tint': (player.current.color || '#8b7bff') + '4d' }"
      @click="open"
      @touchstart.passive="touchStart"
      @touchend.passive="touchEnd"
    >
      <Cover :track="player.current" radius="10px" class="mini-cover" />
      <div class="meta">
        <div class="title ellipsis">{{ player.current.title }}</div>
        <div class="sub ellipsis" :class="{ err: player.error }">{{ player.error ? t('player.errors.' + player.error) : artist(player.current) }}</div>
      </div>
      <button
        class="icon-btn like"
        :class="{ on: lib.isLiked(player.current) }"
        :aria-label="lib.isLiked(player.current) ? t('actions.unlike') : t('actions.like')"
        @click.stop="lib.toggleLike(player.current)"
      >
        <Icon :name="lib.isLiked(player.current) ? 'heart-fill' : 'heart'" :size="21" />
      </button>
      <button class="icon-btn ctl" :aria-label="t('player.prev')" @click.stop="act(player.prev)">
        <Icon name="prev" :size="21" />
      </button>
      <button class="icon-btn ctl" :aria-label="player.playing ? t('player.pause') : t('player.play')" @click.stop="act(player.toggle)">
        <span v-if="player.loading && player.playing" class="spinner" />
        <Icon v-else :name="player.playing ? 'pause' : 'play'" :size="25" />
      </button>
      <button class="icon-btn ctl" :aria-label="t('player.next')" :disabled="!player.hasNext" @click.stop="act(() => player.next())">
        <Icon name="next" :size="21" />
      </button>
      <div class="bar"><div class="bar-fill" :style="{ transform: `scaleX(${player.progress})` }" /></div>
    </div>
  </Transition>
</template>

<style scoped>
.mini {
  position: fixed;
  z-index: 40;
  left: 8px;
  right: 8px;
  bottom: calc(var(--tabbar-h) + var(--safe-bottom) + 6px);
  height: 58px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 4px 0 7px;
  border-radius: 16px;
  overflow: hidden;
  background:
    linear-gradient(90deg, var(--tint), transparent 70%),
    var(--glass-strong);
  border: 1px solid var(--border);
  box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.7);
  cursor: pointer;
  max-width: 720px;
  margin: 0 auto;
}
.mini-cover { width: 44px; margin-right: 6px; }
.meta { flex: 1; min-width: 0; }
.title { font-size: 14.5px; font-weight: 600; }
.sub { font-size: 12.5px; color: var(--text-2); }
.sub.err { color: var(--danger); }
.icon-btn.ctl, .icon-btn.like { width: 36px; height: 36px; }
.like { color: var(--text-2); }
.like.on { color: var(--accent-2); animation: pop 0.35s var(--ease-spring); }
@keyframes pop { 50% { transform: scale(1.25); } }
.icon-btn:disabled { opacity: 0.35; }
.bar { position: absolute; left: 12px; right: 12px; bottom: 0; height: 2px; background: rgba(255, 255, 255, 0.1); border-radius: 2px; }
.bar-fill { height: 100%; background: #fff; transform-origin: left; border-radius: 2px; transition: transform 0.25s linear; }
.spinner {
  width: 20px; height: 20px; border-radius: 50%;
  border: 2.5px solid rgba(255, 255, 255, 0.25); border-top-color: #fff;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.mini-enter-active, .mini-leave-active { transition: transform 0.4s var(--ease), opacity 0.3s; }
.mini-enter-from, .mini-leave-to { transform: translateY(24px); opacity: 0; }
@media (max-width: 340px) { .like { display: none; } }
</style>
