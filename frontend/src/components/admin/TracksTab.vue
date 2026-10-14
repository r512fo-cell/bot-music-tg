<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import { artist, bytes, compact, duration, num } from '../../lib/format'
import { errorText, t, tp } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useLibrary } from '../../stores/library'
import { useUi } from '../../stores/ui'
import Cover from '../Cover.vue'
import Icon from '../Icon.vue'
import InfiniteLoader from '../InfiniteLoader.vue'

const ui = useUi()
const lib = useLibrary()

// ----------------------------------------------------------------- список треков
const q = ref('')
const items = ref([])
const next = ref(0)
const loading = ref(false)
let timer = null
let ctrl = null

async function load(reset) {
  if (!reset && (loading.value || next.value == null)) return
  ctrl?.abort()
  ctrl = new AbortController()
  loading.value = true
  try {
    const res = await api.admin.tracks({ q: q.value.trim(), offset: reset ? 0 : next.value, limit: 30 }, ctrl.signal)
    items.value = reset ? res.items : [...items.value, ...res.items]
    next.value = res.next_offset
  } catch {} finally { loading.value = false }
}
async function toggleHidden(tr) {
  haptic.tap()
  const hidden = !tr.hidden
  tr.hidden = hidden
  try {
    await api.admin.setHidden(tr.id, hidden)
    ui.toast(hidden ? t('admin.track_hidden') : t('admin.track_shown'))
  } catch (e) { tr.hidden = !hidden; ui.toast(errorText(e)) }
}
watch(q, () => { clearTimeout(timer); timer = setTimeout(() => load(true), 300) })

// ----------------------------------------------------------------- правила скрытия
const rules = ref([])
const rule = reactive({ field: 'performer', mode: 'exact', pattern: '' })
const preview = ref(null)
const ruleBusy = ref(false)
let pvTimer = null
const ruleValid = computed(() => rule.pattern.trim().length >= 2)

async function loadRules() {
  try { rules.value = (await api.admin.rules()).items } catch {}
}
watch(() => [rule.field, rule.mode, rule.pattern], () => {
  clearTimeout(pvTimer)
  preview.value = null
  if (!ruleValid.value) return
  pvTimer = setTimeout(async () => {
    try { preview.value = await api.admin.previewRule({ ...rule, pattern: rule.pattern.trim() }) } catch {}
  }, 350)
})
async function addRule() {
  if (!ruleValid.value || ruleBusy.value) return
  ruleBusy.value = true
  try {
    const res = await api.admin.addRule({ ...rule, pattern: rule.pattern.trim() })
    haptic.success()
    ui.toast(t('admin.rule_added', { n: num(res.hidden) }))
    rule.pattern = ''
    await Promise.all([loadRules(), load(true)])
    lib.loadHome(true).catch(() => {})
  } catch (e) { ui.toast(errorText(e)); haptic.error() } finally { ruleBusy.value = false }
}
async function removeRule(r) {
  if (!(await confirmDialog(t('admin.rule_delete_confirm', { p: r.pattern })))) return
  try {
    const res = await api.admin.deleteRule(r.id)
    ui.toast(t('admin.rule_deleted', { n: num(res.shown) }))
    await Promise.all([loadRules(), load(true)])
    lib.loadHome(true).catch(() => {})
  } catch (e) { ui.toast(errorText(e)) }
}

// ----------------------------------------------------------------- очистка базы
const skipHistory = ref(true)
const clearing = ref(false)
async function clearAll() {
  if (!(await confirmDialog(t('admin.clear_confirm1')))) return
  if (!(await confirmDialog(t('admin.clear_confirm2')))) return
  clearing.value = true
  haptic.medium()
  try {
    const res = await api.admin.clearTracks(skipHistory.value)
    haptic.success()
    ui.toast(t('admin.cleared', { n: num(res.deleted) }))
    items.value = []
    await load(true)
    lib.loadHome(true).catch(() => {})
  } catch (e) { ui.toast(errorText(e)); haptic.error() } finally { clearing.value = false }
}

onMounted(() => { load(true); loadRules() })
</script>

