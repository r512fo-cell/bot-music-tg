<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { storage } from '../lib/format'
import { t } from '../lib/i18n'
import { useLibrary } from '../stores/library'
import Icon from '../components/Icon.vue'
import TrackList from '../components/TrackList.vue'
import SkeletonRows from '../components/SkeletonRows.vue'
import InfiniteLoader from '../components/InfiniteLoader.vue'

defineOptions({ name: 'SearchView' })

const lib = useLibrary()
const q = ref('')
const results = ref([])
const nextOffset = ref(null)
const loading = ref(false)
const searched = ref(false)
const recent = ref(storage.get('search.recent', []))
const input = ref(null)
let timer = null
let controller = null

const COLLECTIONS = [
  { sort: 'new', icon: 'sparkles', label: 'search.new', hue: 200 },
  { sort: 'popular', icon: 'flame', label: 'search.popular', hue: 22 },
  { sort: 'title', icon: 'music', label: 'search.az', hue: 152 },
]
// Стабильный оттенок для тега (не зависит от порядка в списке)
function hue(tag) {
  let h = 0x811c9dc5
  for (const ch of tag) h = Math.imul(h ^ ch.codePointAt(0), 0x01000193) >>> 0
  // золотой угол разносит соседние значения по кругу оттенков
  return Math.round(((h ^ (h >>> 15)) % 1000) * 137.508) % 360
}

async function run(reset = true) {
  const query = q.value.trim()
  controller?.abort() // ответ на старый запрос не должен перезаписать новый (или очищенный) поиск
  controller = null
  if (!query) { results.value = []; searched.value = false; loading.value = false; return }
  const mine = (controller = new AbortController())
  loading.value = true
  try {
    const res = await api.search({ q: query, offset: reset ? 0 : nextOffset.value, limit: 30 }, mine.signal)
    results.value = reset ? res.items : [...results.value, ...res.items]
    nextOffset.value = res.next_offset
    searched.value = true
    if (reset && res.items.length) remember(query)
  } catch (e) {
    if (e.name !== 'AbortError') searched.value = true
  } finally {
    if (controller === mine) loading.value = false
  }
}

function remember(query) {
  recent.value = [query, ...recent.value.filter((x) => x.toLowerCase() !== query.toLowerCase())].slice(0, 6)
  storage.set('search.recent', recent.value)
}
function clearRecent() { recent.value = []; storage.set('search.recent', []) }
function pick(text) { q.value = text }
function clear() { q.value = ''; input.value?.focus() }

watch(q, () => {
  clearTimeout(timer)
  timer = setTimeout(() => run(true), 300)
})

onMounted(() => lib.loadHome().catch(() => {}))
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('search.title') }}</h1>
    <div class="search-box glass">
      <Icon name="search" :size="20" class="faint" />
      <input
        ref="input"
        v-model="q"
        type="search"
        inputmode="search"
        enterkeyhint="search"
        maxlength="100"
        :placeholder="t('search.placeholder')"
        autocomplete="off"
        @keydown.enter="$event.target.blur()"
      />
      <button v-if="q" class="icon-btn clear" :aria-label="t('common.clear')" @click="clear"><Icon name="close" :size="18" /></button>
    </div>

    <template v-if="!q.trim()">
      <section v-if="recent.length" class="section">
        <div class="section-head">
          <h2 class="section-title small">{{ t('search.recent') }}</h2>
          <button class="section-link" @click="clearRecent">{{ t('common.clear') }}</button>
        </div>
        <div class="recent">
          <button v-for="r in recent" :key="r" class="chip" @click="pick(r)"><Icon name="clock" :size="15" />{{ r }}</button>
        </div>
      </section>

      <section class="section">
        <h2 class="section-title small mb">{{ t('search.collections') }}</h2>
        <div class="collections">
          <RouterLink v-for="c in COLLECTIONS" :key="c.sort" :to="{ name: 'tracks', query: { sort: c.sort } }" class="coll" :style="{ '--h': c.hue }">
            <span class="coll-icon"><Icon :name="c.icon" :size="20" /></span>
            <span class="coll-name">{{ t(c.label) }}</span>
          </RouterLink>
        </div>
      </section>

      <section v-if="lib.home?.tags?.length" class="section">
        <h2 class="section-title small mb">{{ t('search.genres') }}</h2>
        <div class="tags">
          <RouterLink
            v-for="tag in lib.home.tags"
            :key="tag.tag"
            :to="{ name: 'tracks', query: { tag: tag.tag } }"
            class="tag"
            :style="{ '--h': hue(tag.tag) }"
          >
            <span class="tag-hash">#</span>
            <span class="tag-name ellipsis">{{ tag.tag }}</span>
            <span class="tag-count tnum">{{ tag.count }}</span>
          </RouterLink>
        </div>
      </section>
    </template>

    <section v-else class="section">
      <TrackList :tracks="results" />
      <SkeletonRows v-if="loading && !results.length" :count="5" />
      <InfiniteLoader v-if="results.length" :disabled="loading || nextOffset == null" @load="run(false)" />
      <div v-if="searched && !loading && !results.length" class="empty">
        <div class="empty-icon"><Icon name="search" /></div>
        <p>{{ t('search.nothing', { q }) }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.search-box {
  position: sticky;
  top: calc(var(--safe-top) + 8px);
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 48px;
  padding: 0 8px 0 14px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: rgba(28, 28, 34, 0.72);
}
input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 16px;
}
input::placeholder { color: var(--text-3); }
input::-webkit-search-cancel-button { display: none; }
.clear { width: 32px; height: 32px; color: var(--text-2); }
.small { font-size: 17px; }
.mb { margin-bottom: 12px; }
.recent { display: flex; flex-wrap: wrap; gap: 8px; }
.collections { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.coll {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-height: 92px;
  padding: 12px;
  border-radius: 18px;
  overflow: hidden;
  background:
    radial-gradient(120% 90% at 100% 0%, hsl(var(--h) 85% 60% / 0.22), transparent 60%),
    var(--surface);
  border: 1px solid var(--border);
  transition: transform 0.15s var(--ease), border-color 0.2s;
}
.coll:active { transform: scale(0.96); }
.coll-icon {
  width: 36px; height: 36px; border-radius: 12px; display: grid; place-items: center;
  color: hsl(var(--h) 90% 72%); background: hsl(var(--h) 80% 55% / 0.16);
}
.coll-name { font-size: 14px; font-weight: 700; letter-spacing: -0.01em; }

.tags { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.tag {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 52px;
  padding: 0 10px 0 8px;
  border-radius: 16px;
  min-width: 0;
  background:
    linear-gradient(90deg, hsl(var(--h) 80% 55% / 0.14), transparent 70%),
    var(--surface);
  border: 1px solid var(--border);
  transition: transform 0.15s var(--ease), background 0.2s;
}
.tag:active { transform: scale(0.97); }
.tag-hash {
  flex-shrink: 0;
  width: 34px; height: 34px; border-radius: 11px;
  display: grid; place-items: center;
  font-size: 17px; font-weight: 800;
  color: #fff;
  background: linear-gradient(140deg, hsl(var(--h) 78% 60%), hsl(calc(var(--h) + 40) 70% 42%));
  box-shadow: 0 6px 14px -8px hsl(var(--h) 80% 50% / 0.9);
}
.tag-name { flex: 1; font-size: 14.5px; font-weight: 600; }
.tag-count {
  flex-shrink: 0; font-size: 11.5px; font-weight: 700; color: var(--text-2);
  padding: 2px 7px; border-radius: 999px; background: rgba(255, 255, 255, 0.07);
}
</style>
