<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../../lib/api'
import { dateTime, num, until } from '../../lib/format'
import { errorText, t } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useUi } from '../../stores/ui'
import AdCard from '../AdCard.vue'
import Icon from '../Icon.vue'

const LIMITS = { title: 40, text: 140, button: 24 }
// Варианты «показать через» и «скрыть через» (в секундах)
const START = [['now', 0], ['h1', 3600], ['h3', 3 * 3600], ['d1', 86400], ['custom', null]]
const STOP = [['never', 0], ['h1', 3600], ['h6', 6 * 3600], ['d1', 86400], ['d3', 3 * 86400], ['d7', 7 * 86400], ['custom', null]]

const ui = useUi()
const items = ref(null)
const editing = ref(null) // null | 'new' | id
const saving = ref(false)
const error = ref('')
const form = reactive({})

function reset(ad = null) {
  Object.assign(form, {
    placement: ad?.placement || 'home',
    title: ad?.title || '',
    text: ad?.text || '',
    use_button: !!ad?.button_url,
    button_text: ad?.button_text || '',
    button_url: ad?.button_url || '',
    is_active: ad ? ad.is_active : true,
    start: ad?.show_from ? 'custom' : 'now',
    stop: ad?.show_until ? 'custom' : 'never',
    start_at: toLocal(ad?.show_from),
    stop_at: toLocal(ad?.show_until),
  })
  error.value = ''
}
function toLocal(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const fromLocal = (s) => (s ? Math.floor(new Date(s).getTime() / 1000) : null)

async function load() {
  try { items.value = (await api.admin.ads()).items } catch (e) { ui.toast(errorText(e)) }
}

const urlOk = computed(() => !form.use_button || /^https:\/\/[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test((form.button_url || '').trim()))
const valid = computed(() =>
  form.title?.trim() && form.title.length <= LIMITS.title && (form.text || '').length <= LIMITS.text &&
  (!form.use_button || (form.button_text.trim() && form.button_text.length <= LIMITS.button && urlOk.value)) &&
  (form.start !== 'custom' || form.start_at) && (form.stop !== 'custom' || form.stop_at))
const preview = computed(() => ({
  title: form.title || t('admin.ad_title_ph'),
  text: form.text,
  button_text: form.use_button ? form.button_text || t('admin.ad_button_ph') : null,
  button_url: form.use_button ? 'https://' : null,
}))

function times() {
  const now = Math.floor(Date.now() / 1000)
  const startOpt = START.find(([k]) => k === form.start)
  let showFrom = form.start === 'custom' ? fromLocal(form.start_at) : startOpt[1] ? now + startOpt[1] : null
  const stopOpt = STOP.find(([k]) => k === form.stop)
  let showUntil = form.stop === 'custom' ? fromLocal(form.stop_at) : stopOpt[1] ? (showFrom || now) + stopOpt[1] : null
  return { show_from: showFrom, show_until: showUntil }
}

async function save() {
  if (!valid.value || saving.value) return
  saving.value = true
  error.value = ''
  const body = {
    placement: form.placement,
    title: form.title,
    text: form.text,
    button_text: form.use_button ? form.button_text : null,
    button_url: form.use_button ? form.button_url.trim() : null,
    is_active: form.is_active,
    ...times(),
  }
  try {
    if (editing.value === 'new') await api.admin.createAd(body)
    else await api.admin.updateAd(editing.value, body)
    haptic.success()
    ui.toast(t('admin.ad_saved'))
    editing.value = null
    await load()
  } catch (e) { error.value = errorText(e); haptic.error() } finally { saving.value = false }
}

function startEdit(ad) { reset(ad); editing.value = ad ? ad.id : 'new'; window.scrollTo({ top: 0, behavior: 'smooth' }) }

async function toggle(ad) {
  haptic.tap()
  try {
    await api.admin.updateAd(ad.id, { ...ad, is_active: !ad.is_active })
    await load()
  } catch (e) { ui.toast(errorText(e)) }
}
async function remove(ad) {
  if (!(await confirmDialog(t('admin.ad_delete_confirm', { title: ad.title })))) return
  try { await api.admin.deleteAd(ad.id); haptic.success(); await load() } catch (e) { ui.toast(errorText(e)) }
}
const ctr = (ad) => (ad.impressions ? ((ad.clicks / ad.impressions) * 100).toFixed(1) + '%' : '—')
function stateLine(ad) {
  if (ad.state === 'scheduled') return t('admin.ad_starts', { when: until(ad.show_from) })
  if (ad.state === 'active' && ad.show_until) return t('admin.ad_ends', { when: until(ad.show_until) })
  if (ad.state === 'expired') return t('admin.ad_ended', { when: dateTime(ad.show_until) })
  return ''
}

onMounted(load)
</script>

<template>
  <!-- ======== редактор -->
  <section v-if="editing" class="card card-pad editor">
    <div class="ed-head">
      <h3>{{ editing === 'new' ? t('admin.ad_new') : t('admin.ad_edit') }}</h3>
      <button class="icon-btn" :aria-label="t('common.close')" @click="editing = null"><Icon name="close" :size="20" /></button>
    </div>

    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_preview') }}</span></div>
      <AdCard :ad="preview" />
    </div>

    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_placement') }}</span></div>
      <div class="seg">
        <button type="button" :class="{ on: form.placement === 'home' }" @click="form.placement = 'home'">{{ t('tabs.home') }}</button>
        <button type="button" :class="{ on: form.placement === 'library' }" @click="form.placement = 'library'">{{ t('library.title') }}</button>
      </div>
      <span class="hint">{{ form.placement === 'home' ? t('admin.ad_place_home') : t('admin.ad_place_library') }}</span>
    </div>

    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_title') }}</span><small :class="{ over: form.title.length > LIMITS.title }">{{ form.title.length }}/{{ LIMITS.title }}</small></div>
      <input v-model="form.title" class="input" :maxlength="LIMITS.title" :placeholder="t('admin.ad_title_ph')" />
    </div>
    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_text') }}</span><small :class="{ over: form.text.length > LIMITS.text }">{{ form.text.length }}/{{ LIMITS.text }}</small></div>
      <textarea v-model="form.text" class="input short" :maxlength="LIMITS.text" rows="2" :placeholder="t('admin.ad_text_ph')" />
    </div>

    <label class="switch-row">
      <span>{{ t('admin.ad_with_button') }}</span>
      <input v-model="form.use_button" type="checkbox" />
      <span class="switch" />
    </label>
    <div v-if="form.use_button" class="two">
      <input v-model="form.button_text" class="input" :maxlength="LIMITS.button" :placeholder="t('admin.ad_button_text')" />
      <input v-model="form.button_url" class="input" :class="{ invalid: form.button_url && !urlOk }" maxlength="512" inputmode="url" placeholder="https://" />
    </div>

    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_show') }}</span></div>
      <select v-model="form.start" class="input">
        <option v-for="[k] in START" :key="k" :value="k">{{ t(`admin.ad_start_${k}`) }}</option>
      </select>
      <input v-if="form.start === 'custom'" v-model="form.start_at" type="datetime-local" class="input" />
    </div>
    <div class="field">
      <div class="field-label"><span>{{ t('admin.ad_hide') }}</span></div>
      <select v-model="form.stop" class="input">
        <option v-for="[k] in STOP" :key="k" :value="k">{{ t(`admin.ad_stop_${k}`) }}</option>
      </select>
      <input v-if="form.stop === 'custom'" v-model="form.stop_at" type="datetime-local" class="input" />
    </div>

    <label class="switch-row">
      <span>{{ t('admin.ad_active') }}</span>
      <input v-model="form.is_active" type="checkbox" />
      <span class="switch" />
    </label>

    <p v-if="error" class="err-text">{{ error }}</p>
    <div class="btn-row">
      <button class="btn" @click="editing = null">{{ t('common.cancel') }}</button>
      <button class="btn btn-primary" :disabled="!valid || saving" @click="save"><Icon name="check" :size="18" />{{ t('common.save') }}</button>
    </div>
  </section>

  <button v-else class="btn btn-primary new" @click="startEdit(null)"><Icon name="plus" :size="18" />{{ t('admin.ad_create') }}</button>

  <!-- ======== список -->
  <div v-if="items && !items.length && !editing" class="empty">
    <div class="empty-icon"><Icon name="ad" /></div>
    <p>{{ t('admin.ad_empty') }}</p>
  </div>
  <div class="ads">
    <article v-for="ad in items || []" :key="ad.id" class="card ad-item" :class="{ off: ad.state !== 'active' }">
      <div class="ad-meta">
        <span class="badge" :class="ad.state">{{ t(`admin.ad_state_${ad.state}`) }}</span>
        <span class="faint place">{{ ad.placement === 'home' ? t('admin.ad_place_home') : t('admin.ad_place_library') }}</span>
        <span class="faint tnum stat">👁 {{ num(ad.impressions) }} · 👆 {{ num(ad.clicks) }} · CTR {{ ctr(ad) }}</span>
      </div>
      <AdCard :ad="ad" />
      <p v-if="stateLine(ad)" class="state-line faint">{{ stateLine(ad) }}</p>
      <div class="ad-actions">
        <button @click="startEdit(ad)"><Icon name="edit" :size="16" />{{ t('common.edit') }}</button>
        <button @click="toggle(ad)"><Icon :name="ad.is_active ? 'eye-off' : 'eye'" :size="16" />{{ ad.is_active ? t('admin.hide') : t('admin.show') }}</button>
        <button class="danger" @click="remove(ad)"><Icon name="trash" :size="16" />{{ t('common.delete') }}</button>
      </div>
    </article>
  </div>
</template>

<style scoped>
.new { width: 100%; margin-bottom: 14px; }
.editor { margin-bottom: 16px; }
.ed-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.ed-head h3 { font-size: 17px; font-weight: 700; }
textarea.input.short { min-height: 64px; }
.two { display: grid; gap: 8px; margin: 2px 0 14px; }
.switch-row { margin-bottom: 12px; font-size: 14.5px; }
.ads { display: grid; gap: 12px; }
.ad-item { padding: 12px; display: grid; gap: 10px; }
.ad-item.off :deep(.ad) { opacity: 0.6; }
.ad-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.stat { margin-left: auto; }
.state-line { font-size: 12.5px; margin-top: -4px; }
.ad-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.ad-actions button {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 34px;
  border-radius: 10px; font-size: 13px; font-weight: 600; color: var(--text-2);
  background: var(--surface); border: 1px solid var(--border);
}
.ad-actions .danger { color: var(--danger); }
</style>
