<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { usePlayer } from '../stores/player'
import { useLibrary } from '../stores/library'
import { useUi } from '../stores/ui'
import { artist, duration } from '../lib/format'
import { haptic } from '../lib/telegram'
import { t, tp } from '../lib/i18n'
import Cover from './Cover.vue'
import Icon from './Icon.vue'
import SeekBar from './SeekBar.vue'
import SeasonDecor from './SeasonDecor.vue'

const player = usePlayer()
const lib = useLibrary()
const ui = useUi()

const track = computed(() => player.current)
const preview = ref(null)
const sleepMenu = ref(false)

const dur = computed(() => player.duration || track.value?.duration || 0)
const shownTime = computed(() => (preview.value != null ? preview.value * dur.value : player.currentTime))
const tint = computed(() => track.value?.color || '#8b7bff')
const bufferedFrac = computed(() => (dur.value ? Math.min(1, player.buffered / dur.value) : 0))

// Таймер сна: Date.now() не реактивен, поэтому «тикаем» раз в 15 секунд, пока таймер включён
const now = ref(Date.now())
let clock = 0
watch(() => player.sleepAt, (v) => {
  clearInterval(clock)
  now.value = Date.now()
  if (v > 0) clock = setInterval(() => { now.value = Date.now() }, 15000)
}, { immediate: true })
const sleepLabel = computed(() => {
  if (player.sleepAt === -1) return t('player.sleep_end_short')
  if (player.sleepAt > 0) return tp(Math.max(1, Math.round((player.sleepAt - now.value) / 60000)), 'units.min_short')
  return ''
})

function close() {
  player.sheetOpen = false
  player.queueOpen = false
  sleepMenu.value = false
}
function seekTo(frac) { player.seek(frac * dur.value); haptic.select() }
function act(fn) { haptic.tap(); fn() }
function setSleep(m) {
  player.setSleep(m)
  sleepMenu.value = false
  ui.toast(m === 0 ? t('player.sleep_off_toast') : m === -1 ? t('player.sleep_end_toast') : t('player.sleep_toast', { v: tp(m, 'units.minutes') }))
}

// ---------------------------------------------------------------- свайп вниз
// Палец двигает лист напрямую через style.transform в requestAnimationFrame — без реактивного
// состояния и перерисовки шаблона. Анимации открытия/закрытия — Web Animations API, поэтому
// закрытие продолжается ровно с того места, где отпустили палец, со скоростью жеста.
const EASE = 'cubic-bezier(0.22, 0.9, 0.24, 1)'
const DEAD_ZONE = 8
const sheet = ref(null)
let mode = 'idle' // idle | pending | drag
let startX = 0
let startY = 0
let offset = 0
let raf = 0
let samples = [] // [время, y] за последние ~100 мс — для скорости в момент отпускания
let releaseFrom = 0 // позиция, с которой начнётся анимация закрытия
let releaseVelocity = 0

function paint() {
  raf = 0
  if (sheet.value) sheet.value.style.transform = `translate3d(0, ${offset}px, 0)`
}
function onTouchStart(e) {
  if (e.touches.length !== 1 || player.queueOpen || e.target.closest('.seek, .vol, .no-drag')) return
  mode = 'pending'
  startX = e.touches[0].clientX
  startY = e.touches[0].clientY
  offset = 0
  samples = [[performance.now(), 0]]
}
function onTouchMove(e) {
  if (mode === 'idle') return
  const dx = e.touches[0].clientX - startX
  const dy = e.touches[0].clientY - startY
  if (mode === 'pending') {
    if (Math.abs(dx) > DEAD_ZONE && Math.abs(dx) > Math.abs(dy)) { mode = 'idle'; return } // горизонтальный жест
    if (dy < DEAD_ZONE) return
    mode = 'drag'
    startY += DEAD_ZONE // без «рывка» на величину мёртвой зоны
    sheet.value?.getAnimations().forEach((a) => a.cancel())
    sheet.value?.classList.add('dragging')
  }
  e.preventDefault() // страница и Telegram не перехватывают жест
  offset = Math.max(0, e.touches[0].clientY - startY)
  const ts = performance.now()
  samples.push([ts, offset])
  while (samples.length > 2 && ts - samples[0][0] > 100) samples.shift()
  if (!raf) raf = requestAnimationFrame(paint)
}
function velocity() {
  const [t0, y0] = samples[0]
  const [t1, y1] = samples[samples.length - 1]
  return t1 > t0 ? (y1 - y0) / (t1 - t0) : 0 // px/мс
}
function onTouchEnd() {
  const wasDragging = mode === 'drag'
  mode = 'idle'
  if (!wasDragging) return
  cancelAnimationFrame(raf)
  raf = 0
  sheet.value?.classList.remove('dragging')
  const v = velocity()
  const h = sheet.value?.offsetHeight || window.innerHeight
  if (offset > h * 0.22 || (offset > 30 && v > 0.45)) {
    releaseFrom = offset
    releaseVelocity = Math.max(0, v)
    haptic.select()
    close()
  } else {
    snapBack()
  }
}
function snapBack() {
  const el = sheet.value
  if (!el) return
  const from = offset
  offset = 0
  el.style.transform = ''
  if (from > 0) {
    el.animate([{ transform: `translate3d(0, ${from}px, 0)` }, { transform: 'translate3d(0, 0, 0)' }],
      { duration: 360, easing: 'cubic-bezier(0.18, 1.25, 0.4, 1)' })
  }
}

