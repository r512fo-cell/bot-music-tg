import { createMemoryHistory, createRouter } from 'vue-router'
import HomeView from './views/HomeView.vue'
import { useSession } from './stores/session'

// Memory history: адресная строка в Mini App не нужна, а hash занят Telegram (tgWebAppData).
export const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { tab: 'home', root: true } },
    { path: '/search', name: 'search', component: () => import('./views/SearchView.vue'), meta: { tab: 'search', root: true } },
    { path: '/library', name: 'library', component: () => import('./views/LibraryView.vue'), meta: { tab: 'library', root: true } },
    { path: '/profile', name: 'profile', component: () => import('./views/ProfileView.vue'), meta: { tab: 'profile', root: true } },
    { path: '/tracks', name: 'tracks', component: () => import('./views/TracksView.vue'), meta: { tab: 'home' } },
    { path: '/albums', name: 'albums', component: () => import('./views/AlbumsView.vue'), meta: { tab: 'home' } },
    { path: '/album/:id(\\d+)', name: 'album', component: () => import('./views/AlbumView.vue'), meta: { tab: 'library' } },
    { path: '/shared/:code([A-Za-z0-9_-]{8,16})', name: 'shared-album', component: () => import('./views/AlbumView.vue'), meta: { tab: 'library' } },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('./views/AdminView.vue'),
      meta: { tab: 'profile' },
      beforeEnter: () => (useSession().isAdmin ? true : { name: 'profile' }),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// Запоминаем прокрутку для возврата назад
const positions = new Map()
let goingBack = false
let depth = 0 // глубина push-навигации: memory history не сообщает, есть ли куда возвращаться

const originalPush = router.push.bind(router)
router.push = (to) => originalPush(to).then((failure) => { if (!failure) depth++; return failure })

export const canGoBack = () => depth > 0
export function goBack() {
  depth = Math.max(0, depth - 1)
  goingBack = true
  router.back()
}

router.beforeEach((to, from) => { positions.set(from.fullPath, window.scrollY) })
router.afterEach((to) => {
  const y = goingBack || to.meta.root ? positions.get(to.fullPath) || 0 : 0
  goingBack = false
  requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, y)))
})
