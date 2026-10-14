// Сезонные темы: default | auto | autumn | winter | spring | summer (выбирает администратор)
import { ref } from 'vue'

export const THEMES = ['default', 'auto', 'autumn', 'winter', 'spring', 'summer']
export const season = ref(null) // активный сезон или null (тема по умолчанию)

export function seasonByDate(d = new Date()) {
  const m = d.getMonth() // 0 — январь
  if (m === 11 || m <= 1) return 'winter'
  if (m <= 4) return 'spring'
  if (m <= 7) return 'summer'
  return 'autumn'
}

export function applyTheme(theme) {
  const resolved = theme === 'auto' ? seasonByDate() : ['autumn', 'winter', 'spring', 'summer'].includes(theme) ? theme : null
  season.value = resolved
  const root = document.documentElement
  if (resolved) root.dataset.season = resolved
  else delete root.dataset.season
}