// Анимации появления и закрытия (Transition :css="false")
function onEnter(el, done) {
  el.animate([{ transform: 'translate3d(0, 100%, 0)' }, { transform: 'translate3d(0, 0, 0)' }],
    { duration: 440, easing: EASE }).onfinish = done
}
function onLeave(el, done) {
  const h = el.offsetHeight || window.innerHeight
  const from = releaseFrom
  // чем быстрее смахнули — тем быстрее уезжает, но в разумных пределах
  const ms = from ? Math.min(340, Math.max(170, (h - from) / Math.max(releaseVelocity, 1.6))) : 380
  releaseFrom = 0
  releaseVelocity = 0
  el.style.transform = ''
  el.animate([{ transform: `translate3d(0, ${from}px, 0)` }, { transform: 'translate3d(0, 100%, 0)' }],
    { duration: ms, easing: from ? 'cubic-bezier(0.3, 0.6, 0.4, 1)' : 'cubic-bezier(0.4, 0, 0.7, 0.2)', fill: 'forwards' })
    .onfinish = done
}

// touchmove должен быть НЕ пассивным, чтобы preventDefault останавливал прокрутку под плеером
watch(sheet, (el, old) => {
  old?.removeEventListener('touchmove', onTouchMove)
  el?.addEventListener('touchmove', onTouchMove, { passive: false })
})

// Пока плеер открыт, страница под ним не прокручивается; блокировка гарантированно снимается
watch(() => player.sheetOpen, (open) => { document.documentElement.classList.toggle('scroll-locked', open) })
onBeforeUnmount(() => {
  clearInterval(clock)
  cancelAnimationFrame(raf)
  document.documentElement.classList.remove('scroll-locked')
})
</script>

