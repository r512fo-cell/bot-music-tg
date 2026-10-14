<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import { artist, isNew } from '../lib/format'
import { t, tp } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import { useLibrary } from '../stores/library'
import { usePlayer } from '../stores/player'
import { useSession } from '../stores/session'
import { useUi } from '../stores/ui'
import AdBlock from '../components/AdBlock.vue'
import AlbumArt from '../components/AlbumArt.vue'
import Cover from '../components/Cover.vue'
import Equalizer from '../components/Equalizer.vue'
import Icon from '../components/Icon.vue'
import PullCarousel from '../components/PullCarousel.vue'
import SantaHat from '../components/SantaHat.vue'
import ViewsBadge from '../components/ViewsBadge.vue'
import { season } from '../lib/theme'

defineOptions({ name: 'HomeView' })

const lib = useLibrary()
const player = usePlayer()
const session = useSession()
const ui = useUi()
const data = ref(lib.home)
const error = ref('')
let loadedAt = 0

async function load(force = false) {
  error.value = ''
  try {
    data.value = await lib.loadHome(force)
    loadedAt = Date.now()
  } catch (e) {
    error.value = e.message
  }
}

function play(list, i) {
  haptic.tap()
  player.playList(list, i)
}
const isCurrent = (tr) => player.current?.id === tr.id
const newTitle = computed(() => Array.from(t('home.new')))
// рекомендации раскладываются по «страницам» из 4 строк — листаются вбок
const recoCols = computed(() => {
  const list = data.value?.recommended || []
  const cols = []
  for (let i = 0; i < list.length; i += 4) cols.push(list.slice(i, i + 4))
  return cols
})

onMounted(() => load(!!lib.home))
onActivated(() => { if (Date.now() - loadedAt > 3 * 60_000) load(true) })
</script>

