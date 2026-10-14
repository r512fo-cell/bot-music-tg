<script setup>
// Заявки слушателей: прослушать → опубликовать в канал или отклонить
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, mediaUrl } from '../../lib/api'
import { bytes, duration, initials, num, relative } from '../../lib/format'
import { errorText, t, tp } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useLibrary } from '../../stores/library'
import { usePlayer } from '../../stores/player'
import { useUi } from '../../stores/ui'
import Icon from '../Icon.vue'
import InfiniteLoader from '../InfiniteLoader.vue'

const emit = defineEmits(['count'])
const ui = useUi()
const lib = useLibrary()
const player = usePlayer()

const status = ref('pending')
const tag = ref(null)
const q = ref('')
const items = ref(null)
const counts = ref({ pending: 0, approved: 0, rejected: 0, tags: [] })
const next = ref(0)
const loading = ref(false)
const excluded = reactive({}) // fileId -> true
const rejecting = ref(null) // id заявки с открытым полем причины
const reason = ref('')
const busy = ref(null)
let timer = null

// ---- предпрослушивание: отдельный <audio>, основной плеер ставим на паузу
const audio = new Audio()
audio.preload = 'none'
const playingId = ref(null)
const loadingId = ref(null)
const progress = ref(0)
audio.addEventListener('timeupdate', () => { progress.value = audio.duration ? audio.currentTime / audio.duration : 0 })
audio.addEventListener('playing', () => { loadingId.value = null })
audio.addEventListener('ended', () => { playingId.value = null })
audio.addEventListener('error', () => {
  if (playingId.value) ui.toast(t('subs.play_error'))
  playingId.value = null
  loadingId.value = null
})

let unmounted = false
async function preview(f) {
  if (playingId.value === f.id) { audio.pause(); playingId.value = null; return }
  if (player.playing) player.toggle()
  playingId.value = f.id
  loadingId.value = f.id
  progress.value = 0
  const url = await mediaUrl(`/api/admin/submissions/files/${f.id}/stream`)
  // пока получали ссылку, могли нажать другой трек или уйти с вкладки
  if (playingId.value !== f.id || unmounted) return
  audio.src = url
  audio.play().catch(() => { playingId.value = null; loadingId.value = null })
}
function seek(e, f) {
  if (playingId.value !== f.id || !audio.duration) return
  const r = e.currentTarget.getBoundingClientRect()
  audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration
}

async function load(reset) {
  if (loading.value || (!reset && next.value == null)) return
  loading.value = true
  try {
    const res = await api.admin.submissions({
      status: status.value, tag: tag.value, q: q.value.trim(), offset: reset ? 0 : next.value, limit: 15,
    })
    items.value = reset ? res.items : [...(items.value || []), ...res.items]
    next.value = res.next_offset
    counts.value = res.counts
    emit('count', res.counts.pending)
  } catch (e) { ui.toast(errorText(e)) } finally { loading.value = false }
}

async function approve(sub) {
  const keep = sub.files.filter((f) => !excluded[f.id])
  if (!keep.length) { ui.toast(t('subs.none_selected')); return }
  if (!(await confirmDialog(t('subs.approve_confirm', { n: keep.length })))) return
  busy.value = sub.id
  audio.pause(); playingId.value = null
  try {
    const res = await api.admin.approve(sub.id, sub.files.filter((f) => excluded[f.id]).map((f) => f.id))
    haptic.success()
    ui.toast(res.failed ? t('subs.approved_partial', { n: res.published, f: res.failed }) : t('subs.approved', { n: res.published }))
    lib.loadHome(true).catch(() => {})
    await load(true)
  } catch (e) { ui.toast(errorText(e)); haptic.error() } finally { busy.value = null }
}

async function reject(sub) {
  busy.value = sub.id
  audio.pause(); playingId.value = null
  try {
    await api.admin.reject(sub.id, reason.value.trim())
    haptic.success()
    ui.toast(t('subs.rejected'))
    rejecting.value = null
    reason.value = ''
    await load(true)
  } catch (e) { ui.toast(errorText(e)); haptic.error() } finally { busy.value = null }
}