<template>
  <Transition :css="false" @enter="onEnter" @leave="onLeave">
    <section
      v-if="player.sheetOpen && track"
      ref="sheet"
      class="player"
      :style="{ '--tint': tint }"
      :aria-label="t('player.title')"
      @touchstart.passive="onTouchStart"
      @touchend.passive="onTouchEnd"
      @touchcancel.passive="onTouchEnd"
    >
      <!-- размытый фон из обложки -->
      <div class="bg" aria-hidden="true">
        <Transition name="fade">
          <img v-if="track.cover" :key="track.id" :src="track.cover.s" alt="" class="bg-img" />
        </Transition>
        <div class="bg-tint" />
      </div>
      <SeasonDecor variant="player" />

      <header class="top">
        <button class="icon-btn" :aria-label="t('player.collapse')" @click="close"><Icon name="chevron-down" :size="28" /></button>
        <div class="top-title">
          <span class="faint">{{ t('player.now_playing') }}</span>
          <span v-if="player.queue.length > 1" class="tnum">{{ t('player.position', { i: player.index + 1, n: player.queue.length }) }}</span>
        </div>
        <button class="icon-btn" :aria-label="t('actions.more')" @click="ui.openActions(track)"><Icon name="more" :size="24" /></button>
      </header>

      <div class="art-wrap">
        <Transition name="art" mode="out-in">
          <Cover :key="track.id" :track="track" size="l" radius="22px" eager class="art" :class="{ paused: !player.playing }" />
        </Transition>
      </div>

      <div class="info">
        <div class="info-text">
          <h2 class="title ellipsis">{{ track.title }}</h2>
          <p class="artist ellipsis">{{ artist(track) }}</p>
        </div>
        <button class="icon-btn like" :class="{ on: lib.isLiked(track) }" :aria-label="t(lib.isLiked(track) ? 'actions.unlike' : 'actions.like')" @click="lib.toggleLike(track)">
          <Icon :name="lib.isLiked(track) ? 'heart-fill' : 'heart'" :size="26" />
        </button>
      </div>

      <div class="progress">
        <SeekBar :label="t('player.position_label')" :value="dur ? player.currentTime / dur : 0" :buffered="bufferedFrac" @seek="seekTo" @preview="preview = $event" />
        <div class="times tnum">
          <span>{{ duration(shownTime) }}</span>
          <span v-if="player.error" class="err">{{ t('player.errors.' + player.error) }}</span>
          <span>-{{ duration(Math.max(0, dur - shownTime)) }}</span>
        </div>
      </div>

      <div class="controls">
        <button class="icon-btn small" :class="{ on: player.shuffle }" :aria-label="t('player.shuffle')" @click="act(player.toggleShuffle)">
          <Icon name="shuffle" :size="22" />
        </button>
        <button class="icon-btn big" :aria-label="t('player.prev')" @click="act(player.prev)"><Icon name="prev" :size="34" /></button>
        <button class="play" :aria-label="player.playing ? t('player.pause') : t('player.play')" @click="act(player.toggle)">
          <span v-if="player.loading && player.playing" class="spinner" />
          <Icon v-else :name="player.playing ? 'pause' : 'play'" :size="34" />
        </button>
        <button class="icon-btn big" :aria-label="t('player.next')" @click="act(() => player.next())"><Icon name="next" :size="34" /></button>
        <button class="icon-btn small" :class="{ on: player.repeat !== 'off' }" :aria-label="t('player.repeat')" @click="act(player.cycleRepeat)">
          <Icon name="repeat" :size="22" />
          <span v-if="player.repeat === 'one'" class="one">1</span>
        </button>
      </div>

      <div v-if="player.canSetVolume" class="vol no-drag">
        <button class="icon-btn small" :aria-label="t('player.volume')" @click="player.setVolume(player.volume > 0 ? 0 : 1)">
          <Icon :name="player.volume > 0 ? 'volume' : 'volume-off'" :size="20" />
        </button>
        <SeekBar :value="player.volume" :label="t('player.volume')" class="vol-bar" @seek="player.setVolume" @preview="(v) => v != null && player.setVolume(v, false)" />
      </div>

      <footer class="bottom">
        <button class="pill" :class="{ on: player.sleepAt !== 0 }" @click="sleepMenu = !sleepMenu">
          <Icon name="moon" :size="18" />{{ sleepLabel || t('player.timer') }}
        </button>
        <button class="pill" @click="ui.openPicker(track)">
          <Icon name="album" :size="18" />{{ t('player.to_album') }}
        </button>
        <button class="pill" :class="{ on: player.queueOpen }" @click="player.queueOpen = true">
          <Icon name="queue" :size="18" />{{ t('player.queue') }}
        </button>
      </footer>

      <Transition name="pop">
        <div v-if="sleepMenu" class="menu glass no-drag">
          <button v-for="m in [15, 30, 45, 60]" :key="m" @click="setSleep(m)">{{ tp(m, 'units.minutes') }}</button>
          <button @click="setSleep(-1)">{{ t('player.sleep_end') }}</button>
          <button v-if="player.sleepAt !== 0" class="danger" @click="setSleep(0)">{{ t('player.sleep_off') }}</button>
        </div>
      </Transition>

      <!-- очередь -->
      <Transition name="queue">
        <div v-if="player.queueOpen" class="queue glass no-drag">
          <div class="queue-head">
            <h3>{{ t('player.up_next') }}</h3>
            <button class="icon-btn" :aria-label="t('common.close')" @click="player.queueOpen = false"><Icon name="close" :size="22" /></button>
          </div>
          <div class="queue-list">
            <div v-if="!player.upNext.length" class="empty">{{ t('player.queue_empty') }}</div>
            <div v-for="(q, i) in player.upNext" :key="q.id + '-' + i" class="q-row" @click="player.playIndex(player.index + 1 + i)">
              <Cover :track="q" radius="8px" class="q-cover" />
              <div class="q-meta">
                <div class="ellipsis q-title">{{ q.title }}</div>
                <div class="ellipsis q-sub">{{ artist(q) }}</div>
              </div>
              <button class="icon-btn" :aria-label="t('common.remove')" @click.stop="player.removeFromQueue(player.index + 1 + i)">
                <Icon name="close" :size="18" />
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </section>
  </Transition>
</template>

<style scoped>
.player {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  padding: calc(var(--safe-top) + 6px) 24px calc(var(--safe-bottom) + 18px);
  background: var(--bg);
  overflow: hidden;
  overscroll-behavior: none;
}
/* во время жеста: слой на GPU, декор на паузе — меньше перерисовок */
.player.dragging { will-change: transform; }
.player.dragging :deep(.decor .it) { animation-play-state: paused; }

.bg { position: absolute; inset: 0; z-index: -1; overflow: hidden; }
.bg-img {
  position: absolute;
  inset: -20%;
  width: 140%;
  height: 140%;
  object-fit: cover;
  filter: blur(60px) saturate(1.6);
  opacity: 0.55;
  transform: translateZ(0);
}
.bg-tint {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(120% 70% at 50% 0%, var(--tint) 0%, transparent 65%),
    linear-gradient(180deg, rgba(9, 9, 11, 0.15) 0%, rgba(9, 9, 11, 0.7) 60%, var(--bg) 100%);
  opacity: 0.9;
  mix-blend-mode: normal;
}

