<script setup>
import { usePlayer } from '../stores/player'
import { useUi } from '../stores/ui'
import TrackRow from './TrackRow.vue'

const props = defineProps({
  tracks: { type: Array, required: true },
  ranked: { type: Boolean, default: false },
  showPlays: { type: Boolean, default: false },
  context: { type: Object, default: null }, // например { albumId } — для «Удалить из альбома»
})
const player = usePlayer()
const ui = useUi()
</script>

<template>
  <div class="list">
    <TrackRow
      v-for="(t, i) in tracks"
      :key="t.id"
      :track="t"
      :rank="ranked ? i + 1 : 0"
      :show-plays="showPlays"
      @play="player.playList(props.tracks, i)"
      @more="ui.openActions(t, context)"
    />
  </div>
</template>

<style scoped>
.list { display: flex; flex-direction: column; }
</style>
