import { fmtNum, intlLocale, t, tp } from './i18n'

export function duration(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = String(sec % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export const num = (n) => fmtNum(n)

export function compact(n) {
  n = n || 0
  const dec = (v) => (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10).toLocaleString(intlLocale())
  if (n >= 1e6) return `${dec(n / 1e6)}${t('units.million')}`
  if (n >= 1e3) return `${dec(n / 1e3)}${t('units.thousand')}`
  return String(n)
}

export function date(ts, opts = { day: 'numeric', month: 'long', year: 'numeric' }) {
  return new Date(ts * 1000).toLocaleDateString(intlLocale(), opts)
}

export function dateTime(ts) {
  return new Date(ts * 1000).toLocaleString(intlLocale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function relative(ts) {
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return t('time.just_now')
  if (diff < 3600) return t('time.ago', { v: tp(Math.floor(diff / 60), 'units.minutes') })
  if (diff < 86400) return t('time.ago', { v: tp(Math.floor(diff / 3600), 'units.hours') })
  if (diff < 86400 * 2) return t('time.yesterday')
  if (diff < 86400 * 7) return t('time.ago', { v: tp(Math.floor(diff / 86400), 'units.days') })
  return date(ts, { day: 'numeric', month: 'short' })
}

/** «через 2 ч» для запланированных событий */
export function until(ts) {
  const diff = ts - Date.now() / 1000
  if (diff <= 0) return t('time.now')
  if (diff < 3600) return t('time.in', { v: tp(Math.ceil(diff / 60), 'units.minutes') })
  if (diff < 86400) return t('time.in', { v: tp(Math.round(diff / 3600), 'units.hours') })
  return t('time.in', { v: tp(Math.round(diff / 86400), 'units.days') })
}

export function listenTime(sec) {
  sec = sec || 0
  const h = Math.floor(sec / 3600)
  const m = Math.round((sec % 3600) / 60)
  return h ? `${h} ${t('units.h')} ${m} ${t('units.min')}` : `${m} ${t('units.min')}`
}

export function bytes(n) {
  const u = t('units.bytes').split(',')
  if (n >= 1 << 30) return (n / (1 << 30)).toFixed(1) + ' ' + u[3]
  if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + ' ' + u[2]
  if (n >= 1 << 10) return (n / (1 << 10)).toFixed(0) + ' ' + u[1]
  return n + ' ' + u[0]
}

export const artist = (tr) => tr?.performer || t('common.unknown_artist')
export const isNew = (tr) => tr && Date.now() / 1000 - tr.posted_at < 3 * 86400

/** Первая «буква» каждого слова — корректно для эмодзи и составных символов. */
export function initials(name) {
  const letters = []
  for (const word of (name || '').split(/\s+/)) {
    const ch = Array.from(word).find((c) => /[\p{L}\p{N}]/u.test(c))
    if (ch) letters.push(ch.toUpperCase())
    if (letters.length === 2) break
  }
  return letters.join('')
}

// Безопасное localStorage (в некоторых WebView может бросать исключения)
export const storage = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v) } catch { return fallback }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)) } catch {}
  },
}
