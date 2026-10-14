<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },     // 0..1
  buffered: { type: Number, default: 0 },  // 0..1
  label: { type: String, default: '' },
  thin: { type: Boolean, default: false },
})
const emit = defineEmits(['seek', 'preview'])

const track = ref(null)
const dragging = ref(false)
const dragValue = ref(0)
const shown = computed(() => (dragging.value ? dragValue.value : props.value))

// размеры полосы запоминаем в начале жеста — без пересчёта раскладки на каждое движение
let rect = null
function fractionAt(e) {
  const r = rect || track.value.getBoundingClientRect()
  return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
}
function down(e) {
  rect = track.value.getBoundingClientRect()
  dragging.value = true
  dragValue.value = fractionAt(e)
  emit('preview', dragValue.value)
  e.currentTarget.setPointerCapture?.(e.pointerId)
}
function move(e) {
  if (!dragging.value) return
  dragValue.value = fractionAt(e)
  emit('preview', dragValue.value)
}
function up() {
  if (!dragging.value) return
  dragging.value = false
  rect = null
  emit('seek', dragValue.value)
  emit('preview', null)
}
function key(e) {
  const step = e.shiftKey ? 0.1 : 0.02
  if (e.key === 'ArrowRight') emit('seek', Math.min(1, props.value + step))
  if (e.key === 'ArrowLeft') emit('seek', Math.max(0, props.value - step))
}
</script>

<template>
  <div
    class="seek"
    :class="{ dragging, thin }"
    role="slider"
    tabindex="0"
    :aria-label="label"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-valuenow="Math.round(shown * 100)"
    @pointerdown.stop="down"
    @pointermove="move"
    @pointerup="up"
    @pointercancel="up"
    @keydown="key"
  >
    <div ref="track" class="rail">
      <div class="buf" :style="{ transform: `scaleX(${buffered})` }" />
      <div class="fill" :style="{ transform: `scaleX(${shown})` }" />
      <div class="knob-pos" :style="{ transform: `translate3d(${shown * 100}%, 0, 0)` }"><div class="knob" /></div>
    </div>
  </div>
</template>

<style scoped>
.seek { padding: 12px 0; touch-action: none; cursor: pointer; }
.rail {
  position: relative;
  height: 4px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.14);
  transition: transform 0.2s var(--ease);
}
/* утолщение — через transform, а не height (без перерасчёта раскладки) */
.dragging .rail { transform: scaleY(1.75); }
.buf, .fill {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  transform-origin: left;
}
.buf { background: rgba(255, 255, 255, 0.16); }
.fill { background: #fff; }
.knob-pos { position: absolute; inset: 0; pointer-events: none; }
.knob {
  position: absolute;
  left: 0;
  top: 50%;
  width: 14px;
  height: 14px;
  margin: -7px 0 0 -7px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4);
  transform: scale(0.8);
  transition: transform 0.2s var(--ease-spring);
}
.dragging .knob { transform: scale(1.25) scaleY(0.571); } /* компенсируем scaleY полосы */
.thin .knob { display: none; }
</style>
