<script setup>
import { computed, onMounted } from 'vue'
import { useSession } from '../stores/session'
import { date, listenTime, num } from '../lib/format'
import { t, tp, locale } from '../lib/i18n'
import { haptic } from '../lib/telegram'
import Icon from '../components/Icon.vue'

const session = useSession()
const u = computed(() => session.user)
const vip = computed(() => session.isVip)
const limits = computed(() => session.config.upload_limits || { batch: 5, day: 10 })
const restricted = computed(() => Object.entries(session.restrictions).filter(([, on]) => on).map(([k]) => k))
const s = computed(() => session.stats)
const days = computed(() => (u.value ? Math.max(1, Math.ceil((Date.now() / 1000 - u.value.created_at) / 86400)) : 0))
const version = __APP_VERSION__
const langs = [{ id: 'ru', label: 'Русский', flag: '🇷🇺' }, { id: 'en', label: 'English', flag: '🇬🇧' }]
function setLang(id) { haptic.select(); session.setLanguage(id) }

onMounted(() => {
  session.refresh().catch(() => {})
})
</script>

<template>
  <div class="page profile" :class="{ vip }">
    <!-- Premium: мягкое «северное сияние» и несколько искр за шапкой профиля -->
    <div v-if="vip" class="vip-bg" aria-hidden="true">
      <i v-for="n in 7" :key="n" class="spark" :class="'s' + n">✦</i>
    </div>
    <div class="hero">
      <div class="avatar-ring">
        <div class="avatar">
          <img v-if="session.avatar" :src="session.avatar" alt="" />
          <span v-else-if="session.initials">{{ session.initials }}</span>
          <Icon v-else name="user" :size="44" />
        </div>
        <span v-if="vip" class="vip-mark" :title="t('premium.badge')">⭐</span>
      </div>
      <h1 class="name">
        <span class="name-text">{{ session.displayName || t('profile.listener') }}</span>
        <Icon v-if="u?.is_premium && !vip" name="star" :size="18" class="premium" />
      </h1>
      <p v-if="u?.username" class="muted">@{{ u.username }}</p>
      <div class="chips">
        <span v-if="vip" class="role vip-chip">⭐ {{ t('premium.badge') }}</span>
        <span v-if="session.isAdmin" class="role"><Icon name="shield" :size="14" />{{ t('profile.admin') }}</span>
      </div>
    </div>

    <section v-if="vip" class="card perks">
      <div class="perks-head">{{ t('premium.perks_title') }}</div>
      <ul>
        <li><Icon name="upload" :size="17" />{{ t('premium.perk_uploads', limits) }}</li>
        <li><Icon name="album" :size="17" />{{ t('premium.perk_albums', { n: session.config.album_limit }) }}</li>
        <li><Icon name="sparkles" :size="17" />{{ t('premium.perk_style') }}</li>
      </ul>
    </section>

    <section v-if="restricted.length" class="card limits-card">
      <Icon name="lock" :size="18" class="limits-icon" />
      <div>
        <div class="limits-title">{{ t('profile.restricted_title') }}</div>
        <div class="muted small">{{ restricted.map((k) => t('profile.restricted_' + k)).join(' · ') }}</div>
      </div>
    </section>

    <div class="card since">
      <div class="since-icon"><Icon name="calendar" :size="20" /></div>
      <div>
        <div class="since-label muted">{{ t('profile.since') }}</div>
        <div class="since-date">{{ u ? date(u.created_at) : '—' }}</div>
      </div>
      <div class="since-days">
        <b class="tnum">{{ num(days) }}</b>
        <span class="muted">{{ tp(days, 'units.days', false) }}</span>
      </div>
    </div>

    <div class="stats">
      <div class="stat card">
        <Icon name="headphones" :size="20" class="stat-icon" />
        <b class="tnum">{{ s ? num(s.plays) : '—' }}</b>
        <span>{{ tp(s?.plays || 0, 'units.plays', false) }}</span>
      </div>
      <div class="stat card">
        <Icon name="music" :size="20" class="stat-icon" />
        <b class="tnum">{{ s ? num(s.unique_tracks) : '—' }}</b>
        <span>{{ t('profile.tracks_heard', { w: tp(s?.unique_tracks || 0, 'units.tracks', false) }) }}</span>
      </div>
      <div class="stat card">
        <Icon name="heart" :size="20" class="stat-icon" />
        <b class="tnum">{{ s ? num(s.favorites) : '—' }}</b>
        <span>{{ t('profile.in_favorites') }}</span>
      </div>
      <div class="stat card">
        <Icon name="clock" :size="20" class="stat-icon" />
        <b class="tnum">{{ s ? listenTime(s.seconds) : '—' }}</b>
        <span>{{ t('profile.listen_time') }}</span>
      </div>
    </div>

    <RouterLink v-if="session.isAdmin" to="/admin" class="btn btn-primary admin-btn">
      <Icon name="settings" :size="20" />{{ t('profile.admin_panel') }}
      <Icon name="chevron-right" :size="18" class="chev" />
    </RouterLink>


    <section class="card lang">
      <div class="lang-head"><Icon name="globe" :size="18" class="muted" />{{ t('profile.language') }}</div>
      <div class="lang-switch" role="radiogroup">
        <button v-for="l in langs" :key="l.id" role="radio" :aria-checked="locale === l.id" :class="{ on: locale === l.id }" @click="setLang(l.id)">
          <span>{{ l.flag }}</span>{{ l.label }}
        </button>
      </div>
    </section>

    <p class="version faint">{{ t('profile.version', { v: version }) }}</p>
  </div>
