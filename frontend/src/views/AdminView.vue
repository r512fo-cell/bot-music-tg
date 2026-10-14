<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import { storage } from '../lib/format'
import StatsTab from '../components/admin/StatsTab.vue'
import TracksTab from '../components/admin/TracksTab.vue'
import UsersTab from '../components/admin/UsersTab.vue'
import BroadcastTab from '../components/admin/BroadcastTab.vue'
import AdsTab from '../components/admin/AdsTab.vue'
import SettingsTab from '../components/admin/SettingsTab.vue'
import ContentTab from '../components/admin/ContentTab.vue'
import SubmissionsTab from '../components/admin/SubmissionsTab.vue'
import '../components/admin/admin.css'

const TABS = [
  { id: 'stats', comp: StatsTab },
  { id: 'subs', comp: SubmissionsTab },
  { id: 'content', comp: ContentTab },
  { id: 'tracks', comp: TracksTab },
  { id: 'users', comp: UsersTab },
  { id: 'broadcast', comp: BroadcastTab },
  { id: 'ads', comp: AdsTab },
  { id: 'settings', comp: SettingsTab },
]
const saved = storage.get('admin.tab')
const tab = ref(TABS.some((x) => x.id === saved) ? saved : 'stats')
const pending = ref(0)
onMounted(async () => { try { pending.value = (await api.admin.submissionsCount()).pending } catch {} })
function select(id) { tab.value = id; haptic.select(); storage.set('admin.tab', id) }
</script>

<template>
  <div class="page admin">
    <h1 class="page-title">{{ t('admin.title') }}</h1>
    <div class="tabs h-scroll">
      <button v-for="x in TABS" :key="x.id" class="chip" :class="{ active: tab === x.id }" @click="select(x.id)">
        {{ t(`admin.tab_${x.id}`) }}
        <span v-if="x.id === 'subs' && pending" class="badge-dot tnum">{{ pending }}</span>
      </button>
    </div>
    <KeepAlive>
      <component :is="TABS.find((x) => x.id === tab).comp" :key="tab" @count="pending = $event" />
    </KeepAlive>
  </div>
</template>

<style scoped>
.page-title { margin-bottom: 14px; }
.tabs { gap: 8px; margin-bottom: 16px; }
.badge-dot {
  min-width: 18px; height: 18px; padding: 0 5px; margin-left: 2px; border-radius: 999px;
  display: inline-grid; place-items: center; font-size: 11px; font-weight: 800; color: #fff; background: var(--accent-2);
}
</style>
