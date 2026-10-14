// Обёртка над Telegram.WebApp с безопасными проверками версий.
export const tg = window.Telegram?.WebApp ?? null

const BG = '#09090b'

export function initTelegram() {
  if (!tg) return
  try {
    tg.ready()
    tg.expand()
    if (tg.isVersionAtLeast?.('6.1')) {
      tg.setHeaderColor(BG)
      tg.setBackgroundColor(BG)
    }
    if (tg.isVersionAtLeast?.('7.10')) tg.setBottomBarColor?.(BG)
    // Свайп вниз по плееру не должен закрывать приложение
    if (tg.isVersionAtLeast?.('7.7')) tg.disableVerticalSwipes?.()
  } catch (e) {
    console.warn('Telegram init', e)
  }
}

export const initData = () => tg?.initData || ''
export const tgUser = () => tg?.initDataUnsafe?.user || null

export const haptic = {
  tap() { try { tg?.HapticFeedback?.impactOccurred('light') } catch {} },
  medium() { try { tg?.HapticFeedback?.impactOccurred('medium') } catch {} },
  select() { try { tg?.HapticFeedback?.selectionChanged() } catch {} },
  success() { try { tg?.HapticFeedback?.notificationOccurred('success') } catch {} },
  error() { try { tg?.HapticFeedback?.notificationOccurred('error') } catch {} },
}

export function openTelegramLink(url) {
  if (!url) return
  if (tg && url.startsWith('https://t.me/')) tg.openTelegramLink(url)
  else openLink(url)
}

/** Внешние ссылки — только https; t.me открываем внутри Telegram. */
export function openLink(url) {
  if (!url || !url.startsWith('https://')) return
  if (url.startsWith('https://t.me/')) return openTelegramLink(url)
  if (tg?.openLink) tg.openLink(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}

/** Нативное подтверждение Telegram (с запасным window.confirm). */
export function confirmDialog(message) {
  return new Promise((resolve) => {
    if (tg?.showConfirm && tg.isVersionAtLeast?.('6.2')) {
      try { tg.showConfirm(message, (ok) => resolve(!!ok)); return } catch {}
    }
    resolve(window.confirm(message))
  })
}

/** Параметр запуска: t_<id> — трек, a_<code> — альбом. */
export function startParam() {
  const fromTg = tg?.initDataUnsafe?.start_param
  let fromUrl = null
  try { fromUrl = new URLSearchParams(window.location.search).get('startapp') } catch {}
  const p = fromTg || fromUrl || ''
  return /^(t_\d{1,12}|a_[A-Za-z0-9_-]{8,16})$/.test(p) ? p : null
}

let backHandler = null
export function setBackButton(handler) {
  const bb = tg?.BackButton
  if (!bb) return
  if (backHandler) bb.offClick(backHandler)
  backHandler = handler
  if (handler) { bb.onClick(handler); bb.show() } else bb.hide()
}