</template>

<style scoped>
.hero { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 24px 0 22px; gap: 4px; }
.avatar-ring { padding: 3px; border-radius: 50%; background: var(--accent-grad); box-shadow: 0 16px 50px -12px rgb(var(--accent-mid-rgb) / 0.6); margin-bottom: 12px; }
.avatar {
  width: 104px; height: 104px; border-radius: 50%; overflow: hidden;
  display: grid; place-items: center; background: var(--bg-elev);
  font-size: 36px; font-weight: 800; border: 3px solid var(--bg);
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.name { font-size: 25px; font-weight: 800; letter-spacing: -0.02em; display: inline-flex; align-items: center; gap: 6px; }
.premium { color: var(--accent-light); }
.chips { display: flex; gap: 6px; flex-wrap: wrap; justify-content: center; }
.chips:empty { display: none; }

/* ================= Premium ================= */
.profile { position: relative; }
.vip-bg {
  position: absolute; left: -16px; right: -16px; top: -40px; height: 340px; z-index: -1; pointer-events: none;
  background:
    radial-gradient(45% 55% at 28% 30%, rgba(255, 196, 92, 0.2), transparent 70%),
    radial-gradient(40% 50% at 75% 22%, rgba(255, 120, 190, 0.17), transparent 70%),
    radial-gradient(55% 60% at 55% 55%, rgba(140, 120, 255, 0.16), transparent 72%);
  -webkit-mask-image: linear-gradient(180deg, #000 55%, transparent);
  mask-image: linear-gradient(180deg, #000 55%, transparent);
}
.spark { position: absolute; font-style: normal; color: #ffe2a0; text-shadow: 0 0 8px rgba(255, 210, 120, 0.8); animation: twinkle 3.4s ease-in-out infinite; }
.s1 { left: 14%; top: 70px; font-size: 10px; }
.s2 { left: 82%; top: 64px; font-size: 13px; animation-delay: -1.1s; }
.s3 { left: 24%; top: 170px; font-size: 8px; animation-delay: -2.2s; }
.s4 { left: 72%; top: 160px; font-size: 9px; animation-delay: -0.6s; }
.s5 { left: 48%; top: 40px; font-size: 8px; animation-delay: -1.7s; }
.s6 { left: 90%; top: 210px; font-size: 7px; animation-delay: -2.8s; }
.s7 { left: 6%; top: 220px; font-size: 8px; animation-delay: -0.3s; }
@keyframes twinkle { 0%, 100% { opacity: 0.15; transform: scale(0.6); } 50% { opacity: 0.95; transform: scale(1.1); } }

/* переливающаяся рамка аватара: вращается слой с conic-gradient (только transform) */
.vip .avatar-ring { position: relative; isolation: isolate; padding: 3.5px; background: none; overflow: visible;
  box-shadow: 0 18px 60px -14px rgba(255, 170, 90, 0.45), 0 0 40px -6px rgba(170, 130, 255, 0.35); }
.vip .avatar-ring::before {
  content: ''; position: absolute; inset: 0; z-index: -1; border-radius: 50%;
  background: conic-gradient(from 0deg, #ffd36e, #ff8ac2, #a98bff, #6fd3ff, #8ef0c0, #ffd36e);
  animation: ring-spin 6s linear infinite;
}
@keyframes ring-spin { to { transform: rotate(360deg); } }
.vip-mark {
  position: absolute; right: 2px; bottom: 4px; width: 30px; height: 30px; border-radius: 50%;
  display: grid; place-items: center; font-size: 15px;
  background: var(--bg-elev); border: 2px solid var(--bg); box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
}
/* имя переливается градиентом */
.vip .name-text {
  background: linear-gradient(90deg, #ffd36e, #ff9ac9, #b59bff, #7fd8ff, #ffd36e);
  background-size: 220% auto;
  -webkit-background-clip: text; background-clip: text;
  color: transparent; -webkit-text-fill-color: transparent;
  animation: name-flow 5s linear infinite;
}
@keyframes name-flow { to { background-position: 220% center; } }
.vip-chip {
  color: #ffe3a6; background: linear-gradient(90deg, rgba(255, 196, 92, 0.16), rgba(255, 130, 190, 0.14));
  border-color: rgba(255, 210, 130, 0.35);
}
.perks { margin-top: 0; margin-bottom: 10px; padding: 14px 16px; border-color: rgba(255, 210, 130, 0.22);
  background: linear-gradient(135deg, rgba(255, 196, 92, 0.07), rgba(170, 130, 255, 0.06)), var(--surface); }
.perks-head { font-weight: 700; font-size: 15px; margin-bottom: 8px; }
.perks ul { list-style: none; display: grid; gap: 8px; }
.perks li { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--text-2); }
.perks li .icon { color: #ffd27a; }
.limits-card { display: flex; align-items: center; gap: 12px; padding: 12px 16px; margin-bottom: 10px; }
.limits-icon { color: var(--danger); }
.limits-title { font-weight: 600; font-size: 14.5px; }
.small { font-size: 13px; }
@media (prefers-reduced-motion: reduce) {
  .vip .avatar-ring::before, .vip .name-text, .spark { animation: none; }
}
.role {
  display: inline-flex; align-items: center; gap: 5px; margin-top: 8px;
  padding: 5px 11px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
  color: var(--accent-light); background: rgb(var(--accent-rgb) / 0.16); border: 1px solid rgb(var(--accent-rgb) / 0.3);
}
.since { display: flex; align-items: center; gap: 14px; padding: 14px 16px; }
.since-icon { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: var(--surface-2); color: var(--accent); }
.since-label { font-size: 13px; }
.since-date { font-weight: 600; font-size: 16px; }
.since-days { margin-left: auto; text-align: right; display: flex; flex-direction: column; line-height: 1.15; }
.since-days b { font-size: 22px; }
.since-days span { font-size: 12.5px; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.stat { padding: 14px; display: flex; flex-direction: column; gap: 2px; }
.stat-icon { color: var(--text-3); margin-bottom: 8px; }
.stat b { font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }
.stat span { font-size: 13px; color: var(--text-2); }
.admin-btn { width: 100%; margin-top: 18px; height: 54px; font-size: 16px; justify-content: flex-start; padding: 0 18px; }
.chev { margin-left: auto; }
.version { text-align: center; font-size: 12.5px; margin-top: 24px; }
.lang { margin-top: 10px; padding: 14px 16px; }
.lang-head { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 15px; margin-bottom: 12px; }
.lang-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.lang-switch button {
  display: flex; align-items: center; justify-content: center; gap: 8px; height: 42px;
  border-radius: 12px; font-weight: 600; font-size: 14.5px; color: var(--text-2);
  background: var(--surface); border: 1px solid var(--border);
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.lang-switch button.on { color: var(--text); background: rgb(var(--accent-rgb) / 0.18); border-color: rgb(var(--accent-rgb) / 0.55); }
</style>
