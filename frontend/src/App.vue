<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { canGoBack, goBack } from './router'
import { api } from './lib/api'
import { t } from './lib/i18n'
import { setBackButton, startParam } from './lib/telegram'
import { useSession } from './stores/session'
import { usePlayer } from './stores/player'
import { useUi } from './stores/ui'
import TabBar from './components/TabBar.vue'
import MiniPlayer from './components/MiniPlayer.vue'
import PlayerSheet from './components/PlayerSheet.vue'
import ActionSheet from './components/ActionSheet.vue'
import AlbumPicker from './components/AlbumPicker.vue'
import AlbumEditor from './components/AlbumEditor.vue'
import Toast from './components/Toast.vue'
import Icon from './components/Icon.vue'
import SeasonDecor from './components/SeasonDecor.vue'
import LoadingSplash from './components/LoadingSplash.vue'

const session = useSession()
const player = usePlayer()
const ui = useUi()
const route = useRoute()
const router = useRouter()

// Кнопка «Назад» Telegram: закрывает слои по порядку, затем навигация
const backState = computed(() => {
  if (session.status !== 'ready') return null
  if (ui.editor) return 'editor'
  if (ui.pickerTrack) return 'picker'
  if (ui.actionTrack) return 'actions'
  if (player.queueOpen) return 'queue'
  if (player.sheetOpen) return 'player'
  if (!route.meta.root) return 'route'
  return null
})
watch(backState, (s) => {
  setBackButton(s ? () => {
    if (s === 'editor') ui.closeEditor()
    else if (s === 'picker') ui.closePicker()
    else if (s === 'actions') ui.closeActions()
    else if (s === 'queue') player.queueOpen = false
    else if (s === 'player') player.sheetOpen = false
    else if (canGoBack()) goBack()
    else router.replace('/')
  } : null)
}, { immediate: true })

// Ссылка «поделиться»: t_<id> — сразу открываем плеер, a_<code> — альбом
let deepLinkHandled = false
async function handleDeepLink() {
  if (deepLinkHandled) return
  deepLinkHandled = true
  const param = startParam()
  if (!param) return
  if (param.startsWith('a_')) {
    router.push({ name: 'shared-album', params: { code: param.slice(2) } })
    return
  }
  try {
    const track = await api.track(Number(param.slice(2)))
    player.playList([track], 0) // если WebView запретит автозапуск — трек будет на паузе
    player.sheetOpen = true
  } catch {
    ui.toast(t('errors.track_not_found'))
  }
}

async function start() {
  await session.init()
  if (session.status === 'ready') {
    player.restore()
    handleDeepLink()
  }
}
onMounted(start)
</script>

<template>
  <div class="app-bg" aria-hidden="true" />
  <SeasonDecor />
  <div v-if="session.status === 'ready'" class="app">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in">
        <KeepAlive :include="['HomeView', 'SearchView', 'LibraryView']" :max="4">
          <component :is="Component" :key="['tracks', 'album', 'shared-album', 'albums'].includes(route.name) ? route.fullPath : route.name" />
        </KeepAlive>
      </Transition>
    </RouterView>
    <MiniPlayer />
    <TabBar />
    <PlayerSheet />
    <ActionSheet />
    <AlbumPicker />
    <AlbumEditor />
    <Toast />
  </div>

  <!-- ===== Техническое обслуживание ===== -->
  <div v-else-if="session.status === 'maintenance'" class="splash maint">
    <div class="maint-art" aria-hidden="true">
      <span class="note n1">♪</span><span class="note n2">♫</span><span class="note n3">♩</span>
      <div class="maint-logo"><Icon name="headphones" :size="40" /></div>
      <div class="gear"><Icon name="settings" :size="22" /></div>
    </div>
    <h2>{{ t('maintenance.title') }}</h2>
    <p class="muted">{{ session.config.maintenance_text || t('maintenance.text') }}</p>
    <p class="faint small">{{ t('maintenance.soon') }}</p>
    <button class="btn btn-ghost" @click="start"><Icon name="refresh" :size="18" />{{ t('maintenance.check') }}</button>
  </div>

  <!-- ===== Доступ ограничен администратором ===== -->
  <div v-else-if="session.status === 'banned'" class="splash banned">
    <div class="logo muted-logo"><Icon name="lock" :size="32" /></div>
    <h2>{{ t('splash.banned_title') }}</h2>
    <p class="muted">{{ t('splash.banned_text') }}</p>
  </div>

  <LoadingSplash v-else-if="session.status === 'idle' || session.status === 'loading'" />

  <div v-else class="splash">
    <div class="logo"><Icon name="headphones" :size="34" /></div>
    <template v-if="session.status === 'no-telegram'">
      <h2>{{ t('splash.open_in_tg') }}</h2>
      <p class="muted">{{ t('splash.open_in_tg_text') }}</p>
    </template>
    <template v-else-if="session.status === 'error'">
      <h2>{{ t('splash.error') }}</h2>
      <p class="muted">{{ t('splash.error_text') }}</p>
      <button class="btn btn-primary" @click="start">{{ t('common.retry') }}</button>
    </template>
  </div>