<template>
  <div class="page home">
    <!-- верх намеренно пустой — минимализм; профиль доступен из таб-бара -->
    <div class="top-space" aria-hidden="true" />

    <RouterLink v-if="session.isAdmin && session.config.maintenance" to="/admin" class="maint-banner">
      <Icon name="wrench" :size="16" />{{ t('maintenance.admin_banner') }}
    </RouterLink>

    <AdBlock placement="home" class="home-ad" />

    <div v-if="error && !data" class="empty">
      <div class="empty-icon"><Icon name="refresh" /></div>
      <p>{{ error }}</p>
      <button class="btn" @click="load(true)">{{ t('common.retry') }}</button>
    </div>

    <template v-else>
      <!-- ============ Новинки ============ -->
      <section class="block">
        <h2 class="block-title">
          <span class="cap">{{ newTitle[0] }}<SantaHat v-if="season === 'winter'" /></span>{{ newTitle.slice(1).join('') }}
        </h2>
        <PullCarousel :to="{ name: 'tracks', query: { sort: 'new' } }">
          <template v-if="!data">
            <div v-for="i in 3" :key="i" class="new-card"><div class="skeleton sk-sq" /></div>
          </template>
          <article v-for="(tr, i) in data?.new || []" :key="tr.id" class="new-card" @click="play(data.new, i)">
            <Cover :track="tr" size="l" radius="20px" :eager="i < 2" class="new-cover">
              <div class="shade" />
              <span v-if="isNew(tr)" class="badge">NEW</span>
              <span class="play glass" :class="{ on: isCurrent(tr) && player.playing }">
                <Equalizer v-if="isCurrent(tr) && player.playing" />
                <Icon v-else name="play" :size="17" />
              </span>
              <div class="new-meta">
                <div class="new-title ellipsis">{{ tr.title }}</div>
                <div class="new-sub ellipsis">{{ artist(tr) }}</div>
              </div>
            </Cover>
          </article>
        </PullCarousel>
        <p v-if="data && !data.new.length" class="muted hint">{{ t('home.empty') }}</p>
      </section>

      <!-- ============ Рекомендуем ============ -->
      <section v-if="recoCols.length" class="block">
        <h2 class="block-title">{{ t('home.for_you') }}</h2>
        <p class="block-sub">{{ t('home.for_you_sub') }}</p>
        <div class="reco">
          <div v-for="(col, ci) in recoCols" :key="ci" class="reco-col">
            <div
              v-for="(tr, ri) in col"
              :key="tr.id"
              class="reco-row"
              :class="{ current: isCurrent(tr) }"
              role="button"
              tabindex="0"
              @click="play(data.recommended, ci * 4 + ri)"
            >
              <Cover :track="tr" radius="10px" class="reco-cover">
                <span v-if="isCurrent(tr)" class="now fill"><Equalizer :active="player.playing" /></span>
              </Cover>
              <div class="reco-meta">
                <div class="reco-title ellipsis">{{ tr.title }}</div>
                <div class="reco-sub ellipsis">{{ artist(tr) }}</div>
              </div>
              <button class="icon-btn reco-more" :aria-label="t('actions.more')" @click.stop="ui.openActions(tr)">
                <Icon name="more" :size="20" />
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ Популярное ============ -->
      <section v-if="data?.popular?.length" class="block">
        <h2 class="block-title">{{ t('home.popular') }}</h2>
        <PullCarousel :to="data.popular.length >= 10 ? { name: 'tracks', query: { sort: 'popular' } } : null">
          <article v-for="(tr, i) in data.popular" :key="tr.id" class="sq-card" @click="play(data.popular, i)">
            <Cover :track="tr" radius="16px" class="sq-cover">
              <span class="rank">{{ i + 1 }}</span>
              <span v-if="isCurrent(tr)" class="now"><Equalizer :active="player.playing" /></span>
            </Cover>
            <div class="sq-title ellipsis">{{ tr.title }}</div>
            <div class="sq-sub ellipsis">{{ artist(tr) }}</div>
          </article>
        </PullCarousel>
      </section>

      <!-- ============ Альбомы слушателей ============ -->
      <section v-if="data?.albums?.length" class="block">
        <h2 class="block-title">{{ t('home.albums') }}</h2>
        <PullCarousel :to="data.albums.length >= 5 ? { name: 'albums' } : null">
          <RouterLink
            v-for="a in data.albums"
            :key="a.id"
            :to="{ name: 'shared-album', params: { code: a.share_param.slice(2) } }"
            class="sq-card album"
          >
            <div class="art-box"><AlbumArt :album="a" radius="18px" /><ViewsBadge :views="a.views" /></div>
            <div class="sq-title ellipsis">{{ a.name }}</div>
            <div class="sq-sub ellipsis">{{ a.owner_name || '' }} · {{ tp(a.track_count, 'units.tracks') }}</div>
          </RouterLink>
        </PullCarousel>
      </section>

      <!-- ============ Вы слушали ============ -->
      <section v-if="data?.recent?.length" class="block">
        <h2 class="block-title">{{ t('home.recent') }}</h2>
        <PullCarousel :to="null" :gap="14">
          <article v-for="(tr, i) in data.recent" :key="tr.id" class="mini-card" @click="play(data.recent, i)">
            <Cover :track="tr" radius="50%" class="mini-cover">
              <span v-if="isCurrent(tr)" class="now round"><Equalizer :active="player.playing" /></span>
            </Cover>
            <div class="mini-title ellipsis">{{ tr.title }}</div>
          </article>
        </PullCarousel>
      </section>
    </template>
  </div>
</template>

<style scoped>
.top-space { height: 18px; }
.home-ad { margin-top: 4px; }
.maint-banner {
  display: flex; align-items: center; gap: 8px; margin-top: 8px; padding: 10px 14px;
  border-radius: 12px; font-size: 13px; font-weight: 600; color: #ffd27a;
  background: rgba(255, 196, 0, 0.1); border: 1px solid rgba(255, 196, 0, 0.25);
}

.block { margin-top: 26px; }
.cap { position: relative; display: inline-block; }
.block-title { font-size: 20px; font-weight: 800; letter-spacing: -0.025em; margin-bottom: 12px; }
.hint { font-size: 14px; }

