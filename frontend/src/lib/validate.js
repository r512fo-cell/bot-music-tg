// Клиентская проверка названия альбома — зеркало серверной (validators.py).
// Сервер всё равно проверяет повторно; здесь — мгновенная подсказка пользователю.
const esc = (s) => s.replace(/[-\\^\]]/g, '\\$&')

export function validateAlbumName(raw, { max = 32, punct = "!#&'(),+-.:?_" } = {}) {
  const value = (raw || '').normalize('NFKC').replace(/\s+/g, ' ').trim()
  const len = Array.from(value).length
  let error = ''
  if (!len) error = 'album_name_empty'
  else if (len > max) error = 'album_name_long'
  else if (!new RegExp(`^[\\p{L}\\p{Mn}\\p{Mc}\\p{Nd} ${esc(punct)}]+$`, 'u').test(value)) error = 'album_name_chars'
  else if (!/[\p{L}\p{N}]/u.test(value)) error = 'album_name_alnum'
  else if (/(.)\1{4,}/u.test(value)) error = 'album_name_repeat'
  else if (new RegExp(`[${esc(punct)}]{3,}`, 'u').test(value)) error = 'album_name_punct'
  return { value, length: len, error }
}
