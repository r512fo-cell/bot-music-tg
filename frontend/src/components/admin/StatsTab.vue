<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../../lib/api'
import { artist, bytes, compact, date, listenTime, num, relative } from '../../lib/format'
import { errorText, t } from '../../lib/i18n'
import { haptic } from '../../lib/telegram'
import { useUi } from '../../stores/ui'
import Cover from '../Cover.vue'
import Icon from '../Icon.vue'

const ui = useUi()
const stats = ref(null)
const error = ref('')
const hover = ref(null)
const showTable = ref(false)
let poll = null
let alive = true // после ухода с вкладки опрос не продолжается

async function load() {
  try {
    stats.value = await api.admin.stats()
    error.value = ''
    clearTimeout(poll)
    if (alive && stats.value?.sync?.running) poll = setTimeout(load, 2000)
  } catch (e) { error.value = errorText(e) }
}
async function sync(full) {
  haptic.medium()
  try {
    const res = await api.admin.sync(full)
    ui.toast(res.started ? (full ? t('admin.sync_full_started') : t('admin.sync_started')) : t('admin.sync_running_toast'))
    stats.value = { ...stats.value, sync: res.sync }
    clearTimeout(poll); poll = setTimeout(load, 800)
  } catch (e) { ui.toast(errorText(e)) }
}

async function historyReset() {
  try { await api.admin.historyReset(); ui.toast(t('admin.history_reset_done')); await load() } catch (e) { ui.toast(errorText(e)) }
}

const o = computed(() => stats.value?.overview || {})
const series = computed(() => stats.value?.series || [])
const maxPlays = computed(() => Math.max(1, ...series.value.map((d) => d.plays)))
const totalPlays14 = computed(() => series.value.reduce((a, d) => a + d.plays, 0))
const kpis = computed(() => [
  { icon: 'users', label: t('admin.kpi_users'), value: num(o.value.users_total), sub: t('admin.kpi_users_sub', { today: num(o.value.users_today), week: num(o.value.users_week) }) },
  { icon: 'flame', label: t('admin.kpi_active'), value: num(o.value.dau), sub: `DAU · WAU ${num(o.value.wau)} · MAU ${num(o.value.mau)}` },
  { icon: 'headphones', label: t('admin.kpi_plays'), value: compact(o.value.plays_total), sub: t('admin.kpi_today', { n: num(o.value.plays_today) }) },
  { icon: 'music', label: t('admin.kpi_tracks'), value: num(o.value.tracks_total), sub: t('admin.kpi_tracks_sub', { week: num(o.value.tracks_week), hidden: num(o.value.tracks_hidden) }) },
  { icon: 'heart', label: t('admin.kpi_likes'), value: num(o.value.favorites_total), sub: t('admin.kpi_likes_sub') },
  { icon: 'clock', label: t('admin.kpi_library'), value: listenTime(o.value.library_seconds), sub: t('admin.kpi_library_sub') },
])
const shortDate = (ts) => date(ts, { day: 'numeric', month: 'short' })

onMounted(load)
onBeforeUnmount(() => { alive = false; clearTimeout(poll) })
</script>