<template>
  <!-- ===== скрытие по автору / названию ===== -->
  <section class="card card-pad rules">
    <div class="head-row">
      <span class="h-icon"><Icon name="eye-off" :size="19" /></span>
      <div class="grow">
        <b>{{ t('admin.rules_title') }}</b>
        <p class="r-sub">{{ t('admin.rules_desc') }}</p>
      </div>
    </div>
    <div class="seg two">
      <button type="button" :class="{ on: rule.field === 'performer' }" @click="rule.field = 'performer'">{{ t('admin.rule_performer') }}</button>
      <button type="button" :class="{ on: rule.field === 'title' }" @click="rule.field = 'title'">{{ t('admin.rule_title') }}</button>
    </div>
    <div class="seg two">
      <button type="button" :class="{ on: rule.mode === 'exact' }" @click="rule.mode = 'exact'">{{ t('admin.rule_exact') }}</button>
      <button type="button" :class="{ on: rule.mode === 'contains' }" @click="rule.mode = 'contains'">{{ t('admin.rule_contains') }}</button>
    </div>
    <form class="rule-row" @submit.prevent="addRule">
      <input v-model="rule.pattern" class="input" maxlength="100"
             :placeholder="rule.field === 'performer' ? t('admin.rule_ph_performer') : t('admin.rule_ph_title')" />
      <button class="btn btn-primary" :disabled="!ruleValid || ruleBusy || preview?.count === 0">{{ t('admin.hide') }}</button>
    </form>
    <p v-if="preview" class="hint preview">
      {{ preview.count ? t('admin.rule_preview', { n: tp(preview.count, 'units.tracks') }) : t('admin.rule_preview_none') }}<template v-if="preview.sample.length">: {{ preview.sample.map((s) => (s.performer ? s.performer + ' — ' : '') + s.title).join(', ') }}<template v-if="preview.count > preview.sample.length">…</template></template>
    </p>
    <div v-if="rules.length" class="rule-list">
      <div v-for="r in rules" :key="r.id" class="rule-chip">
        <span class="faint small">{{ r.field === 'performer' ? t('admin.rule_performer') : t('admin.rule_title') }} · {{ r.mode === 'exact' ? '=' : '∋' }}</span>
        <b class="ellipsis">{{ r.pattern }}</b>
        <span class="badge hidden">{{ num(r.hidden_count) }}</span>
        <button class="x" :aria-label="t('common.delete')" @click="removeRule(r)"><Icon name="close" :size="14" /></button>
      </div>
    </div>
  </section>

  <!-- ===== список треков ===== -->
  <div class="search-box">
    <Icon name="search" :size="18" class="faint" />
    <input v-model="q" type="search" maxlength="100" :placeholder="t('admin.search_tracks')" />
  </div>
  <div class="card list-card">
    <div v-for="tr in items" :key="tr.id" class="row-item" :class="{ dim: tr.hidden }">
      <Cover :track="tr" radius="8px" class="mini-cover" />
      <div class="grow">
        <div class="ellipsis r-title">{{ tr.title }}</div>
        <div class="ellipsis r-sub">{{ artist(tr) }} · {{ duration(tr.duration) }} · ▶ {{ compact(tr.plays) }} · {{ bytes(tr.file_size) }}</div>
      </div>
      <button class="icon-btn" :aria-label="tr.hidden ? t('admin.show') : t('admin.hide')" @click="toggleHidden(tr)">
        <Icon :name="tr.hidden ? 'eye-off' : 'eye'" :size="20" />
      </button>
    </div>
    <p v-if="!loading && !items.length" class="muted pad">{{ t('common.nothing_found') }}</p>
    <InfiniteLoader v-if="items.length" :disabled="loading || next == null" @load="load(false)" />
  </div>

  <!-- ===== опасная зона ===== -->
  <section class="card card-pad danger-zone">
    <div class="head-row">
      <span class="h-icon danger"><Icon name="trash" :size="19" /></span>
      <div class="grow">
        <b>{{ t('admin.clear_title') }}</b>
        <p class="r-sub">{{ t('admin.clear_desc') }}</p>
      </div>
    </div>
    <label class="switch-row">
      <span>{{ t('admin.clear_skip_history') }}</span>
      <input v-model="skipHistory" type="checkbox" />
      <span class="switch" />
    </label>
    <button class="btn danger-btn" :disabled="clearing" @click="clearAll">
      <span v-if="clearing" class="spinner" /><Icon v-else name="trash" :size="18" />{{ t('admin.clear_button') }}
    </button>
  </section>
</template>

<style scoped>
.rules, .danger-zone { display: grid; gap: 10px; margin-bottom: 14px; }
.danger-zone { margin: 14px 0 0; border-color: rgba(255, 92, 108, 0.3); background: rgba(255, 92, 108, 0.05); }
.head-row { display: flex; gap: 12px; align-items: center; }
.head-row b { font-size: 15.5px; }
.h-icon { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; flex-shrink: 0; color: var(--accent); background: rgb(var(--accent-rgb) / 0.14); }
.h-icon.danger { color: var(--danger); background: rgba(255, 92, 108, 0.14); }
.seg.two { grid-template-columns: 1fr 1fr; }
.rule-row { display: flex; gap: 8px; }
.rule-row .input { flex: 1; min-width: 0; }
.rule-row .btn { height: 44px; padding: 0 16px; }
.preview { margin-top: -2px; }
.rule-list { display: flex; flex-wrap: wrap; gap: 6px; }
.rule-chip {
  display: inline-flex; align-items: center; gap: 6px; max-width: 100%; height: 32px; padding: 0 4px 0 10px;
  border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); font-size: 13px;
}
.rule-chip b { font-weight: 600; max-width: 140px; }
.small { font-size: 11px; }
.x { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; color: var(--text-2); background: rgba(255, 255, 255, 0.06); }
.search-box {
  display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 14px; margin-bottom: 12px;
  border-radius: 12px; background: var(--surface); border: 1px solid var(--border);
}
.search-box input { flex: 1; min-width: 0; background: transparent; border: 0; outline: 0; color: var(--text); font: inherit; }
.switch-row { font-size: 14px; }
.danger-btn { width: 100%; color: #fff; background: rgba(255, 92, 108, 0.85); }
</style>
