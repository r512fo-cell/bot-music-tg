<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { usePlayer } from '../stores/player'
import Icon from '../components/Icon.vue'
import TrackList from '../components/TrackList.vue'
import SkeletonRows from '../components/SkeletonRows.vue'
import InfiniteLoader from '../components/InfiniteLoader.vue'

const route = useRoute()
const router = useRouter()
const player = usePlayer()
const items = ref([])
const nextOffset = ref(0)
const loading = ref(false)
const error = ref('')

const tag = computed(() => route.query.tag || null)
const sort = computed(() => (['new', 'popular', 'title'].includes(route.query.sort) ? route.query.sort : 'new'))
const title = computed(() => (tag.value ? `#${tag.value}` : t(`tracks.title_${sort.value}`)))
const sorts = [{ id: 'new', label: 'tracks.sort_new' }, { id: 'popular', label: 'tracks.sort_popular' }, { id: 'title', label: 'tracks.sort_title' }]

async function load(reset) {
  if (loading.value || (!reset && nextOffset.value == null)) return
  loading.value = true
  error.value = ''
  try {
    const res = await api.tracks({ sort: sort.value, tag: tag.value, offset: reset ? 0 : nextOffset.value, limit: 40 })
    items.value = reset ? res.items : [...items.value, ...res.items]
    nextOffset.value = res.next_offset
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function setSort(id) { router.replace({ query: { ...route.query, sort: id } }) }
function playAll(shuffle) { player.playAll(items.value, shuffle) }

watch(() => [route.query.sort, route.query.tag], () => { if (route.name === 'tracks') load(true) }, { immediate: true })
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ title }}</h1>
    <div class="toolbar">
      <div class="sorts">
        <button v-for="s in sorts" :key="s.id" class="chip" :class="{ active: sort === s.id }" @click="setSort(s.id)">{{ t(s.label) }}</button>
      </div>
    </div>
    <div class="actions">
      <button class="btn btn-primary" :disabled="!items.length" @click="playAll(false)"><Icon name="play" :size="18" />{{ t('common.listen') }}</button>
      <button class="btn" :disabled="!items.length" @click="playAll(true)"><Icon name="shuffle" :size="18" />{{ t('common.shuffle') }}</button>
    </div>
    <TrackList :tracks="items" :show-plays="sort === 'popular'" />
    <SkeletonRows v-if="loading" :count="items.length ? 3 : 8" />
    <InfiniteLoader v-if="items.length" :disabled="loading || nextOffset == null" @load="load(false)" />
    <div v-if="!loading && !items.length" class="empty">
      <div class="empty-icon"><Icon name="music" /></div>
      <p>{{ error || t('common.empty') }}</p>
    </div>
  </div>
</template>

<style scoped>
.page-title { margin-top: 4px; }
.sorts { display: flex; gap: 8px; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0 12px; }
</style>
