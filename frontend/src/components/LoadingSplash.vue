<script setup>
// Экран загрузки. Если вход занимает дольше обычного, появляются короткие фразы:
// плавно всплывают из лёгкого размытия и так же растворяются, сменяя друг друга.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { locale, t, tlist } from '../lib/i18n'
import Icon from './Icon.vue'

const SHOW_AFTER = 900 // быстрые загрузки обходятся без текста — он не успевает «мигнуть»
const EVERY = 3800

const quotes = computed(() => tlist('splash.quotes'))
// случайный порядок; фразы идут по кругу
const order = ref([])
const step = ref(-1)
const current = computed(() => (step.value < 0 ? '' : quotes.value[order.value[step.value % order.value.length]] || ''))

let delay = 0
let timer = 0
onMounted(() => {
  const n = quotes.value.length
  order.value = Array.from({ length: n }, (_, i) => i).sort(() => Math.random() - 0.5)
  delay = setTimeout(() => {
    step.value = 0
    timer = setInterval(() => { step.value++ }, EVERY)
  }, SHOW_AFTER)
})
onBeforeUnmount(() => { clearTimeout(delay); clearInterval(timer) })
</script>

<template>
  <div class="splash loading" :lang="locale">
    <div class="logo"><Icon name="headphones" :size="34" /></div>
    <div class="loader" :aria-label="t('common.loading')"><i /><i /><i /></div>
    <div class="quote-box" aria-live="polite">
      <Transition name="quote" mode="out-in">
        <p v-if="current" :key="step" class="quote">{{ current }}</p>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
/* место под фразу зарезервировано — логотип не сдвигается, когда текст появляется */
.quote-box {
  position: absolute;
  left: 28px;
  right: 28px;
  top: calc(50% + 78px);
  display: flex;
  justify-content: center;
  min-height: 72px;
}
.quote {
  max-width: 320px;
  font-size: 15.5px;
  line-height: 1.5;
  font-weight: 500;
  color: var(--text-2);
  text-wrap: balance;
}
.quote-enter-active { transition: opacity 0.9s var(--ease), transform 0.9s var(--ease), filter 0.9s var(--ease); }
.quote-leave-active { transition: opacity 0.6s ease-in, transform 0.6s ease-in, filter 0.6s ease-in; }
.quote-enter-from { opacity: 0; transform: translateY(10px); filter: blur(6px); }
.quote-leave-to { opacity: 0; transform: translateY(-8px); filter: blur(6px); }
@media (prefers-reduced-motion: reduce) {
  .quote-enter-active, .quote-leave-active { transition: opacity 0.4s; }
  .quote-enter-from, .quote-leave-to { transform: none; filter: none; }
}
</style>
