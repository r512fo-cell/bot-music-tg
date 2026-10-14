// Лёгкая i18n без зависимостей: реактивная локаль + словари RU/EN.
import { ref } from 'vue'
import ru from '../locales/ru'
import en from '../locales/en'

const DICTS = { ru, en }
export const LOCALES = ['ru', 'en']

function initial() {
  const code = (window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code || navigator.language || 'en').slice(0, 2)
  return ['ru', 'uk', 'be', 'kk'].includes(code) ? 'ru' : 'en'
}

export const locale = ref(initial())
document.documentElement.lang = locale.value

export function setLocale(lang) {
  if (!DICTS[lang]) return
  locale.value = lang
  document.documentElement.lang = lang
}

function lookup(dict, key) {
  let v = dict
  for (const part of key.split('.')) {
    if (v == null) return undefined
    v = v[part]
  }
  return v
}

/** t('player.queue'), t('home.greeting', { name }) */
export function t(key, vars) {
  let s = lookup(DICTS[locale.value], key) ?? lookup(DICTS.ru, key) ?? key
  if (typeof s !== 'string') return key
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''))
  return s
}

/** Список строк (например, фразы экрана загрузки) */
export function tlist(key) {
  const v = lookup(DICTS[locale.value], key) ?? lookup(DICTS.ru, key)
  return Array.isArray(v) ? v : []
}

/** Плюрализация: tp(5, 'units.tracks') -> «5 треков» / «5 tracks» */
export function tp(n, key, withNumber = true) {
  const forms = lookup(DICTS[locale.value], key) ?? lookup(DICTS.ru, key)
  if (!Array.isArray(forms)) return key
  let word
  if (locale.value === 'ru') {
    const a = Math.abs(n) % 100
    const b = a % 10
    word = a > 10 && a < 20 ? forms[2] : b > 1 && b < 5 ? forms[1] : b === 1 ? forms[0] : forms[2]
  } else {
    word = Math.abs(n) === 1 ? forms[0] : forms[1]
  }
  return withNumber ? `${fmtNum(n)} ${word}` : word
}

export const intlLocale = () => (locale.value === 'ru' ? 'ru-RU' : 'en-US')
export const fmtNum = (n) => new Intl.NumberFormat(intlLocale()).format(n || 0)

/** Текст ошибки API по коду (сервер возвращает коды вида album_name_long). */
export function errorText(e, vars) {
  const code = e?.message || ''
  const key = `errors.${code}`
  const s = t(key, vars)
  return s === key ? (code && !/^[a-z_]+$/.test(code) ? code : t('errors.generic')) : s
}
