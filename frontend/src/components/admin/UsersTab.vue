<script setup>
import { computed, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import { compact, date, initials, relative } from '../../lib/format'
import { errorText, t } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useUi } from '../../stores/ui'
import Icon from '../Icon.vue'
import InfiniteLoader from '../InfiniteLoader.vue'

const ui = useUi()
const FILTERS = ['all', 'vip', 'banned', 'restricted']
const NAME_MAX = 24
const FLAGS = [
  { key: 'vip', icon: 'star', cls: 'gold' },
  { key: 'banned', icon: 'ban', cls: 'danger' },
  { key: 'no_albums', icon: 'album', cls: 'warn' },
  { key: 'no_uploads', icon: 'upload', cls: 'warn' },
]

const items = ref([])
const next = ref(0)
const loading = ref(false)
const q = ref('')
const filter = ref('all')
let seq = 0

async function load(reset) {
  if (!reset && (loading.value || next.value == null)) return
  const my = ++seq // ответ на устаревший запрос (смена фильтра/поиска) игнорируется
  loading.value = true
  try {
    const res = await api.admin.users({ offset: reset ? 0 : next.value, limit: 30, q: q.value.trim(), filter: filter.value })
    if (my !== seq) return
    items.value = reset ? res.items : [...items.value, ...res.items]
    next.value = res.next_offset
  } catch (e) {
    if (my === seq) ui.toast(errorText(e))
  } finally {
    if (my === seq) loading.value = false
  }
}
let timer = 0
watch(q, () => { clearTimeout(timer); timer = setTimeout(() => load(true), 300) })
watch(filter, () => load(true))
onMounted(() => load(true))
onBeforeUnmount(() => clearTimeout(timer))

const tgName = (u) => [u.first_name, u.last_name].filter(Boolean).join(' ') || `id${u.id}`
const shownName = (u) => u.display_name || tgName(u)

// ---------------------------------------------------------------- карточка пользователя
const open = ref(null) // полные данные пользователя
const form = reactive({ display_name: '', vip: false, banned: false, no_albums: false, no_uploads: false, reason: '', notify: true })
const saving = ref(false)

async function openUser(u) {
  haptic.tap()
  open.value = { ...u, loading: true }
  fill(u)
  try {
    const full = await api.admin.user(u.id)
    if (open.value?.id === u.id) { open.value = full; fill(full) }
  } catch (e) { ui.toast(errorText(e)); open.value = null }
}
function fill(u) {
  Object.assign(form, {
    display_name: u.display_name || '', vip: !!u.vip, banned: !!u.banned,
    no_albums: !!u.no_albums, no_uploads: !!u.no_uploads, reason: '', notify: true,
  })
}
function close() { open.value = null }
onDeactivated(close) // вкладка в KeepAlive: карточку не оставляем открытой

const nameLen = computed(() => form.display_name.trim().length)
const nameError = computed(() => {
  const n = nameLen.value
  if (n === 0) return ''
  if (n < 2) return 'name_short'
  if (n > NAME_MAX) return 'name_long'
  return ''
})
const changes = computed(() => {
  const u = open.value
  if (!u || u.loading) return {}
  const out = {}
  for (const f of FLAGS) if (form[f.key] !== !!u[f.key]) out[f.key] = form[f.key]
  if (form.display_name.trim() !== (u.display_name || '')) out.display_name = form.display_name.trim()
  return out
})
const dirty = computed(() => Object.keys(changes.value).length > 0)

async function save() {
  if (!dirty.value || saving.value || nameError.value) return
  if (changes.value.banned && !(await confirmDialog(t('admin.u_ban_confirm', { name: shownName(open.value) })))) return
  saving.value = true
  try {
    const body = { ...changes.value, notify: form.notify }
    if (form.reason.trim()) body.reason = form.reason.trim()
    const updated = await api.admin.updateUser(open.value.id, body)
    items.value = items.value.map((x) => (x.id === updated.id ? { ...x, ...updated } : x))
    open.value = updated
    fill(updated)
    haptic.success()
    ui.toast(t('admin.u_saved'))
  } catch (e) {
    haptic.error()
    ui.toast(errorText(e))
  } finally { saving.value = false }
}
</script>

