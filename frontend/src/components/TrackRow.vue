<script setup>
import { computed } from 'vue'
import { usePlayer } from '../stores/player'
import { useLibrary } from '../stores/library'
import { artist, duration, compact } from '../lib/format'
import { t } from '../lib/i18n'
import Cover from './Cover.vue'
import Icon from './Icon.vue'
import Equalizer from './Equalizer.vue'

const props = defineProps({
  track: { type: Object, required: true },
  rank: { type: Number, default: 0 },
  showPlays: { type: Boolean, default: false },
})
const emit = defineEmits(['play', 'more'])
const player = usePlayer()
const lib = useLibrary()
const isCurrent = computed(() => player.current?.id === props.track.id)
</script>

<template>
  <div class="row" :class="{ current: isCurrent }" role="button" tabindex="0" @click="emit('play')" @keydown.enter="emit('play')">
    <span v-if="rank" class="rank tnum">{{ rank }}</span>
    <Cover :track="track" radius="10px" class="row-cover">
      <span v-if="isCurrent" class="overlay"><Equalizer :active="player.playing" /></span>
    </Cover>
    <div class="meta">
      <div class="title ellipsis">{{ track.title }}</div>
      <div class="sub ellipsis">
        {{ artist(track) }}
        <template v-if="showPlays && track.plays"> · {{ compact(track.plays) }} {{ t('units.plays_short') }}</template>
      </div>
    </div>
    <span class="dur tnum">{{ duration(track.duration) }}</span>
    <button class="icon-btn like" :class="{ on: lib.isLiked(track) }" :aria-label="lib.isLiked(track) ? t('actions.unlike') : t('actions.like')" @click.stop="lib.toggleLike(track)">
      <Icon :name="lib.isLiked(track) ? 'heart-fill' : 'heart'" :size="20" />
    </button>
    <button class="icon-btn more" :aria-label="t('actions.more')" @click.stop="emit('more', track)">
      <Icon name="more" :size="20" />
    </button>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 0;
  border-radius: 14px;
  cursor: pointer;
  transition: background 0.2s, transform 0.15s var(--ease);
  content-visibility: auto;
  contain-intrinsic-size: auto 62px;
}
.row:active { transform: scale(0.985); }
.rank {
  width: 22px;
  text-align: center;
  font-weight: 800;
  font-size: 17px;
  color: var(--text-3);
}
.row-cover { width: 48px; }
.overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
}
.meta { flex: 1; min-width: 0; }
.title { font-size: 15.5px; font-weight: 600; letter-spacing: -0.01em; }
.current .title { color: var(--accent); }
.sub { font-size: 13.5px; color: var(--text-2); margin-top: 2px; }
.dur { font-size: 13px; color: var(--text-3); }
.like, .more { width: 34px; height: 34px; color: var(--text-3); }
.like.on { color: var(--accent-2); animation: pop 0.35s var(--ease-spring); }
@keyframes pop { 50% { transform: scale(1.25); } }
.more { margin-right: -6px; }
</style>