<template>
  <div v-if="error && !stats" class="empty">
    <p>{{ error }}</p>
    <button class="btn" @click="load">{{ t('common.retry') }}</button>
  </div>

  <template v-else-if="stats">
    <div class="status card">
      <span class="dot" :class="stats.system.telegram_ready ? 'ok' : 'bad'" />
      <div class="status-text">
        <b>{{ stats.system.telegram_ready ? t('admin.bot_online') : t('admin.bot_offline') }}</b>
        <span class="muted ellipsis">
          {{ stats.system.channel || t('admin.no_channel') }}<template v-if="stats.system.bot"> · @{{ stats.system.bot }}</template>
        </span>
      </div>
      <button class="icon-btn" :aria-label="t('common.refresh')" @click="load"><Icon name="refresh" :size="20" /></button>
    </div>

    <div class="kpis">
      <div v-for="k in kpis" :key="k.icon" class="kpi card">
        <div class="kpi-head"><Icon :name="k.icon" :size="16" />{{ k.label }}</div>
        <div class="kpi-value tnum">{{ k.value }}</div>
        <div class="kpi-sub">{{ k.sub }}</div>
      </div>
    </div>

    <!-- одна серия — прослушивания по дням -->
    <section class="card chart-card">
      <div class="chart-head">
        <div>
          <h3>{{ t('admin.chart_title') }}</h3>
          <p v-if="hover != null && series[hover]" class="muted tnum">
            <b class="hl">{{ shortDate(series[hover].date) }}: {{ num(series[hover].plays) }}</b>
            · {{ t('admin.chart_detail', { l: num(series[hover].listeners), n: num(series[hover].new_users) }) }}
          </p>
          <p v-else class="muted tnum">{{ t('admin.chart_total', { n: num(totalPlays14) }) }}</p>
        </div>
        <button class="chip small-chip" @click="showTable = !showTable">{{ showTable ? t('admin.chart') : t('admin.table') }}</button>
      </div>
      <div v-if="!showTable" class="chart" @pointerleave="hover = null">
        <div class="grid-line"><span class="tnum">{{ num(maxPlays) }}</span></div>
        <div class="bars">
          <div v-for="(d, i) in series" :key="d.date" class="bar-hit" @pointerenter="hover = i" @click="hover = i">
            <div class="bar" :class="{ active: hover === i }" :style="{ height: `${Math.max(2, (d.plays / maxPlays) * 100)}%` }" />
          </div>
        </div>
        <div class="axis tnum">
          <span>{{ series[0] && shortDate(series[0].date) }}</span>
          <span>{{ t('time.today') }}</span>
        </div>
      </div>
      <table v-else class="table tnum">
        <thead><tr><th>{{ t('admin.col_date') }}</th><th>{{ t('admin.col_plays') }}</th><th>{{ t('admin.col_listeners') }}</th><th>{{ t('admin.col_new') }}</th></tr></thead>
        <tbody>
          <tr v-for="d in [...series].reverse()" :key="d.date">
            <td>{{ shortDate(d.date) }}</td><td>{{ num(d.plays) }}</td><td>{{ num(d.listeners) }}</td><td>{{ num(d.new_users) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="section">
      <div class="section-head"><h2 class="section-title">{{ t('admin.top_week') }}</h2></div>
      <div v-if="stats.top.length" class="card list-card">
        <div v-for="(tr, i) in stats.top" :key="tr.id" class="row-item">
          <span class="rank tnum">{{ i + 1 }}</span>
          <Cover :track="tr" radius="8px" class="mini-cover" />
          <div class="grow">
            <div class="ellipsis r-title">{{ tr.title }}</div>
            <div class="ellipsis r-sub">{{ artist(tr) }}</div>
          </div>
          <div class="r-num tnum"><b>{{ compact(tr.plays) }}</b><span>♥ {{ tr.likes }}</span></div>
        </div>
      </div>
      <p v-else class="muted">{{ t('admin.no_plays_week') }}</p>
    </section>

    <section class="section">
      <div class="section-head"><h2 class="section-title">{{ t('admin.sync_title') }}</h2></div>
      <div class="card sync">
        <p class="muted">{{ t('admin.sync_desc') }}</p>
        <div v-if="stats.sync.running" class="sync-progress">
          <span class="spinner" />{{ t(stats.sync.full ? 'admin.sync_progress_full' : 'admin.sync_progress', { s: num(stats.sync.scanned), f: num(stats.sync.found) }) }}
        </div>
        <div v-else-if="stats.system.last_sync" class="faint small">
          {{ t('admin.sync_last', { when: relative(stats.system.last_sync) }) }}
          <template v-if="stats.sync.finished_at"> · {{ t('admin.sync_result', { f: num(stats.sync.found), d: num(stats.sync.deleted) }) }}</template>
          <span v-if="stats.sync.error" class="err"> · {{ stats.sync.error }}</span>
        </div>
        <div v-if="stats.system.history_floor" class="floor">
          <span>{{ t('admin.history_floor', { n: stats.system.history_floor }) }}</span>
          <button class="link" @click="historyReset">{{ t('admin.history_reset') }}</button>
        </div>
        <div class="btn-row">
          <button class="btn" :disabled="stats.sync.running || !stats.system.telegram_ready" @click="sync(false)"><Icon name="refresh" :size="18" />{{ t('admin.sync_quick') }}</button>
          <button class="btn btn-ghost" :disabled="stats.sync.running || !stats.system.telegram_ready" @click="sync(true)"><Icon name="database" :size="18" />{{ t('admin.sync_full') }}</button>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><h2 class="section-title">{{ t('admin.system') }}</h2></div>
      <div class="card sys">
        <div><span class="muted">{{ t('admin.version') }}</span><b>{{ stats.system.version }}</b></div>
        <div><span class="muted">{{ t('admin.db_size') }}</span><b class="tnum">{{ bytes(stats.system.db_size) }}</b></div>
        <div><span class="muted">{{ t('admin.covers_size') }}</span><b class="tnum">{{ bytes(stats.system.covers_size) }}</b></div>
        <div><span class="muted">{{ t('admin.started_bot') }}</span><b class="tnum">{{ num(o.users_started) }}</b></div>
      </div>
    </section>
  </template>
  <div v-else class="kpis">
    <div v-for="i in 6" :key="i" class="skeleton kpi-sk" />
  </div>
</template>

<style scoped>
.status { display: flex; align-items: center; gap: 12px; padding: 12px 10px 12px 16px; }
.status-text { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: 14px; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot.ok { background: var(--success); box-shadow: 0 0 0 4px rgba(61, 220, 151, 0.18); }
.dot.bad { background: var(--danger); box-shadow: 0 0 0 4px rgba(255, 92, 108, 0.18); }
.kpis { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.kpi { padding: 14px; min-width: 0; }
.kpi-sk { height: 104px; border-radius: var(--radius); }
.kpi-head { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-2); font-weight: 500; }
.kpi-value { font-size: 26px; font-weight: 800; letter-spacing: -0.03em; margin-top: 6px; }
.kpi-sub { font-size: 11.5px; color: var(--text-3); margin-top: 2px; line-height: 1.3; }
.chart-card { margin-top: 10px; padding: 16px; }
.chart-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.chart-head h3 { font-size: 16px; font-weight: 700; }
.chart-head p { font-size: 13px; }
.hl { color: var(--text); font-weight: 600; }
.small-chip { height: 30px; font-size: 12.5px; }
.chart { position: relative; margin-top: 24px; }
.grid-line { position: absolute; left: 0; right: 0; top: 0; border-top: 1px dashed rgba(255, 255, 255, 0.08); }
.grid-line span { position: absolute; right: 0; top: -16px; font-size: 11px; color: var(--text-3); }
.bars { display: flex; align-items: flex-end; gap: 2px; height: 140px; border-bottom: 1px solid rgba(255, 255, 255, 0.1); }
.bar-hit { flex: 1; height: 100%; display: flex; align-items: flex-end; cursor: pointer; }
.bar { width: 100%; background: var(--accent); border-radius: 4px 4px 0 0; opacity: 0.85; transition: height 0.5s var(--ease), opacity 0.2s; }
.bar.active { opacity: 1; box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.5); }
.axis { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); margin-top: 6px; }
.table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13.5px; }
.table th { text-align: left; color: var(--text-3); font-weight: 500; padding: 6px 4px; }
.table td { padding: 7px 4px; border-top: 1px solid var(--border); }
.rank { width: 18px; text-align: center; font-weight: 800; color: var(--text-3); }
.sync { padding: 16px; display: grid; gap: 12px; font-size: 14px; }
.floor { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; color: var(--text-2); }
.floor .link { color: var(--accent); font-weight: 600; flex-shrink: 0; }
.sync-progress { display: flex; align-items: center; gap: 10px; font-size: 13.5px; }
.small { font-size: 13px; }
.err { color: var(--danger); }
.sys { padding: 4px 16px; }
.sys div { display: flex; justify-content: space-between; padding: 11px 0; border-bottom: 1px solid var(--border); font-size: 14.5px; }
.sys div:last-child { border-bottom: 0; }
</style>