const uname = (u) => [u.first_name, u.last_name].filter(Boolean).join(' ') || `id${u.id}`
function setStatus(s) { status.value = s; tag.value = null; haptic.select() }

watch([status, tag], () => load(true))
watch(q, () => { clearTimeout(timer); timer = setTimeout(() => load(true), 300) })
onMounted(() => load(true))
onBeforeUnmount(() => { unmounted = true; audio.pause(); audio.removeAttribute('src') })
</script>

<template>
  <div class="seg three">
    <button v-for="s in ['pending', 'approved', 'rejected']" :key="s" type="button" :class="{ on: status === s }" @click="setStatus(s)">
      {{ t(`subs.st_${s}`) }} <span class="cnt tnum">{{ num(counts[s] || 0) }}</span>
    </button>
  </div>

  <div class="filters">
    <div class="search-box">
      <Icon name="search" :size="17" class="faint" />
      <input v-model="q" type="search" maxlength="100" :placeholder="t('subs.search')" />
    </div>
    <div v-if="status === 'pending' && counts.tags.length" class="tag-row h-scroll">
      <button class="chip" :class="{ active: !tag }" @click="tag = null">{{ t('common.all') }}</button>
      <button v-for="tg in counts.tags" :key="tg" class="chip" :class="{ active: tag === tg }" @click="tag = tg">#{{ tg }}</button>
    </div>
  </div>

  <div v-if="items && !items.length" class="empty">
    <div class="empty-icon"><Icon name="music" /></div>
    <p>{{ status === 'pending' ? t('subs.empty_pending') : t('common.empty') }}</p>
    <p v-if="status === 'pending'" class="hint">{{ t('subs.how') }}</p>
  </div>

  <div class="subs">
    <article v-for="sub in items || []" :key="sub.id" class="card sub">
      <header class="sub-head">
        <span class="ava">{{ initials(uname(sub.user)) || '?' }}</span>
        <div class="grow">
          <b class="ellipsis">{{ uname(sub.user) }}</b>
          <span class="r-sub ellipsis">
            <template v-if="sub.user.username">@{{ sub.user.username }} · </template>
            {{ relative(sub.status === 'pending' ? sub.submitted_at : sub.decided_at) }}
          </span>
        </div>
        <span class="faint tnum">#{{ sub.id }}</span>
      </header>
      <div v-if="sub.tags.length" class="tags">
        <span v-for="tg in sub.tags" :key="tg" class="tag">#{{ tg }}</span>
      </div>

      <!-- треки заявки -->
      <div v-if="sub.status === 'pending'" class="files">
        <div v-for="f in sub.files" :key="f.id" class="file" :class="{ off: excluded[f.id] }">
          <button class="play" :class="{ on: playingId === f.id }" :aria-label="t('player.play')" @click="preview(f)">
            <span v-if="loadingId === f.id" class="spinner" />
            <Icon v-else :name="playingId === f.id ? 'pause' : 'play'" :size="16" />
          </button>
          <div class="grow">
            <div class="r-title ellipsis">{{ f.title }}</div>
            <div class="r-sub ellipsis">{{ f.performer || t('common.unknown_artist') }} · {{ duration(f.duration) }} · {{ bytes(f.file_size) }}</div>
            <div v-if="playingId === f.id" class="bar" @click="seek($event, f)"><i :style="{ width: `${progress * 100}%` }" /></div>
          </div>
          <label class="pick" :title="t('subs.include')">
            <input type="checkbox" :checked="!excluded[f.id]" @change="excluded[f.id] = !$event.target.checked" />
            <span class="box"><Icon v-if="!excluded[f.id]" name="check" :size="13" /></span>
          </label>
        </div>
      </div>
      <p v-else class="r-sub decided">
        <template v-if="sub.status === 'approved'">✅ {{ t('subs.published', { n: tp(sub.published, 'units.tracks') }) }}</template>
        <template v-else>✖ {{ t('subs.declined') }}<template v-if="sub.reason"> — {{ sub.reason }}</template></template>
      </p>

      <!-- действия -->
      <template v-if="sub.status === 'pending'">
        <div v-if="rejecting === sub.id" class="reject-box">
          <textarea v-model="reason" class="input" rows="2" maxlength="300" :placeholder="t('subs.reason_ph')" />
          <div class="btn-row">
            <button class="btn" @click="rejecting = null">{{ t('common.cancel') }}</button>
            <button class="btn danger-btn" :disabled="busy === sub.id" @click="reject(sub)">{{ t('subs.reject_send') }}</button>
          </div>
        </div>
        <div v-else class="btn-row">
          <button class="btn" :disabled="busy === sub.id" @click="rejecting = sub.id; reason = ''">
            <Icon name="close" :size="17" />{{ t('subs.reject') }}
          </button>
          <button class="btn btn-primary" :disabled="busy === sub.id" @click="approve(sub)">
            <span v-if="busy === sub.id" class="spinner" /><Icon v-else name="send" :size="17" />
            {{ t('subs.approve', { n: sub.files.filter((f) => !excluded[f.id]).length }) }}
          </button>
        </div>
      </template>
    </article>
  </div>
  <InfiniteLoader v-if="items?.length" :disabled="loading || next == null" @load="load(false)" />
