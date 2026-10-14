import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError, api, authenticate, mediaUrl, onBanned, onMaintenance } from '../lib/api'
import { initials as makeInitials } from '../lib/format'
import { locale, setLocale } from '../lib/i18n'
import { applyTheme } from '../lib/theme'
import { tgUser } from '../lib/telegram'

export const useSession = defineStore('session', () => {
  const user = ref(null)
  const stats = ref(null)
  const config = ref({})
  const status = ref('idle') // idle | loading | ready | maintenance | banned | no-telegram | error
  const errorText = ref('')
  const avatar = ref('')

  const isAdmin = computed(() => !!user.value?.is_admin)
  const isVip = computed(() => !!user.value?.vip)
  // имя, которое задал администратор, важнее имени из Telegram
  const displayName = computed(() => {
    if (user.value?.display_name) return user.value.display_name
    const u = user.value || tgUser()
    return u ? [u.first_name, u.last_name].filter(Boolean).join(' ') : ''
  })
  const restrictions = computed(() => user.value?.restrictions || {})
  const initials = computed(() => makeInitials(displayName.value))

  async function init() {
    status.value = 'loading'
    try {
      const res = await authenticate()
      user.value = res.user
      config.value = res.config || {}
      setLocale(res.user.lang)
      applyTheme(config.value.theme)
      status.value = config.value.maintenance && !res.user.is_admin ? 'maintenance' : 'ready'
      if (status.value === 'ready') loadAvatar()
    } catch (e) {
      if (e instanceof ApiError && e.message === 'NO_TELEGRAM') status.value = 'no-telegram'
      else if (e instanceof ApiError && e.status === 403 && e.message === 'banned') status.value = 'banned'
      else { status.value = 'error'; errorText.value = e.message || '' }
    }
  }

  // Сервер включил обслуживание, пока приложение открыто
  onMaintenance(() => { if (!isAdmin.value) status.value = 'maintenance' })
  onBanned(() => { if (!isAdmin.value) status.value = 'banned' })

  function tryImage(url) {
    return new Promise((resolve) => {
      const img = new Image()
      img.onload = () => resolve(true)
      img.onerror = () => resolve(false)
      img.src = url
    })
  }

  async function loadAvatar() {
    const url = await mediaUrl('/api/me/avatar')
    if (await tryImage(url)) { avatar.value = url; return }
    // запасной вариант: фото из initData (если Telegram его передал)
    const photo = tgUser()?.photo_url
    if (photo && photo.startsWith('https://t.me/') && (await tryImage(photo))) avatar.value = photo
  }

  async function refresh() {
    const me = await api.me()
    const { stats: s, config: cfg, ...profile } = me
    user.value = { ...user.value, ...profile }
    stats.value = s
    if (cfg) config.value = { ...config.value, ...cfg } // лимиты меняются вместе с Premium
  }

  async function setLanguage(lang) {
    if (lang === locale.value) return
    const prev = locale.value
    setLocale(lang)
    if (user.value) user.value.lang = lang
    try { await api.settings({ lang }) } catch { setLocale(prev) }
  }

  return { user, stats, config, status, errorText, avatar, isAdmin, isVip, restrictions, displayName, initials, init, refresh, setLanguage }
})