<template>
  <div class="users">
    <div class="search">
      <Icon name="search" :size="18" />
      <input v-model="q" type="search" :placeholder="t('admin.u_search')" autocomplete="off" enterkeyhint="search" />
    </div>
    <div class="chips">
      <button v-for="f in FILTERS" :key="f" class="chip" :class="{ on: filter === f }" @click="filter = f; haptic.select()">
        {{ t('admin.u_filter_' + f) }}
      </button>
    </div>

    <div class="card list-card">
      <button v-for="u in items" :key="u.id" class="row-item user-row" @click="openUser(u)">
        <div class="u-ava" :class="{ vip: u.vip, banned: u.banned }">
          <template v-if="initials(shownName(u))">{{ initials(shownName(u)) }}</template>
          <Icon v-else name="user" :size="18" />
        </div>
        <div class="grow">
          <div class="ellipsis r-title">
            {{ shownName(u) }}<span v-if="u.vip" class="star">⭐</span>
            <span v-if="u.lang" class="tag">{{ u.lang.toUpperCase() }}</span>
            <span v-if="u.is_admin" class="tag acc">{{ t('admin.u_admin') }}</span>
            <span v-if="u.banned" class="tag red">{{ t('admin.u_banned') }}</span>
            <span v-else-if="u.no_albums || u.no_uploads" class="tag warn">{{ t('admin.u_limited') }}</span>
            <span v-if="u.blocked" class="tag">{{ t('admin.blocked') }}</span>
          </div>
          <div class="ellipsis r-sub">
            <template v-if="u.username">@{{ u.username }} · </template>{{ t('admin.user_since', { date: date(u.created_at, { day: 'numeric', month: 'short', year: 'numeric' }), seen: relative(u.last_seen_at) }) }}
          </div>
        </div>
        <div class="r-num tnum"><b>{{ compact(u.plays) }}</b><span>{{ t('units.plays_short') }}</span></div>
      </button>
      <div v-if="!loading && !items.length" class="empty-row muted">{{ t('admin.u_empty') }}</div>
      <InfiniteLoader v-if="items.length" :disabled="loading || next == null" @load="load(false)" />
    </div>

    <!-- ============ карточка пользователя ============ -->
    <Teleport to="body">
      <Transition name="sheet">
        <div v-if="open" class="admin backdrop" @click.self="close">
          <form class="sheet glass" role="dialog" aria-modal="true" @submit.prevent="save">
            <div class="grab" />
            <div class="u-head">
              <div class="u-ava big" :class="{ vip: form.vip, banned: form.banned }">
                {{ initials(form.display_name.trim() || tgName(open)) || '?' }}
              </div>
              <div class="grow">
                <div class="u-name ellipsis" :class="{ vip: form.vip }">{{ form.display_name.trim() || tgName(open) }}</div>
                <div class="r-sub ellipsis">
                  <template v-if="open.username">@{{ open.username }} · </template>ID {{ open.id }}
                </div>
              </div>
              <button type="button" class="icon-btn" :aria-label="t('common.close')" @click="close"><Icon name="close" :size="22" /></button>
            </div>

            <div class="u-stats">
              <div><b class="tnum">{{ compact(open.plays || 0) }}</b><span>{{ t('units.plays_short') }}</span></div>
              <div><b class="tnum">{{ open.loading ? '…' : compact(open.favorites || 0) }}</b><span>{{ t('admin.u_favs') }}</span></div>
              <div><b class="tnum">{{ open.loading ? '…' : compact(open.albums || 0) }}</b><span>{{ t('admin.u_albums') }}</span></div>
              <div><b class="tnum">{{ open.loading ? '…' : compact(open.published || 0) }}</b><span>{{ t('admin.u_published') }}</span></div>
            </div>
            <p class="hint center">{{ t('admin.user_since', { date: date(open.created_at), seen: relative(open.last_seen_at) }) }}</p>

            <div class="field">
              <div class="field-label">
                <span>{{ t('admin.u_name') }}</span>
                <small :class="{ over: nameLen > NAME_MAX }">{{ nameLen }}/{{ NAME_MAX }}</small>
              </div>
              <div class="name-row">
                <input v-model="form.display_name" class="input" :class="{ invalid: nameError }" :placeholder="tgName(open)" :maxlength="NAME_MAX + 8" autocomplete="off" />
                <button v-if="form.display_name" type="button" class="icon-btn" :aria-label="t('admin.u_name_reset')" @click="form.display_name = ''"><Icon name="close" :size="18" /></button>
              </div>
              <span v-if="nameError" class="err-text">{{ errorText({ message: nameError }) }}</span>
              <span v-else class="hint">{{ t('admin.u_name_hint') }}</span>
            </div>

            <div class="flags">
              <label v-for="f in FLAGS" :key="f.key" class="switch-row flag" :class="[f.cls, { off: open.is_admin && f.key !== 'vip' }]">
                <span class="flag-ico"><Icon :name="f.icon" :size="18" /></span>
                <span class="grow">
                  <span class="flag-title">{{ t('admin.u_' + f.key) }}</span>
                  <span class="hint">{{ t('admin.u_' + f.key + '_hint') }}</span>
                </span>
                <input v-model="form[f.key]" type="checkbox" :disabled="open.loading || (open.is_admin && f.key !== 'vip')" />
                <span class="switch" :class="{ warn: f.cls !== 'gold', gold: f.cls === 'gold' }" />
              </label>
            </div>

            <Transition name="fade">
              <div v-if="dirty" class="extra">
                <textarea v-model="form.reason" class="input reason" maxlength="300" :placeholder="t('admin.u_reason')" />
                <label class="switch-row notify">
                  <span>{{ t('admin.u_notify') }}</span>
                  <input v-model="form.notify" type="checkbox" />
                  <span class="switch" />
                </label>
              </div>
            </Transition>

            <div class="btn-row">
              <button type="button" class="btn" @click="close">{{ t('common.cancel') }}</button>
              <button type="submit" class="btn btn-primary" :disabled="!dirty || saving || !!nameError">
                <span v-if="saving" class="spinner" /><Icon v-else name="check" :size="18" />{{ t('common.save') }}
              </button>
            </div>
          </form>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.search {
  display: flex; align-items: center; gap: 8px; height: 44px; padding: 0 12px; margin-bottom: 10px;
  border-radius: 12px; background: var(--surface); border: 1px solid var(--border); color: var(--text-3);
}
.search input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; font-size: 15px; }
.chips { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; margin-bottom: 10px; }
.chip {
  flex-shrink: 0; height: 32px; padding: 0 12px; border-radius: 999px; font-size: 13px; font-weight: 600;
  color: var(--text-2); background: var(--surface); border: 1px solid var(--border); transition: background 0.2s, color 0.2s;
}
.chip.on { color: var(--on-accent); background: var(--accent); border-color: transparent; }
.user-row { width: 100%; text-align: left; transition: opacity 0.15s; }
.user-row:active { opacity: 0.6; }
.empty-row { padding: 24px 0; text-align: center; font-size: 14px; }