</template>

<style>
.splash {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 32px;
  text-align: center;
  background: radial-gradient(60% 40% at 50% 30%, rgb(var(--accent-rgb) / 0.22), transparent 70%), var(--bg);
}
.splash h2 { font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }
.splash p { max-width: 300px; }
.splash.loading { gap: 18px; }
.splash .small { font-size: 13px; }
.logo {
  width: 76px; height: 76px; border-radius: 24px;
  display: grid; place-items: center; color: var(--on-accent);
  background: var(--accent-grad);
  box-shadow: 0 20px 50px -14px rgb(var(--accent-mid-rgb) / 0.7);
  animation: breathe 2.4s ease-in-out infinite;
}
@keyframes breathe { 50% { transform: scale(1.06); } }
.muted-logo { background: var(--surface-3); color: var(--text-2); box-shadow: none; animation: none; }
.loader { display: flex; gap: 6px; margin-top: 8px; }
.loader i { width: 8px; height: 8px; border-radius: 50%; background: var(--text-2); animation: dot 1s ease-in-out infinite; }
.loader i:nth-child(2) { animation-delay: 0.15s; }
.loader i:nth-child(3) { animation-delay: 0.3s; }
@keyframes dot { 0%, 100% { opacity: 0.25; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-4px); } }

/* заглушка обслуживания */
.maint { background: radial-gradient(55% 40% at 50% 32%, rgb(var(--accent-2-rgb) / 0.18), transparent 70%), radial-gradient(60% 45% at 50% 28%, rgb(var(--accent-rgb) / 0.25), transparent 70%), var(--bg); }
.maint-art { position: relative; width: 150px; height: 130px; margin-bottom: 6px; }
.maint-logo {
  position: absolute; left: 50%; top: 50%; width: 92px; height: 92px; margin: -46px 0 0 -46px;
  border-radius: 30px; display: grid; place-items: center; color: var(--on-accent);
  background: var(--accent-grad); box-shadow: 0 24px 60px -16px rgb(var(--accent-mid-rgb) / 0.8);
  animation: breathe 3s ease-in-out infinite;
}
.gear {
  position: absolute; right: 22px; bottom: 6px; width: 40px; height: 40px; border-radius: 50%;
  display: grid; place-items: center; color: #ffd27a;
  background: rgba(20, 20, 26, 0.9); border: 1px solid rgba(255, 210, 122, 0.35);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
}
.gear .icon { animation: spin 4s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.note { position: absolute; font-size: 22px; color: rgba(255, 255, 255, 0.55); animation: float 3.2s ease-in-out infinite; }
.n1 { left: 4px; top: 30px; }
.n2 { right: 8px; top: 8px; animation-delay: -1s; font-size: 26px; }
.n3 { left: 26px; bottom: 0; animation-delay: -2s; font-size: 18px; }
@keyframes float { 0%, 100% { transform: translateY(0) rotate(-6deg); opacity: 0.35; } 50% { transform: translateY(-12px) rotate(6deg); opacity: 0.85; } }
</style>
