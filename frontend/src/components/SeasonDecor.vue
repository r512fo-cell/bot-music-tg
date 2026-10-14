<script setup>
// Лёгкий сезонный декор в верхней части экрана: несколько элементов, только transform/opacity.
// Не перекрывает контент (рисуется под ним), не ловит нажатия, уважает «уменьшение движения».
import { computed } from 'vue'
import { season } from '../lib/theme'

const props = defineProps({ variant: { type: String, default: 'page' } }) // page | player

const SETS = {
  autumn: { glyphs: ['🍂', '🍁', '🍂', '🍂', '🍁', '🍂', '🍁'], kind: 'fall' },
  winter: { glyphs: ['❄', '❅', '❆', '❄', '❅', '❄', '❆', '❄', '❅'], kind: 'snow' },
  spring: { glyphs: ['🌸', '🌸', '🌼', '🌸', '🌸', '🌼'], kind: 'fall' },
  summer: { glyphs: ['✦', '✧', '✦', '✧', '✦'], kind: 'twinkle' },
}

// Детерминированные позиции: одинаковы при каждом рендере, без Math.random
const items = computed(() => {
  const set = SETS[season.value]
  if (!set) return []
  const n = props.variant === 'player' ? Math.min(6, set.glyphs.length) : set.glyphs.length
  return set.glyphs.slice(0, n).map((g, i) => {
    const x = (i * 37 + 9) % 100
    return {
      g,
      style: {
        left: `${x}%`,
        top: `${(i * 23) % (props.variant === 'player' ? 60 : 70)}px`,
        fontSize: `${set.kind === 'snow' ? 9 + (i % 3) * 3 : set.kind === 'twinkle' ? 8 + (i % 3) * 3 : 13 + (i % 3) * 3}px`,
        animationDuration: `${9 + (i % 4) * 2.5}s`,
        animationDelay: `${-(i * 1.7)}s`,
        opacity: set.kind === 'twinkle' ? 0.8 : 0.55 + (i % 3) * 0.12,
      },
    }
  })
})
const kind = computed(() => SETS[season.value]?.kind)
</script>

<template>
  <div v-if="items.length" class="decor" :class="[variant, kind, season]" aria-hidden="true">
    <span v-if="season === 'summer'" class="sun" />
    <span v-for="(it, i) in items" :key="i" class="it" :style="it.style">{{ it.g }}</span>
  </div>
</template>

<style scoped>
.decor {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  height: 190px;
  overflow: hidden;
  pointer-events: none;
  -webkit-mask-image: linear-gradient(180deg, #000 45%, transparent 100%);
  mask-image: linear-gradient(180deg, #000 45%, transparent 100%);
}
.decor.player { position: absolute; height: 150px; z-index: 0; }
.it {
  position: absolute;
  line-height: 1;
  will-change: transform, opacity;
  user-select: none;
}
.snow .it { color: #eaf6ff; text-shadow: 0 0 6px rgba(170, 215, 255, 0.6); }
.twinkle .it { color: #ffe39a; text-shadow: 0 0 8px rgba(255, 210, 100, 0.7); }

/* медленное падение с покачиванием, исчезает в нижней части полосы */
.fall .it, .snow .it { animation-name: drift; animation-timing-function: linear; animation-iteration-count: infinite; }
@keyframes drift {
  0% { transform: translate3d(0, -30px, 0) rotate(0deg); opacity: 0; }
  12% { opacity: 1; }
  50% { transform: translate3d(14px, 70px, 0) rotate(120deg); }
  85% { opacity: 0.8; }
  100% { transform: translate3d(-6px, 150px, 0) rotate(230deg); opacity: 0; }
}
.snow .it { animation-name: snow; }
@keyframes snow {
  0% { transform: translate3d(0, -20px, 0); opacity: 0; }
  15% { opacity: 1; }
  50% { transform: translate3d(8px, 70px, 0); }
  100% { transform: translate3d(-4px, 160px, 0); opacity: 0; }
}
.twinkle .it { animation: twinkle 3.2s ease-in-out infinite; }
@keyframes twinkle {
  0%, 100% { transform: scale(0.6); opacity: 0.15; }
  50% { transform: scale(1.1); opacity: 0.9; }
}
.sun {
  position: absolute;
  right: -60px;
  top: -70px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 214, 102, 0.35) 0%, rgba(255, 190, 70, 0.12) 40%, transparent 70%);
}
@media (prefers-reduced-motion: reduce) {
  .it { animation: none !important; }
}
</style>
