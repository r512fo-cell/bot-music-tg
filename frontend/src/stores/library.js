import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { api } from '../lib/api'
import { haptic } from '../lib/telegram'

// Общий источник правды для лайков: один и тот же трек может быть в разных списках.
export const useLibrary = defineStore('library', () => {
  const liked = reactive(new Map())
  const likeDelta = reactive(new Map())
  const home = ref(null)
  const favoritesVersion = ref(0)

  const isLiked = (t) => (t ? (liked.has(t.id) ? liked.get(t.id) : !!t.liked) : false)
  const likes = (t) => (t?.likes || 0) + (likeDelta.get(t?.id) || 0)

  async function toggleLike(track) {
    const was = isLiked(track)
    liked.set(track.id, !was)
    likeDelta.set(track.id, (likeDelta.get(track.id) || 0) + (was ? -1 : 1))
    was ? haptic.tap() : haptic.success()
    try {
      await (was ? api.unlike(track.id) : api.like(track.id))
      favoritesVersion.value++
    } catch {
      liked.set(track.id, was)
      likeDelta.set(track.id, (likeDelta.get(track.id) || 0) + (was ? 1 : -1))
      haptic.error()
    }
  }

  async function loadHome(force = false) {
    if (home.value && !force) return home.value
    home.value = await api.home()
    return home.value
  }

  return { isLiked, likes, toggleLike, home, loadHome, favoritesVersion }
})