</template>

<style scoped>
.seg.three { grid-template-columns: repeat(3, 1fr); }
.cnt { font-size: 11px; color: var(--text-3); margin-left: 2px; }
.filters { display: grid; gap: 8px; margin: 10px 0 12px; }
.search-box {
  display: flex; align-items: center; gap: 10px; height: 42px; padding: 0 14px;
  border-radius: 12px; background: var(--surface); border: 1px solid var(--border);
}
.search-box input { flex: 1; min-width: 0; background: transparent; border: 0; outline: 0; color: var(--text); font: inherit; font-size: 14.5px; }
.tag-row { gap: 6px; }
.tag-row .chip { height: 30px; font-size: 13px; }
.subs { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.sub { padding: 14px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; min-width: 0; overflow: hidden; }
.sub-head { display: flex; align-items: center; gap: 10px; }
.sub-head .grow { display: flex; flex-direction: column; min-width: 0; }
.sub-head b { font-size: 15px; }
.ava { width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0; font-weight: 800; font-size: 13px; background: var(--accent-grad); color: var(--on-accent); }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px; color: var(--accent-light); background: rgb(var(--accent-rgb) / 0.15); }
.files { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; border-top: 1px solid var(--border); padding-top: 6px; }
.file { display: flex; align-items: center; gap: 10px; padding: 6px 0; min-width: 0; transition: opacity 0.2s; }
.file .grow { flex: 1; min-width: 0; }
.file.off { opacity: 0.4; }
.play {
  width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  background: var(--surface-2); color: var(--text); transition: background 0.2s, transform 0.15s var(--ease);
}
.play.on { background: var(--accent-grad); color: var(--on-accent); }
.play:active { transform: scale(0.9); }
.bar { height: 4px; border-radius: 3px; background: var(--surface-3); margin-top: 6px; cursor: pointer; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--accent-grad); }
.pick input { position: absolute; opacity: 0; pointer-events: none; }
.pick { cursor: pointer; }
.box { width: 24px; height: 24px; border-radius: 7px; display: grid; place-items: center; color: #fff; border: 2px solid rgba(255, 255, 255, 0.25); }
.pick input:checked + .box { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.decided { font-size: 13px; }
.sub .btn { white-space: nowrap; font-size: 14px; padding: 0 10px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.sub .btn-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); }
.pick { flex-shrink: 0; }
.reject-box { display: grid; gap: 8px; }
.reject-box textarea { min-height: 64px; }
.danger-btn { color: #fff; background: rgba(255, 92, 108, 0.85); }
.empty .hint { max-width: 300px; }
</style>