.u-ava {
  width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  background: var(--surface-2); font-weight: 700; font-size: 14px;
}
.u-ava.vip { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px #ffd36e; }
.u-ava.banned { opacity: 0.5; filter: grayscale(1); }
.u-ava.big { width: 52px; height: 52px; font-size: 18px; }
.star { margin-left: 4px; font-size: 11px; }
.tag { font-size: 10px; font-weight: 700; color: var(--text-3); border: 1px solid var(--border); border-radius: 5px; padding: 0 4px; margin-left: 4px; vertical-align: 1px; }
.tag.red { color: var(--danger); border-color: rgba(255, 92, 108, 0.4); }
.tag.warn { color: #f5a524; border-color: rgba(245, 165, 36, 0.4); }
.tag.acc { color: var(--accent-light); border-color: rgb(var(--accent-rgb) / 0.4); }

/* ---- карточка ---- */
.backdrop {
  position: fixed; inset: 0; z-index: 90; display: flex; align-items: flex-end; justify-content: center;
  background: rgba(0, 0, 0, 0.55); -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px);
}
.sheet {
  width: 100%; max-width: 560px; max-height: 92vh; overflow-y: auto; overscroll-behavior: contain;
  padding: 8px 18px calc(var(--safe-bottom) + 16px);
  border-radius: 24px 24px 0 0; border: 1px solid var(--border); border-bottom: 0;
  background: rgba(22, 22, 28, 0.94);
}
.grab { width: 38px; height: 5px; border-radius: 3px; background: var(--surface-3); margin: 0 auto 12px; }
.u-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.u-name { font-size: 18px; font-weight: 800; letter-spacing: -0.01em; }
.u-name.vip {
  background: linear-gradient(90deg, #ffd36e, #ff9ac9, #b59bff, #7fd8ff, #ffd36e); background-size: 220% auto;
  -webkit-background-clip: text; background-clip: text; color: transparent; -webkit-text-fill-color: transparent;
  animation: name-flow 5s linear infinite;
}
@keyframes name-flow { to { background-position: 220% center; } }
.u-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.u-stats div {
  display: flex; flex-direction: column; align-items: center; padding: 8px 4px; border-radius: 12px;
  background: var(--surface); border: 1px solid var(--border);
}
.u-stats b { font-size: 16px; }
.u-stats span { font-size: 11px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.center { text-align: center; margin: 8px 0 14px; }
.name-row { display: flex; align-items: center; gap: 6px; }
.flags { display: grid; gap: 4px; margin-bottom: 12px; }
.flag { padding: 8px 10px; border-radius: 14px; background: var(--surface); border: 1px solid var(--border); }
.flag.off { opacity: 0.45; pointer-events: none; }
.flag-ico { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; flex-shrink: 0; background: var(--surface-2); }
.flag.gold .flag-ico { color: #ffd36e; }
.flag.danger .flag-ico { color: var(--danger); }
.flag.warn .flag-ico { color: #f5a524; }
.flag .grow { display: flex; flex-direction: column; gap: 1px; }
.flag-title { font-size: 14.5px; font-weight: 600; }
.flag .hint { font-size: 11.5px; }
.sheet .flag input:checked + .switch.gold { background: linear-gradient(90deg, #ffbf47, #ff8ac2); }
.sheet .flag.danger input:checked + .switch { background: var(--danger); }
.extra { display: grid; gap: 8px; margin-bottom: 12px; }
.reason { min-height: 70px !important; }
.notify { font-size: 14px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.3s var(--ease); }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.4s var(--ease); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(100%); }
</style>
