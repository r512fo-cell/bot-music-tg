<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { haptic } from '../lib/telegram'
import { t } from '../lib/i18n'
import { useSession } from '../stores/session'
import Icon from './Icon.vue'

const route = useRoute()
const session = useSession()
const tabs = [
  { to: '/', name: 'home', icon: 'home', label: 'tabs.home' },
  { to: '/search', name: 'search', icon: 'search', label: 'tabs.search' },
  { to: '/library', name: 'library', icon: 'heart', label: 'tabs.library' },
  { to: '/profile', name: 'profile', icon: 'user', label: 'tabs.profile' },
]
const index = computed(() => Math.max(0, tabs.findIndex((x) => x.name === route.meta.tab)))
// Счётчик нажатий на вкладку: смена ключа перезапускает анимацию даже на уже активной вкладке
const taps = ref({})

function tap(tab) {
  haptic.select()
  taps.value = { ...taps.value, [tab.name]: (taps.value[tab.name] || 0) + 1 }
  if (route.meta.tab === tab.name && route.meta.root) window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <nav class="tabbar glass" :aria-label="t('tabs.nav')" :style="{ '--i': index }">
    <span class="indicator" aria-hidden="true" />
    <RouterLink
      v-for="tab in tabs"
      :key="tab.name"
      :to="tab.to"
      replace
      class="tab"
      :class="{ active: index === tabs.indexOf(tab) }"
      :aria-current="index === tabs.indexOf(tab) ? 'page' : undefined"
      @click="tap(tab)"
    >
      <span :key="taps[tab.name] || 0" class="ico" :class="{ pop: taps[tab.name] }">
        <template v-if="tab.name === 'profile'">
          <span class="ava" :class="{ vip: session.isVip }">
            <img v-if="session.avatar" :src="session.avatar" alt="" />
            <span v-else-if="session.initials" class="ini">{{ session.initials }}</span>
            <Icon v-else name="user" :size="16" />
          </span>
        </template>
        <Icon v-else :name="tab.icon" :size="23" />
      </span>
      <span class="label">{{ t(tab.label) }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.tabbar {
  position: fixed;
  z-index: 45;
  left: 0;
  right: 0;
  bottom: 0;
  height: calc(var(--tabbar-h) + var(--safe-bottom));
  padding: 0 6px var(--safe-bottom);
  display: flex;
  border-top: 1px solid var(--border);
  background: var(--glass-strong);
}
/* скользящая подсветка активной вкладки: только transform — без перерасчёта раскладки */
.indicator {
  position: absolute;
  top: 6px;
  left: 6px;
  width: calc((100% - 12px) / 4);
  height: 50px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.07);
  transform: translateX(calc(var(--i) * 100%));
  transition: transform 0.45s var(--ease-spring);
  pointer-events: none;
}
.indicator::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 18px;
  height: 3px;
  margin-left: -9px;
  border-radius: 3px;
  background: var(--accent-grad);
}
.tab {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  height: var(--tabbar-h);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  transition: color 0.25s;
}
.tab.active { color: var(--text); }
.ico { display: grid; place-items: center; height: 26px; transition: transform 0.2s var(--ease); }
.tab:active .ico { transform: scale(0.86); }
.ico.pop { animation: tab-pop 0.5s var(--ease-spring); }
@keyframes tab-pop {
  0% { transform: scale(0.8); }
  45% { transform: scale(1.18) translateY(-2px); }
  70% { transform: scale(0.96); }
  100% { transform: scale(1); }
}
.label { transition: transform 0.3s var(--ease), opacity 0.3s; }
.tab.active .label { transform: translateY(-1px); }

.ava {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  overflow: hidden;
  display: grid;
  place-items: center;
  background: var(--surface-3);
  box-shadow: 0 0 0 1.5px rgba(255, 255, 255, 0.18);
  transition: box-shadow 0.3s;
}
.ava img { width: 100%; height: 100%; object-fit: cover; }
.ini { font-size: 10.5px; font-weight: 800; color: var(--text); }
.tab.active .ava { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--accent-mid); }
/* Premium: золотистая окантовка аватара и в таб-баре */
.ava.vip { box-shadow: 0 0 0 1.6px rgba(255, 211, 110, 0.9), 0 0 10px rgba(255, 190, 100, 0.35); }
.tab.active .ava.vip { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px #ffd36e, 0 0 14px rgba(255, 190, 100, 0.45); }

@media (prefers-reduced-motion: reduce) {
  .indicator, .ico { transition: none; animation: none; }
}
</style>