/* --- новинки --- */
.new-card { width: min(46vw, 196px); cursor: pointer; }
.new-cover { width: 100%; box-shadow: 0 18px 36px -22px rgba(0, 0, 0, 0.9); transition: transform 0.25s var(--ease); }
.new-card:active .new-cover { transform: scale(0.97); }
.sk-sq { width: 100%; aspect-ratio: 1; border-radius: 20px; }
.shade { position: absolute; inset: 0; background: linear-gradient(180deg, transparent 50%, rgba(0, 0, 0, 0.8) 100%); }
.badge {
  position: absolute; top: 10px; left: 10px; padding: 3px 8px; border-radius: 999px;
  font-size: 10px; font-weight: 800; letter-spacing: 0.08em; background: var(--accent-grad); color: var(--on-accent);
}
.play {
  position: absolute; right: 10px; bottom: 10px; width: 36px; height: 36px; border-radius: 50%;
  display: grid; place-items: center; color: #fff;
  background: rgba(255, 255, 255, 0.18); border: 1px solid rgba(255, 255, 255, 0.2);
}
.play.on { background: var(--accent-grad); border-color: transparent; color: var(--on-accent); }
.new-meta { position: absolute; left: 12px; right: 54px; bottom: 11px; }
.new-title { font-size: 15px; font-weight: 700; letter-spacing: -0.01em; }
.new-sub { font-size: 12.5px; color: rgba(255, 255, 255, 0.72); margin-top: 1px; }

/* --- рекомендации: колонки по 4 строки, листаются вбок --- */
.block-sub { font-size: 13px; color: var(--text-3); margin: -8px 0 10px; }
.reco {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: calc(100% - 40px);
  gap: 14px;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scroll-padding: 0 var(--gutter);
  margin: 0 calc(var(--gutter) * -1);
  padding: 0 var(--gutter) 4px;
  scrollbar-width: none;
  overscroll-behavior-x: contain;
}
.reco::-webkit-scrollbar { display: none; }
.reco-col { scroll-snap-align: start; display: grid; gap: 2px; align-content: start; min-width: 0; }
.reco-row { display: flex; align-items: center; gap: 12px; padding: 6px 0; min-width: 0; cursor: pointer; border-radius: 12px; transition: transform 0.15s var(--ease); }
.reco-row:active { transform: scale(0.985); }
.reco-cover { width: 52px; }
.reco-meta { flex: 1; min-width: 0; }
.reco-title { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
.reco-row.current .reco-title { color: var(--accent); }
.reco-sub { font-size: 13px; color: var(--text-2); margin-top: 2px; }
.reco-more { width: 34px; height: 34px; color: var(--text-3); margin-right: -4px; }
.now.fill { inset: 0; position: absolute; width: auto; height: auto; border-radius: 0; display: grid; place-items: center; background: rgba(0, 0, 0, 0.45); }

/* --- квадратные карточки (популярное, альбомы) --- */
.sq-card { width: 138px; cursor: pointer; display: block; }
.sq-cover, .sq-card.album :deep(.art) { width: 100%; transition: transform 0.25s var(--ease); }
.sq-card:active .sq-cover, .sq-card:active :deep(.art) { transform: scale(0.96); }
.rank {
  position: absolute; left: 8px; bottom: 2px;
  font-size: 40px; font-weight: 900; line-height: 1; letter-spacing: -0.06em;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 4px 18px rgba(0, 0, 0, 0.55);
}
.now {
  position: absolute; right: 8px; top: 8px; width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center; color: #fff; background: rgba(0, 0, 0, 0.5);
}
.now.round { inset: 0; width: auto; height: auto; border-radius: 50%; background: rgba(0, 0, 0, 0.45); }
.sq-title { font-size: 14px; font-weight: 600; margin-top: 8px; }
.sq-sub { font-size: 12.5px; color: var(--text-2); margin-top: 1px; }

/* --- недавно слушали --- */
.mini-card { width: 84px; cursor: pointer; text-align: center; }
.mini-cover { width: 84px; box-shadow: 0 10px 24px -14px rgba(0, 0, 0, 0.9); transition: transform 0.2s var(--ease); }
.mini-card:active .mini-cover { transform: scale(0.94); }
.mini-title { font-size: 12.5px; font-weight: 500; color: var(--text-2); margin-top: 8px; }
.art-box { position: relative; }
</style>
