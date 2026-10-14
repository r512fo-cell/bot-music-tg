import { api } from './api'
import { artist } from './format'
import { t } from './i18n'
import { openTelegramLink } from './telegram'
import { useSession } from '../stores/session'

/** Ссылка, открывающая мини-приложение с нужным треком или альбомом. */
export function shareLink(param) {
  const base = useSession().config.share_base
  return base ? base + param : null
}

function openShare(url, text) {
  openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`)
}

export function shareTrack(track) {
  const url = shareLink(`t_${track.id}`) || track.post_url
  if (url) openShare(url, `🎵 ${artist(track)} — ${track.title}`)
}

export async function shareAlbum(album) {
  const { param } = await api.albums.share(album.id)
  const url = shareLink(param)
  if (url) openShare(url, t('album.share_text', { name: `${album.icon} ${album.name}` }))
  return param
}
