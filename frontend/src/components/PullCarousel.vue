<script setup>
// Горизонтальная карусель со «скрытой» стрелкой в конце.
// Стрелка плавно проявляется по мере прокрутки к концу; если дотянуть дальше и отпустить —
// открывается полный список. Анимация только через transform/opacity, обработчик — раз в кадр.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { haptic } from '../lib/telegram'
import { t } from '../lib/i18n'
import Icon from './Icon.vue'

const props = defineProps({
  to: { type: [Object, String], default: null }, // куда вести при «вытягивании»; null — без стрелки
  gap: { type: Number, default: 12 },
})
const router = useRouter()
const scroller = ref(null)
const root = ref(null)
const armed = ref(false)
const ZONE = 88
let raf = 0
let touching = false

function measure() {
  raf = 0
  const el = scroller.value
  if (!el || !props.to) return
  const max = el.scrollWidth - el.clientWidth
  const reveal = Math.min(1, Math.max(0, (el.scrollLeft - (max - ZONE)) / ZONE))
  root.value?.style.setProperty('--reveal', reveal.toFixed(3))
  const nowArmed = reveal > 0.82
  if (nowArmed !== armed.value) {
    armed.value = nowArmed
    if (nowArmed && touching) haptic.select()
  }
}
const onScroll = () => { if (!raf) raf = requestAnimationFrame(measure) }

function open() {
  if (!props.to) return
  haptic.medium()
  router.push(props.to)
}
function onTouchStart() { touching = true }
function onTouchEnd() {
  touching = false
  if (armed.value) open()
}

onMounted(() => measure())
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <div ref="root" class="pc" :class="{ armed }">
    <div
      ref="scroller"
      class="pc-scroll"
      :style="{ gap: gap + 'px' }"
      @scroll.passive="onScroll"
      @touchstart.passive="onTouchStart"
      @touchend.passive="onTouchEnd"
      @touchcancel.passive="touching = false"
    >
      <slot />
      <div v-if="to" class="pc-zone" aria-hidden="false">
        <button class="pc-arrow" :aria-label="t('common.see_all')" tabindex="0" @click="open">
          <Icon name="arrow-right" :size="22" />
        </button>
        <span class="pc-label">{{ armed ? t('common.release_open') : t('common.more_short') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pc { --reveal: 0; position: relative; }
.pc-scroll {
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
  scroll-snap-type: x mandatory;
  scroll-padding: 0 var(--gutter);
  margin: 0 calc(var(--gutter) * -1);
  padding: 2px var(--gutter) 6px;
  scrollbar-width: none;
  overscroll-behavior-x: contain;
  -webkit-overflow-scrolling: touch;
}
.pc-scroll::-webkit-scrollbar { display: none; }
.pc-scroll > :deep(*:not(.pc-zone)) { scroll-snap-align: start; flex-shrink: 0; }
.pc-zone {
  flex: 0 0 80px;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  /* зона без точки привязки: после отпускания карусель мягко возвращается к последней карточке */
  scroll-snap-align: none;
}
.pc-arrow {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--text);
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
  opacity: var(--reveal);
  transform: translateX(calc((1 - var(--reveal)) * -18px)) scale(calc(0.6 + var(--reveal) * 0.4));
  transition: background 0.25s, color 0.25s, box-shadow 0.25s;
  will-change: transform, opacity;
}
.pc-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  white-space: nowrap;
  opacity: var(--reveal);
  transition: color 0.2s;
}
.armed .pc-arrow {
  background: var(--accent-grad);
  border-color: transparent;
  color: var(--on-accent);
  box-shadow: 0 10px 26px -8px rgb(var(--accent-mid-rgb) / 0.75);
}
.armed .pc-label { color: var(--text); }
@media (hover: hover) {
  .pc-arrow { opacity: max(var(--reveal), 0.5); }
}
</style>
