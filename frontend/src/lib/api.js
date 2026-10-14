// HTTP-клиент: сессионный токен хранится только в памяти.
import { initData } from './telegram'

let token = null
let tokenExp = 0
let authPromise = null
let maintenanceHandler = null
let bannedHandler = null

/** Вызывается, если сервер ответил «режим обслуживания» посреди работы. */
export function onMaintenance(fn) { maintenanceHandler = fn }
/** Вызывается, если администратор заблокировал пользователя, пока приложение открыто. */
export function onBanned(fn) { bannedHandler = fn }

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

export async function authenticate() {
  if (authPromise) return authPromise
  authPromise = (async () => {
    const data = initData()
    if (!data) throw new ApiError(0, 'NO_TELEGRAM')
    const res = await fetch('/api/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: data }),
      credentials: 'omit',
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(res.status, body.detail || 'auth_failed')
    token = body.token
    tokenExp = body.expires_at
    return body
  })()
  try { return await authPromise } finally { authPromise = null }
}

async function ensureToken() {
  if (!token || Date.now() / 1000 > tokenExp - 120) await authenticate()
}

export async function request(path, { method = 'GET', body, signal, retry = true } = {}) {
  await ensureToken()
  const res = await fetch(path, {
    method,
    signal,
    credentials: 'omit',
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && retry) {
    token = null
    return request(path, { method, body, signal, retry: false })
  }
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (res.status === 503 && data.detail === 'maintenance') maintenanceHandler?.()
  if (res.status === 403 && data.detail === 'banned') bannedHandler?.()
  if (!res.ok) throw new ApiError(res.status, typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`)
  return data
}

const qs = (params) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : ''
}

// URL для <audio>/<img>: токен в query (заголовки там недоступны)
export async function mediaUrl(path) {
  await ensureToken()
  return `${path}${path.includes('?') ? '&' : '?'}t=${encodeURIComponent(token)}`
}
export const currentToken = () => token

export const api = {
  home: () => request('/api/home'),
  tracks: (params, signal) => request('/api/tracks' + qs(params), { signal }),
  track: (id) => request(`/api/tracks/${id}`),
  search: (params, signal) => request('/api/search' + qs(params), { signal }),
  play: (id) => request(`/api/tracks/${id}/play`, { method: 'POST' }),
  like: (id) => request(`/api/tracks/${id}/like`, { method: 'PUT' }),
  unlike: (id) => request(`/api/tracks/${id}/like`, { method: 'DELETE' }),
  me: () => request('/api/me'),
  settings: (body) => request('/api/me/settings', { method: 'PUT', body }),
  ads: (placement) => request(`/api/ads?placement=${placement}`),
  adClick: (id) => request(`/api/ads/${id}/click`, { method: 'POST' }),
  publicAlbums: (params) => request('/api/public/albums' + qs(params)),
  albums: {
    list: (trackId) => request('/api/albums' + qs({ track_id: trackId })),
    get: (id) => request(`/api/albums/${id}`),
    create: (body) => request('/api/albums', { method: 'POST', body }),
    update: (id, body) => request(`/api/albums/${id}`, { method: 'PATCH', body }),
    remove: (id) => request(`/api/albums/${id}`, { method: 'DELETE' }),
    addTrack: (id, trackId) => request(`/api/albums/${id}/tracks/${trackId}`, { method: 'PUT' }),
    removeTrack: (id, trackId) => request(`/api/albums/${id}/tracks/${trackId}`, { method: 'DELETE' }),
    share: (id) => request(`/api/albums/${id}/share`, { method: 'POST' }),
    visibility: (id, isPublic) => request(`/api/albums/${id}/visibility`, { method: 'POST', body: { public: isPublic } }),
    shared: (code) => request(`/api/shared/albums/${encodeURIComponent(code)}`),
    saveShared: (code) => request(`/api/shared/albums/${encodeURIComponent(code)}/save`, { method: 'POST' }),
  },
  favorites: (params) => request('/api/me/favorites' + qs(params)),
  history: () => request('/api/me/history'),
  admin: {
    stats: () => request('/api/admin/stats'),
    tracks: (params, signal) => request('/api/admin/tracks' + qs(params), { signal }),
    setHidden: (id, hidden) => request(`/api/admin/tracks/${id}/hidden`, { method: 'POST', body: { hidden } }),
    sync: (full) => request('/api/admin/sync', { method: 'POST', body: { full } }),
    users: (params) => request('/api/admin/users' + qs(params)),
    user: (id) => request(`/api/admin/users/${id}`),
    updateUser: (id, body) => request(`/api/admin/users/${id}`, { method: 'PATCH', body }),
    ads: () => request('/api/admin/ads'),
    createAd: (body) => request('/api/admin/ads', { method: 'POST', body }),
    updateAd: (id, body) => request(`/api/admin/ads/${id}`, { method: 'PUT', body }),
    deleteAd: (id) => request(`/api/admin/ads/${id}`, { method: 'DELETE' }),
    broadcasts: () => request('/api/admin/broadcasts'),
    broadcastTest: (body) => request('/api/admin/broadcasts/test', { method: 'POST', body }),
    broadcast: (body) => request('/api/admin/broadcasts', { method: 'POST', body }),
    cancelBroadcast: () => request('/api/admin/broadcasts/cancel', { method: 'POST' }),
    settings: () => request('/api/admin/settings'),
    saveSettings: (body) => request('/api/admin/settings', { method: 'PUT', body }),
    saveTheme: (theme) => request('/api/admin/settings/theme', { method: 'PUT', body: { theme } }),
    rules: () => request('/api/admin/hide-rules'),
    previewRule: (body) => request('/api/admin/hide-rules/preview', { method: 'POST', body }),
    addRule: (body) => request('/api/admin/hide-rules', { method: 'POST', body }),
    deleteRule: (id) => request(`/api/admin/hide-rules/${id}`, { method: 'DELETE' }),
    clearTracks: (skipHistory) => request('/api/admin/tracks/clear', { method: 'POST', body: { confirm: 'CLEAR', skip_history: skipHistory } }),
    historyReset: () => request('/api/admin/tracks/history-reset', { method: 'POST' }),
    submissions: (params) => request('/api/admin/submissions' + qs(params)),
    submissionsCount: () => request('/api/admin/submissions/count'),
    approve: (id, exclude) => request(`/api/admin/submissions/${id}/approve`, { method: 'POST', body: { exclude } }),
    reject: (id, reason) => request(`/api/admin/submissions/${id}/reject`, { method: 'POST', body: { reason } }),
    content: {
      status: () => request('/api/admin/content/status'),
      resolve: (url) => request('/api/admin/content/resolve', { method: 'POST', body: { url } }),
      page: (rid, page) => request(`/api/admin/content/resolve/${rid}?page=${page}`),
      start: (body) => request('/api/admin/content/import', { method: 'POST', body }),
      jobs: () => request('/api/admin/content/jobs'),
      cancel: (id) => request(`/api/admin/content/jobs/${id}/cancel`, { method: 'POST' }),
    },
  },
}
