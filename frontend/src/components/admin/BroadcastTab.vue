<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../../lib/api'
import { dateTime, num } from '../../lib/format'
import { errorText, t } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useUi } from '../../stores/ui'
import Icon from '../Icon.vue'

const TEXT_MAX = 3500
const ui = useUi()
const form = reactive({ text: '', audience: 'all', with_app_button: true, use_button: false, button_text: '', button_url: '' })
const info = ref(null)
const busy = ref(false)
const error = ref('')
let poll = null
let alive = true // после ухода с вкладки опрос не продолжается

const length = computed(() => form.text.length)
const urlOk = computed(() => !form.use_button || /^https:\/\/[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(form.button_url.trim()))
const valid = computed(() => form.text.trim() && length.value <= TEXT_MAX && (!form.use_button || (form.button_text.trim() && urlOk.value)))
const current = computed(() => info.value?.items?.find((b) => b.status === 'running' || b.status === 'queued'))
const audienceSize = computed(() => info.value?.audience?.[form.audience] ?? 0)

function payload() {
  return {
    text: form.text,
    audience: form.audience,
    with_app_button: form.with_app_button,
    button_text: form.use_button ? form.button_text : null,
    button_url: form.use_button ? form.button_url.trim() : null,
  }
}

async function load() {
  try {
    info.value = await api.admin.broadcasts()
    clearTimeout(poll)
    if (alive && info.value.running) poll = setTimeout(load, 2000)
  } catch (e) { error.value = errorText(e) }
}

async function test() {
  if (!valid.value) return
  busy.value = true
  error.value = ''
  try {
    const { result } = await api.admin.broadcastTest(payload())
    if (result === 'ok') { haptic.success(); ui.toast(t('admin.bc_test_sent')) }
    else { haptic.error(); error.value = t('admin.bc_test_failed') }
  } catch (e) { error.value = errorText(e) } finally { busy.value = false }
}

async function send() {
  if (!valid.value) return
  if (!(await confirmDialog(t('admin.bc_confirm', { n: num(audienceSize.value) })))) return
  busy.value = true
  error.value = ''
  try {
    await api.admin.broadcast(payload())
    haptic.success()
    ui.toast(t('admin.bc_started'))
    form.text = ''
    await load()
  } catch (e) { error.value = errorText(e) } finally { busy.value = false }
}

async function cancel() {
  if (!(await confirmDialog(t('admin.bc_cancel_confirm')))) return
  try { await api.admin.cancelBroadcast(); clearTimeout(poll); poll = setTimeout(load, 500) } catch (e) { ui.toast(errorText(e)) }
}

function wrap(tag) {
  const el = document.getElementById('bc-text')
  if (!el) return
  const [a, b] = [el.selectionStart, el.selectionEnd]
  const sel = form.text.slice(a, b) || t('admin.bc_sample')
  form.text = `${form.text.slice(0, a)}<${tag}>${sel}</${tag}>${form.text.slice(b)}`
}

onMounted(load)
onBeforeUnmount(() => { alive = false; clearTimeout(poll) })
</script>

<template>
  <!-- Текущая рассылка -->
  <section v-if="current" class="card card-pad running">
    <div class="run-head">
      <span class="spinner" />
      <b>{{ t('admin.bc_running') }}</b>
      <span class="badge running">{{ num(current.sent + current.failed) }} / {{ num(current.total) }}</span>
    </div>
    <div class="progress"><i :style="{ width: `${current.total ? ((current.sent + current.failed) / current.total) * 100 : 0}%` }" /></div>
    <div class="run-foot">
      <span class="muted">{{ t('admin.bc_stats', { s: num(current.sent), f: num(current.failed) }) }}</span>
      <button class="link-danger" @click="cancel">{{ t('admin.bc_cancel') }}</button>
    </div>
  </section>

  <section class="card card-pad">
    <h3 class="title">{{ t('admin.bc_new') }}</h3>
    <p class="section-sub">{{ t('admin.bc_desc') }}</p>

    <div class="field">
      <div class="field-label">
        <span>{{ t('admin.bc_text') }}</span>
        <small class="tnum" :class="{ over: length > TEXT_MAX }">{{ length }}/{{ TEXT_MAX }}</small>
      </div>
      <div class="fmt">
        <button type="button" @click="wrap('b')"><b>B</b></button>
        <button type="button" @click="wrap('i')"><i>I</i></button>
        <button type="button" @click="wrap('u')"><u>U</u></button>
        <button type="button" @click="wrap('s')"><s>S</s></button>
        <button type="button" @click="wrap('code')"><code>{}</code></button>
      </div>
      <textarea id="bc-text" v-model="form.text" class="input" rows="6" :placeholder="t('admin.bc_placeholder')" />
      <span class="hint">{{ t('admin.bc_html_hint') }}</span>
    </div>

    <div class="field">
      <div class="field-label"><span>{{ t('admin.bc_audience') }}</span></div>
      <div class="seg">
        <button v-for="a in ['all', 'ru', 'en']" :key="a" type="button" :class="{ on: form.audience === a }" @click="form.audience = a">
          {{ t(`admin.bc_aud_${a}`) }} · {{ num(info?.audience?.[a] ?? 0) }}
        </button>
      </div>
    </div>

    <label class="switch-row">
      <span>{{ t('admin.bc_app_button') }}</span>
      <input v-model="form.with_app_button" type="checkbox" />
      <span class="switch" />
    </label>
    <label class="switch-row">
      <span>{{ t('admin.bc_link_button') }}</span>
      <input v-model="form.use_button" type="checkbox" />
      <span class="switch" />
    </label>
    <div v-if="form.use_button" class="link-fields">
      <input v-model="form.button_text" class="input" maxlength="24" :placeholder="t('admin.ad_button_text')" />
      <input v-model="form.button_url" class="input" :class="{ invalid: form.button_url && !urlOk }" maxlength="512" inputmode="url" placeholder="https://" />
    </div>

    <p v-if="error" class="err-text">{{ error }}</p>
    <div class="btn-row actions">
      <button class="btn" :disabled="!valid || busy" @click="test"><Icon name="send" :size="17" />{{ t('admin.bc_test') }}</button>
      <button class="btn btn-primary" :disabled="!valid || busy || !!current || !audienceSize" @click="send"><Icon name="megaphone" :size="18" />{{ t('admin.bc_send') }}</button>
    </div>
  </section>

  <section v-if="info?.items?.length" class="section">
    <div class="section-head"><h2 class="section-title">{{ t('admin.bc_history') }}</h2></div>
    <div class="card list-card">
      <div v-for="b in info.items" :key="b.id" class="row-item">
        <div class="grow">
          <div class="ellipsis r-title">{{ b.text.replace(/<[^>]+>/g, '') }}</div>
          <div class="r-sub">{{ dateTime(b.created_at) }} · {{ t(`admin.bc_aud_${b.audience}`) }} · {{ t('admin.bc_stats', { s: num(b.sent), f: num(b.failed) }) }}</div>
        </div>
        <span class="badge" :class="b.status">{{ t(`admin.bc_status_${b.status}`) }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.title { font-size: 17px; font-weight: 700; margin-bottom: 10px; }
.fmt { display: flex; gap: 6px; }
.fmt button { width: 36px; height: 30px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); font-size: 14px; }
.fmt code { font-size: 12px; }
.link-fields { display: grid; gap: 8px; margin: 4px 0 8px; }
.actions { margin-top: 14px; }
.running { margin-bottom: 12px; display: grid; gap: 10px; }
.run-head { display: flex; align-items: center; gap: 10px; }
.run-head b { flex: 1; }
.run-foot { display: flex; justify-content: space-between; font-size: 13px; }
.link-danger { color: var(--danger); font-weight: 600; font-size: 13.5px; }
.switch-row { margin-bottom: 10px; font-size: 14.5px; }
</style>