.top { display: flex; align-items: center; justify-content: space-between; height: 48px; }
.top-title { display: flex; flex-direction: column; align-items: center; font-size: 12.5px; font-weight: 600; line-height: 1.3; }

.art-wrap { flex: 1; display: grid; place-items: center; min-height: 0; padding: 16px 0; }
.art {
  width: min(100%, 360px, 42vh);
  box-shadow: 0 30px 60px -20px rgba(0, 0, 0, 0.8);
  transition: transform 0.5s var(--ease-spring), box-shadow 0.5s;
}
.art.paused { transform: scale(0.86); box-shadow: 0 16px 40px -20px rgba(0, 0, 0, 0.7); }

.info { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
.info-text { flex: 1; min-width: 0; }
.title { font-size: 23px; font-weight: 700; letter-spacing: -0.02em; }
.artist { font-size: 17px; color: var(--text-2); margin-top: 2px; }
.like { color: var(--text-2); }
.like.on { color: var(--accent-2); animation: pop 0.35s var(--ease-spring); }
@keyframes pop { 50% { transform: scale(1.3); } }

.progress { margin-top: 12px; }
.times { display: flex; justify-content: space-between; font-size: 12.5px; color: var(--text-3); margin-top: -4px; }
.err { color: var(--danger); }

.controls { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 6px; }
.icon-btn.small { color: var(--text-3); position: relative; }
.icon-btn.small.on { color: var(--accent); }
.icon-btn.small.on::after {
  content: ''; position: absolute; bottom: 2px; left: 50%; width: 4px; height: 4px; margin-left: -2px;
  border-radius: 50%; background: currentColor;
}
.one { position: absolute; top: 7px; right: 6px; font-size: 9px; font-weight: 800; }
.icon-btn.big { width: 60px; height: 60px; }
.play {
  width: 74px;
  height: 74px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #fff;
  color: #0b0b0f;
  box-shadow: 0 12px 30px -8px rgba(255, 255, 255, 0.25);
  transition: transform 0.2s var(--ease-spring);
}
.play:active { transform: scale(0.9); }
.spinner {
  width: 28px; height: 28px; border-radius: 50%;
  border: 3px solid rgba(0, 0, 0, 0.15); border-top-color: #0b0b0f;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.vol { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.vol-bar { flex: 1; }

.bottom { display: flex; justify-content: space-between; gap: 8px; margin-top: 10px; }
.pill {
  flex: 1 1 0; min-width: 0; justify-content: center; white-space: nowrap; overflow: hidden;
  display: inline-flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 10px; border-radius: 999px;
  font-size: 13.5px; font-weight: 600; color: var(--text-2);
  background: rgba(255, 255, 255, 0.07);
}
.pill.on { color: var(--text); background: rgba(255, 255, 255, 0.14); }

.menu {
  position: absolute;
  left: 24px;
  bottom: calc(var(--safe-bottom) + 64px);
  display: flex; flex-direction: column;
  min-width: 190px; padding: 6px;
  border-radius: 16px;
  border: 1px solid var(--border);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
  transform-origin: bottom left;
}
.menu button { text-align: left; padding: 11px 12px; border-radius: 10px; font-size: 15px; }
.menu button:active { background: var(--surface-2); }
.menu .danger { color: var(--danger); }

.queue {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 72%;
  display: flex; flex-direction: column;
  border-radius: 24px 24px 0 0;
  border-top: 1px solid var(--border);
  background: rgba(16, 16, 20, 0.86);
  padding: 8px 16px calc(var(--safe-bottom) + 8px);
}
.queue-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 0 8px; }
.queue-head h3 { font-size: 18px; font-weight: 700; }
.queue-list { overflow-y: auto; flex: 1; overscroll-behavior: contain; }
.q-row { display: flex; align-items: center; gap: 12px; padding: 6px 0; cursor: pointer; }
.q-cover { width: 42px; }
.q-meta { flex: 1; min-width: 0; }
.q-title { font-size: 15px; font-weight: 600; }
.q-sub { font-size: 13px; color: var(--text-2); }
.queue .empty { padding: 32px; }

.art-enter-active, .art-leave-active { transition: opacity 0.25s, transform 0.3s var(--ease); }
.art-enter-from { opacity: 0; transform: scale(0.94); }
.art-leave-to { opacity: 0; transform: scale(0.94); }
.queue-enter-active, .queue-leave-active { transition: transform 0.4s var(--ease); }
.queue-enter-from, .queue-leave-to { transform: translateY(100%); }
.pop-enter-active, .pop-leave-active { transition: opacity 0.2s, transform 0.25s var(--ease-spring); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.9); }

@media (min-height: 760px) {
  .title { font-size: 26px; }
}
</style>
