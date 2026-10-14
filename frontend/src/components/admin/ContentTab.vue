<script setup>
// Импорт собственного контента с YouTube Music → Telegram-канал → приложение
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import { duration, num } from '../../lib/format'
import { errorText, t, tp } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { validateAlbumName } from '../../lib/validate'
import { useAlbums } from '../../stores/albums'
import { useLibrary } from '../../stores/library'
import { useSession } from '../../stores/session'
import { useUi } from '../../stores/ui'
import Icon from '../Icon.vue'

const ui = useUi()
const session = useSession()
const albums = useAlbums()
const lib = useLibrary()

const status = ref(null)
const url = ref('')
const loading = ref(false)
const error = ref('')
const res = ref(null) // { rid, kind, title, artist, thumbnail, total, page, pages, items }
const jobs = ref([])
const opts = reactive({ create_album: false, album_name: '', caption: '' })
let poll = null
let alive = true // после ухода с вкладки опрос не продолжается

const albumCheck = computed(() => validateAlbumName(opts.album_name, {
  max: session.config.album_name_max || 32, punct: session.config.album_punct,
}))
const canStart = computed(() => res.value && (!opts.create_album || !albumCheck.value.error))
const running = computed(() => jobs.value.some((j) => j.status === 'queued' || j.status === 'running'))

async function loadStatus() {
  try {
    status.value = await api.admin.content.status()
    jobs.value = status.value.jobs
    schedule()
  } catch (e) { error.value = errorText(e) }
}
async function refreshJobs() {
  try {
    const before = jobs.value.filter((j) => j.status === 'running' || j.status === 'queued').length
    jobs.value = (await api.admin.content.jobs()).items
    const after = jobs.value.filter((j) => j.status === 'running' || j.status === 'queued').length
    if (before && !after) {
      // задания завершились — обновляем данные приложения и отметки «в канале»
      lib.loadHome(true).catch(() => {})
      albums.bump()
      if (res.value) goto(res.value.page, true)
    }
  } catch {}
  schedule()
}
function schedule() {
  clearTimeout(poll)
  if (alive && running.value) poll = setTimeout(refreshJobs, 2000)
}

