import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { t } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import { useSession } from './session'

export const useAlbums = defineStore('albums', () => {
  const items = ref(null)
  const version = ref(0) // растёт при любом изменении — представления перезагружают данные
  const session = useSession()
  const limit = computed(() => session.config.album_limit || 50)
  // администратор может ограничить создание и изменение альбомов
  const restricted = computed(() => !!session.restrictions.albums)
  const canCreate = computed(() => !restricted.value && (items.value?.length || 0) < limit.value)
  const blockText = computed(() => (restricted.value ? t('errors.albums_restricted') : t('errors.album_limit', { n: limit.value })))

  async function load() {
    const res = await api.albums.list()
    items.value = res.items
    return items.value
  }
  const bump = () => { version.value++ }

  async function create(name, icon, trackId) {
    const album = await api.albums.create({ name, icon, track_id: trackId || null })
    items.value = [album, ...(items.value || [])]
    bump()
    haptic.success()
    return album
  }
  async function update(id, body) {
    const album = await api.albums.update(id, body)
    items.value = (items.value || []).map((a) => (a.id === id ? album : a))
    bump()
    return album
  }
  async function remove(id) {
    await api.albums.remove(id)
    items.value = (items.value || []).filter((a) => a.id !== id)
    bump()
  }
  async function addTrack(id, trackId) { await api.albums.addTrack(id, trackId); bump() }
  async function removeTrack(id, trackId) { await api.albums.removeTrack(id, trackId); bump() }

  return { items, version, limit, restricted, canCreate, blockText, load, create, update, remove, addTrack, removeTrack, bump }
})
