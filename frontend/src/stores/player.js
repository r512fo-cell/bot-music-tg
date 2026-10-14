import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'
import { api, authenticate, currentToken } from '../lib/api'
import { artist, storage } from '../lib/format'
import { tg } from '../lib/telegram'

const PLAY_THRESHOLD = 30 // сек. прослушивания, после которых засчитывается проигрывание

function shuffled(list, firstId) {
  const rest = list.filter((t) => t.id !== firstId)
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[rest[i], rest[j]] = [rest[j], rest[i]]
  }
  const first = list.find((t) => t.id === firstId)
  return first ? [first, ...rest] : rest
}

export const usePlayer = defineStore('player', () => {
  const audio = new Audio()
  audio.preload = 'metadata'
  audio.crossOrigin = null

  const queue = shallowRef([])
  const originalQueue = shallowRef(null)
  const index = ref(-1)
  const playing = ref(false)
  const loading = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const buffered = ref(0)
  const shuffle = ref(storage.get('player.shuffle', false))
  const repeat = ref(storage.get('player.repeat', 'off')) // off | all | one
  const volume = ref(storage.get('player.volume', 1))
  const sheetOpen = ref(false)
  const queueOpen = ref(false)
  const error = ref('')
  const sleepAt = ref(0) // timestamp (ms) | -1 = после трека | 0 = выкл
  const canSetVolume = !['ios', 'android'].includes(tg?.platform)

  const current = computed(() => queue.value[index.value] || null)
  const hasNext = computed(() => index.value < queue.value.length - 1 || repeat.value === 'all')
  const progress = computed(() => (duration.value ? currentTime.value / duration.value : 0))
  const upNext = computed(() => queue.value.slice(index.value + 1))

  audio.volume = volume.value

  let srcTrackId = null
  let pendingSeek = 0
  let listened = 0
  let lastTime = 0
  let reported = false
  let retried = false
  let sleepTimer = null

  // ------------------------------------------------------------- загрузка
  function streamUrl(track) {
    return `/api/stream/${track.id}?t=${encodeURIComponent(currentToken() || '')}`
  }

  function attach(track, startAt = 0) {
    srcTrackId = track.id
    listened = 0
    lastTime = startAt
    reported = false
    retried = false
    error.value = ''
    pendingSeek = startAt
    currentTime.value = startAt
    duration.value = track.duration || 0
    buffered.value = 0
    audio.src = streamUrl(track) // синхронно — важно для iOS (жест пользователя)
    audio.load()
    updateMediaSession(track)
  }

  function start() {
    loading.value = true
    const p = audio.play()
    if (p?.catch) p.catch((e) => {
      if (e?.name !== 'AbortError') { loading.value = false; playing.value = false }
    })
    return p
  }

  function playIndex(i) {
    if (i < 0 || i >= queue.value.length) return
    index.value = i
    attach(queue.value[i])
    start()
  }

  // ------------------------------------------------------------- API
  /** toggleIfSame: нажатие на уже играющий трек в списке — пауза/продолжение.
   *  Для «Слушать всё» (playAll) очередь всегда заменяется и музыка запускается. */
  function playList(list, startIndex = 0, { toggleIfSame = true } = {}) {
    if (!list?.length) return
    const target = list[Math.min(Math.max(0, startIndex), list.length - 1)]
    if (toggleIfSame && current.value && current.value.id === target.id && srcTrackId === target.id) {
      toggle()
      return
    }
    originalQueue.value = list.slice()
    queue.value = shuffle.value ? shuffled(list, target.id) : list.slice()
    playIndex(queue.value.findIndex((t) => t.id === target.id))
  }

  function playTrack(track) { playList([track], 0) }

  /** «Слушать» / «Перемешать» для целого списка (альбом, избранное, история). */
  function playAll(list, withShuffle = false) {
    if (!list?.length) return
    if (shuffle.value !== withShuffle) {
      shuffle.value = withShuffle
      storage.set('player.shuffle', withShuffle)
    }
    playList(list, withShuffle ? Math.floor(Math.random() * list.length) : 0, { toggleIfSame: false })
  }

  function toggle() {
    if (!current.value) return
    if (srcTrackId !== current.value.id) { attach(current.value, pendingSeek); start(); return }
    if (audio.paused) start()
    else audio.pause()
  }

  function next(auto = false) {
    if (!queue.value.length) return
    if (auto && repeat.value === 'one') { audio.currentTime = 0; start(); return }
    if (index.value < queue.value.length - 1) playIndex(index.value + 1)
    else if (repeat.value === 'all') playIndex(0)
    else if (auto) { playing.value = false; audio.pause() }
    // ручное «Далее» в конце очереди без повтора ничего не делает (как и кнопка в мини-плеере)
  }

  function prev() {
    if (audio.currentTime > 3 || (index.value <= 0 && repeat.value !== 'all')) { seek(0); return }
    playIndex(index.value > 0 ? index.value - 1 : queue.value.length - 1)
  }

  function seek(seconds) {
    const d = duration.value || current.value?.duration || 0
    const t = Math.max(0, Math.min(seconds, d ? d - 0.25 : seconds))
    currentTime.value = t
    lastTime = t
    if (srcTrackId === current.value?.id && audio.readyState > 0) audio.currentTime = t
    else pendingSeek = t
  }

  function setVolume(v, persist = true) {
    volume.value = Math.max(0, Math.min(1, v))
    audio.volume = volume.value
    if (persist) storage.set('player.volume', volume.value) // не пишем в storage на каждое движение пальца
  }

  function toggleShuffle() {
    shuffle.value = !shuffle.value
    storage.set('player.shuffle', shuffle.value)
    const cur = current.value
    if (!cur) return
    if (shuffle.value) {
      originalQueue.value = queue.value.slice()
      queue.value = shuffled(queue.value, cur.id)
      index.value = 0
    } else if (originalQueue.value) {
      // исходный порядок, но с учётом правок очереди, сделанных в режиме перемешивания
      const present = new Set(queue.value.map((t) => t.id))
      const restored = originalQueue.value.filter((t) => present.has(t.id))
      const known = new Set(restored.map((t) => t.id))
      queue.value = [...restored, ...queue.value.filter((t) => !known.has(t.id))]
      index.value = queue.value.findIndex((t) => t.id === cur.id)
    }
  }

  function cycleRepeat() {
    repeat.value = { off: 'all', all: 'one', one: 'off' }[repeat.value]
    storage.set('player.repeat', repeat.value)
  }

  function playNext(track) {
    if (!current.value) return playTrack(track)
    const q = queue.value.filter((t, i) => i <= index.value || t.id !== track.id)
    q.splice(index.value + 1, 0, track)
    queue.value = q
  }

  function addToQueue(track) {
    if (!current.value) return playTrack(track)
    if (queue.value.some((t, i) => i > index.value && t.id === track.id)) return
    queue.value = [...queue.value, track]
  }

  function removeFromQueue(i) {
    if (i <= index.value || i >= queue.value.length) return
    const q = queue.value.slice()
    q.splice(i, 1)
    queue.value = q
  }

  function moveInQueue(from, to) {
    if (from <= index.value || to <= index.value) return
    const q = queue.value.slice()
    const [t] = q.splice(from, 1)
    q.splice(to, 0, t)
    queue.value = q
  }

  function setSleep(minutes) {
    clearTimeout(sleepTimer)
    if (minutes === 0) { sleepAt.value = 0; return }
    if (minutes === -1) { sleepAt.value = -1; return }
    sleepAt.value = Date.now() + minutes * 60_000
    sleepTimer = setTimeout(() => { audio.pause(); sleepAt.value = 0 }, minutes * 60_000)
  }

  // ------------------------------------------------------------- события <audio>
  audio.addEventListener('loadedmetadata', () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) duration.value = audio.duration
    if (pendingSeek) { audio.currentTime = pendingSeek; pendingSeek = 0 }
  })
  audio.addEventListener('timeupdate', () => {
    const t = audio.currentTime
    currentTime.value = t
    const delta = t - lastTime
    if (delta > 0 && delta < 2) listened += delta
    lastTime = t
    const track = current.value
    if (!reported && track && listened >= Math.min(PLAY_THRESHOLD, (duration.value || 60) * 0.5)) {
      reported = true
      api.play(track.id).catch(() => {})
    }
    updatePositionState()
  })
  audio.addEventListener('progress', () => {
    try {
      if (audio.buffered.length) buffered.value = audio.buffered.end(audio.buffered.length - 1)
    } catch {}
  })
  audio.addEventListener('waiting', () => { loading.value = true })
  audio.addEventListener('canplay', () => { loading.value = false })
  audio.addEventListener('playing', () => { loading.value = false; playing.value = true; error.value = '' })
  audio.addEventListener('play', () => { playing.value = true })
  audio.addEventListener('pause', () => { playing.value = false; saveSession() })
  audio.addEventListener('ended', () => {
    if (sleepAt.value === -1) { sleepAt.value = 0; playing.value = false; return }
    next(true)
  })
  audio.addEventListener('error', async () => {
    if (!audio.src || !current.value) return
    loading.value = false
    // Токен мог истечь — переавторизуемся и пробуем ещё раз с той же позиции
    if (!retried) {
      retried = true
      const pos = currentTime.value
      const failedId = srcTrackId
      try {
        await authenticate()
        const track = current.value
        if (!track || srcTrackId !== failedId) return // пока шла авторизация, включили другой трек
        srcTrackId = track.id
        pendingSeek = pos
        audio.src = streamUrl(track)
        audio.load()
        start()
        return
      } catch {}
    }
    playing.value = false
    error.value = 'play_failed'
  })

  // ------------------------------------------------------------- Media Session
  function updateMediaSession(track) {
    if (!('mediaSession' in navigator) || !track) return
    try {
      const art = track.cover ? [{ src: new URL(track.cover.l, location.origin).href, sizes: '600x600', type: 'image/webp' }] : []
      navigator.mediaSession.metadata = new MediaMetadata({ title: track.title, artist: artist(track), artwork: art })
    } catch {}
  }

  let lastPos = 0
  function updatePositionState() {
    if (!('mediaSession' in navigator) || !navigator.mediaSession.setPositionState) return
    const now = Date.now()
    if (now - lastPos < 1000 || !duration.value) return
    lastPos = now
    try {
      navigator.mediaSession.setPositionState({
        duration: duration.value, position: Math.min(audio.currentTime, duration.value), playbackRate: 1,
      })
    } catch {}
  }

  if ('mediaSession' in navigator) {
    const ms = navigator.mediaSession
    const handlers = {
      play: () => toggle(),
      pause: () => audio.pause(),
      previoustrack: () => prev(),
      nexttrack: () => next(),
      seekto: (d) => seek(d.seekTime),
      seekbackward: (d) => seek(audio.currentTime - (d.seekOffset || 10)),
      seekforward: (d) => seek(audio.currentTime + (d.seekOffset || 10)),
    }
    for (const [k, fn] of Object.entries(handlers)) {
      try { ms.setActionHandler(k, fn) } catch {}
    }
  }
  watch(playing, (v) => {
    if ('mediaSession' in navigator) navigator.mediaSession.playbackState = v ? 'playing' : 'paused'
  })

  // ------------------------------------------------------------- восстановление сессии
  function saveSession() {
    if (!current.value) return
    storage.set('player.last', { track: current.value, time: Math.floor(audio.currentTime || currentTime.value) })
  }
  setInterval(() => { if (playing.value) saveSession() }, 10_000)

  function restore() {
    const last = storage.get('player.last')
    if (!last?.track?.id || current.value) return
    queue.value = [last.track]
    originalQueue.value = null
    index.value = 0
    currentTime.value = last.time || 0
    duration.value = last.track.duration || 0
    pendingSeek = last.time || 0
  }

  return {
    audio, queue, index, current, playing, loading, currentTime, duration, buffered, progress,
    shuffle, repeat, volume, sheetOpen, queueOpen, error, sleepAt, hasNext, upNext, canSetVolume,
    playList, playTrack, playAll, playIndex, toggle, next, prev, seek, setVolume, toggleShuffle, cycleRepeat,
    playNext, addToQueue, removeFromQueue, moveInQueue, setSleep, restore,
  }
})