async function resolve() {
  if (!url.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  res.value = null
  try {
    res.value = await api.admin.content.resolve(url.value.trim())
    opts.album_name = res.value.kind === 'playlist' ? res.value.title.slice(0, 32) : ''
    opts.create_album = false
    haptic.success()
  } catch (e) {
    error.value = errorText(e)
    haptic.error()
  } finally { loading.value = false }
}

async function goto(page, silent = false) {
  if (!res.value) return
  try {
    res.value = await api.admin.content.page(res.value.rid, page)
  } catch (e) {
    if (!silent) error.value = errorText(e)
  }
}

async function start(scope, videoId = null) {
  const count = scope === 'track' ? 1 : scope === 'page' ? res.value.items.length : res.value.total
  if (count > 1 && !(await confirmDialog(t('content.confirm', { n: count })))) return
  error.value = ''
  try {
    await api.admin.content.start({
      rid: res.value.rid, scope, page: res.value.page, video_id: videoId,
      create_album: scope !== 'track' && opts.create_album,
      album_name: opts.create_album ? albumCheck.value.value : null,
      caption: opts.caption,
    })
    haptic.success()
    ui.toast(t('content.queued', { n: count }))
    await refreshJobs()
    goto(res.value.page, true)
  } catch (e) {
    error.value = errorText(e, { n: albums.limit })
    haptic.error()
  }
}

async function cancel(job) {
  try { await api.admin.content.cancel(job.id); clearTimeout(poll); poll = setTimeout(refreshJobs, 400) } catch (e) { ui.toast(errorText(e)) }
}
async function paste() {
  try { url.value = (await navigator.clipboard.readText()).trim() } catch {}
}
const currentItem = (job) => job.items.find((it) => it.status === 'downloading' || it.status === 'uploading')

watch(() => opts.create_album, (v) => { if (v && !opts.album_name && res.value) opts.album_name = res.value.title.slice(0, 32) })
onMounted(loadStatus)
onBeforeUnmount(() => { alive = false; clearTimeout(poll) })
</script>

<template>
  <section class="card card-pad intro">
    <div class="intro-head">
      <span class="yt-icon"><Icon name="download" :size="20" /></span>
      <div class="grow">
        <b>{{ t('content.title') }}</b>
        <p class="r-sub">{{ t('content.desc') }}</p>
      </div>
    </div>

    <p v-if="status && !status.available" class="warn-box">{{ t('content.not_installed') }}</p>
    <p v-else-if="status && !status.js_runtime" class="warn-box">{{ t('content.no_js') }}</p>

    <form class="url-row" @submit.prevent="resolve">
      <div class="url-input">
        <Icon name="link" :size="18" class="faint" />
        <input v-model="url" type="url" inputmode="url" maxlength="500" placeholder="https://music.youtube.com/…" autocomplete="off" />
        <button v-if="!url" type="button" class="paste" @click="paste">{{ t('content.paste') }}</button>
      </div>
      <button class="btn btn-primary find" :disabled="loading || !url.trim()">
        <span v-if="loading" class="spinner" /><template v-else>{{ t('content.find') }}</template>
      </button>
    </form>
    <p class="hint">{{ t('content.url_hint') }}</p>
    <p v-if="error" class="err-text">{{ error }}</p>
  </section>

  <!-- ===== результат ===== -->
  <section v-if="res" class="card result">
    <header class="res-head">
      <img v-if="res.thumbnail" :src="res.thumbnail" alt="" class="res-art" referrerpolicy="no-referrer" />
      <div class="grow">
        <span class="kind">{{ res.kind === 'playlist' ? t('content.playlist') : t('content.track') }}</span>
        <h3 class="ellipsis">{{ res.title }}</h3>
        <p class="r-sub ellipsis">{{ res.artist }}<template v-if="res.kind === 'playlist'"> · {{ tp(res.total, 'units.tracks') }}</template></p>
      </div>
    </header>

    <div class="items">
      <div v-for="(it, i) in res.items" :key="it.video_id" class="row-item">
        <span class="num tnum">{{ (res.page - 1) * 10 + i + 1 }}</span>
        <img v-if="it.thumbnail" :src="it.thumbnail" alt="" class="it-thumb" loading="lazy" referrerpolicy="no-referrer" />
        <div class="grow">
          <div class="r-title ellipsis">{{ it.title }}</div>
          <div class="r-sub ellipsis">{{ it.artist }}<template v-if="it.duration"> · {{ duration(it.duration) }}</template></div>
        </div>
        <span v-if="it.imported" class="badge done">{{ t('content.in_channel') }}</span>
        <span v-else-if="it.queued" class="badge queued">{{ t('content.in_queue') }}</span>
        <button v-else class="icon-btn dl" :aria-label="t('content.download_one')" @click="start('track', it.video_id)">
          <Icon name="download" :size="19" />
        </button>
      </div>
    </div>

    <nav v-if="res.pages > 1" class="pager">
      <button class="icon-btn" :disabled="res.page <= 1" :aria-label="t('content.prev_page')" @click="goto(res.page - 1)"><Icon name="chevron-left" :size="20" /></button>
      <span class="tnum">{{ t('content.page', { p: res.page, n: res.pages }) }}</span>
      <button class="icon-btn" :disabled="res.page >= res.pages" :aria-label="t('content.next_page')" @click="goto(res.page + 1)"><Icon name="chevron-right" :size="20" /></button>
    </nav>

    <div class="opts">
      <label v-if="res.kind === 'playlist'" class="switch-row">
        <span>{{ t('content.make_album') }}</span>
        <input v-model="opts.create_album" type="checkbox" />
        <span class="switch" />
      </label>
      <div v-if="opts.create_album" class="field">
        <div class="field-label"><span>{{ t('album.name') }}</span><small :class="{ over: albumCheck.length > 32 }">{{ albumCheck.length }}/32</small></div>
        <input v-model="opts.album_name" class="input" :class="{ invalid: albumCheck.error }" maxlength="40" />
        <span v-if="albumCheck.error" class="err-text">{{ errorText({ message: albumCheck.error }, { max: 32 }) }}</span>
      </div>
      <div class="field">
        <div class="field-label"><span>{{ t('content.caption') }}</span></div>
        <input v-model="opts.caption" class="input" maxlength="300" :placeholder="t('content.caption_ph')" />
      </div>
    </div>

    <div class="btn-row actions">
      <template v-if="res.kind === 'playlist'">
        <button class="btn" :disabled="!canStart" @click="start('page')"><Icon name="download" :size="17" />{{ t('content.dl_page', { n: res.items.length }) }}</button>
        <button class="btn btn-primary" :disabled="!canStart" @click="start('all')"><Icon name="download" :size="17" />{{ t('content.dl_all', { n: num(res.total) }) }}</button>
      </template>
      <button v-else class="btn btn-primary full" :disabled="!canStart || res.items[0]?.imported" @click="start('track', res.items[0].video_id)">
        <Icon name="download" :size="17" />{{ t('content.dl_track') }}
      </button>
    </div>
  </section>

  <!-- ===== задания ===== -->
  <section v-if="jobs.length" class="section">
    <div class="section-head"><h2 class="section-title">{{ t('content.jobs') }}</h2></div>
    <div class="jobs">
      <article v-for="job in jobs" :key="job.id" class="card card-pad job">
        <div class="job-head">
          <span v-if="job.status === 'running'" class="spinner" />
          <b class="ellipsis grow">{{ job.title }}</b>
          <span class="badge" :class="job.status">{{ t(`content.job_${job.status}`) }}</span>
        </div>
        <div class="progress"><i :style="{ width: `${job.total ? (job.processed / job.total) * 100 : 0}%` }" /></div>
        <div class="job-foot">
          <span class="muted tnum">
            {{ job.processed }}/{{ job.total }}
            · ✓ {{ job.counts.done || 0 }}
            <template v-if="job.counts.skipped"> · ↷ {{ job.counts.skipped }}</template>
            <template v-if="job.counts.error"> · ⚠ {{ job.counts.error }}</template>
          </span>
          <button v-if="job.status === 'running' || job.status === 'queued'" class="link-danger" @click="cancel(job)">{{ t('common.cancel') }}</button>
        </div>
        <p v-if="currentItem(job)" class="now ellipsis">
          {{ t(`content.item_${currentItem(job).status}`) }}: {{ currentItem(job).title }}
        </p>
        <p v-if="job.album_id" class="now ok">💿 {{ t('content.album_created') }}</p>
        <details v-if="job.counts.error" class="errors">
          <summary>{{ t('content.errors') }}</summary>
          <p v-for="it in job.items.filter((x) => x.status === 'error')" :key="it.video_id" class="ellipsis">
            {{ it.title }} — {{ errorText({ message: it.error }) }}
          </p>
        </details>
      </article>
    </div>
  </section>
</template>

<style scoped>
.intro-head { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.yt-icon { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; color: #ff5c6c; background: rgba(255, 92, 108, 0.14); flex-shrink: 0; }
.intro-head b { font-size: 16px; }
.warn-box { font-size: 12.5px; color: #ffd27a; background: rgba(255, 196, 0, 0.08); border: 1px solid rgba(255, 196, 0, 0.25); border-radius: 12px; padding: 10px 12px; margin-bottom: 12px; line-height: 1.4; }
.url-row { display: flex; gap: 8px; }
.url-input { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; height: 46px; padding: 0 6px 0 12px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--border); }
.url-input:focus-within { border-color: rgb(var(--accent-rgb) / 0.6); }
.url-input input { flex: 1; min-width: 0; background: transparent; border: 0; outline: 0; color: var(--text); font: inherit; font-size: 14.5px; }
.paste { font-size: 12.5px; font-weight: 600; color: var(--accent); padding: 6px 8px; }
.find { height: 46px; padding: 0 16px; min-width: 82px; }
.url-row + .hint { margin-top: 8px; display: block; }

.result { margin-top: 12px; padding: 14px; }
.res-head { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.res-art { width: 64px; height: 64px; border-radius: 14px; object-fit: cover; flex-shrink: 0; background: var(--surface-2); }
.kind { font-size: 10.5px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }
.res-head h3 { font-size: 17px; font-weight: 700; }
.items { border-top: 1px solid var(--border); }
.num { width: 20px; text-align: center; font-size: 12px; color: var(--text-3); flex-shrink: 0; }
.it-thumb { width: 40px; height: 40px; border-radius: 8px; object-fit: cover; flex-shrink: 0; background: var(--surface-2); }
.dl { width: 36px; height: 36px; color: var(--text-2); }
.pager { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 8px 0 2px; font-size: 13.5px; color: var(--text-2); }
.pager .icon-btn:disabled { opacity: 0.3; }
.opts { margin-top: 10px; padding-top: 12px; border-top: 1px solid var(--border); }
.opts .switch-row { margin-bottom: 12px; font-size: 14.5px; }
.actions { margin-top: 14px; }
.actions .btn { white-space: nowrap; font-size: 14px; padding: 0 10px; }
.full { grid-column: 1 / -1; }

.jobs { display: grid; gap: 10px; }
.job { display: grid; gap: 8px; }
.job-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.job-foot { display: flex; justify-content: space-between; font-size: 12.5px; }
.link-danger { color: var(--danger); font-weight: 600; font-size: 13px; }
.now { font-size: 12.5px; color: var(--text-2); }
.now.ok { color: var(--success); }
.errors { font-size: 12.5px; color: var(--text-2); }
.errors summary { cursor: pointer; color: var(--danger); }
.errors p { margin-top: 4px; }
</style>
