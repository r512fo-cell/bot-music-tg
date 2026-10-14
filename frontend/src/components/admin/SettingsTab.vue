<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../../lib/api'
import { errorText, t } from '../../lib/i18n'
import { confirmDialog, haptic } from '../../lib/telegram'
import { useSession } from '../../stores/session'
import { useUi } from '../../stores/ui'
import Icon from '../Icon.vue'
import { applyTheme, seasonByDate } from '../../lib/theme'

const ui = useUi()
const session = useSession()
const loaded = ref(false)
const maintenance = ref(false)
const text = ref('')
const savedText = ref('')
const saving = ref(false)
const dirtyText = computed(() => text.value !== savedText.value)

// ---- тема оформления
const theme = ref(session.config.theme || 'default')
const THEME_LIST = [
  { id: 'default', emoji: '🎧', colors: ['#8b7bff', '#c174ff', '#ff6fb1'] },
  { id: 'auto', emoji: '🗓️', colors: [] },
  { id: 'autumn', emoji: '🍂', colors: ['#ffa149', '#ff7a3d', '#e5533d'] },
  { id: 'winter', emoji: '❄️', colors: ['#6cc9ff', '#8aa9ff', '#c3e9ff'] },
  { id: 'spring', emoji: '🌸', colors: ['#74de95', '#b5e27a', '#ff9cc6'] },
  { id: 'summer', emoji: '☀️', colors: ['#ffc940', '#ff9f3f', '#2fd3c5'] },
]
const autoNow = seasonByDate()
async function pickTheme(id) {
  if (id === theme.value) return
  const prev = theme.value
  theme.value = id
  applyTheme(id)
  haptic.select()
  try {
    await api.admin.saveTheme(id)
    session.config = { ...session.config, theme: id }
    ui.toast(t('admin.theme_saved'))
  } catch (e) {
    theme.value = prev
    applyTheme(prev)
    ui.toast(errorText(e))
  }
}

async function load() {
  const s = await api.admin.settings()
  maintenance.value = s.maintenance
  text.value = savedText.value = s.maintenance_text
  loaded.value = true
}

async function save(nextMaintenance) {
  saving.value = true
  try {
    const s = await api.admin.saveSettings({ maintenance: nextMaintenance, maintenance_text: text.value })
    maintenance.value = s.maintenance
    text.value = savedText.value = s.maintenance_text
    session.config = { ...session.config, maintenance: s.maintenance, maintenance_text: s.maintenance_text }
    haptic.success()
    ui.toast(s.maintenance ? t('admin.maint_on_toast') : t('admin.maint_off_toast'))
  } catch (e) {
    ui.toast(errorText(e))
  } finally { saving.value = false }
}

async function onToggle(e) {
  const want = e.target.checked
  e.target.checked = maintenance.value // состояние меняем только после подтверждения
  if (want && !(await confirmDialog(t('admin.maint_confirm')))) return
  await save(want)
}

onMounted(() => load().catch((e) => ui.toast(errorText(e))))
</script>

<template>
  <section class="card card-pad themes">
    <div class="m-head">
      <span class="m-icon theme-icon"><Icon name="sparkles" :size="20" /></span>
      <div class="grow">
        <b>{{ t('admin.theme_title') }}</b>
        <p class="r-sub">{{ t('admin.theme_desc') }}</p>
      </div>
    </div>
    <div class="theme-grid" role="radiogroup">
      <button
        v-for="th in THEME_LIST"
        :key="th.id"
        type="button"
        role="radio"
        :aria-checked="theme === th.id"
        class="theme-card"
        :class="{ on: theme === th.id }"
        @click="pickTheme(th.id)"
      >
        <span class="theme-emoji">{{ th.emoji }}</span>
        <span class="theme-name">{{ t(`admin.theme_${th.id}`) }}</span>
        <span v-if="th.colors.length" class="dots">
          <i v-for="c in th.colors" :key="c" :style="{ background: c }" />
        </span>
        <span v-else class="auto-note">{{ t(`admin.theme_${autoNow}`) }}</span>
      </button>
    </div>
  </section>

  <section class="card card-pad" :class="{ warn: maintenance }">
    <div class="m-head">
      <span class="m-icon"><Icon name="wrench" :size="20" /></span>
      <div class="grow">
        <b>{{ t('admin.maint_title') }}</b>
        <p class="r-sub">{{ maintenance ? t('admin.maint_state_on') : t('admin.maint_state_off') }}</p>
      </div>
    </div>

    <label class="switch-row main-switch">
      <span>{{ t('admin.maint_switch') }}</span>
      <input type="checkbox" :checked="maintenance" :disabled="!loaded || saving" @change="onToggle" />
      <span class="switch warn" />
    </label>
    <p class="hint">{{ t('admin.maint_hint') }}</p>

    <div class="field msg">
      <div class="field-label"><span>{{ t('admin.maint_text') }}</span><small>{{ text.length }}/300</small></div>
      <textarea v-model="text" class="input short" maxlength="300" rows="3" :placeholder="t('maintenance.text')" />
      <button v-if="dirtyText" class="btn" :disabled="saving" @click="save(maintenance)"><Icon name="check" :size="17" />{{ t('common.save') }}</button>
    </div>
  </section>
</template>

<style scoped>
.themes { margin-bottom: 12px; }
.theme-icon { color: var(--accent); background: rgb(var(--accent-rgb) / 0.15); }
.theme-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.theme-card {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 10px; min-width: 0;
  border-radius: 14px; background: var(--surface); border: 1px solid var(--border); text-align: left;
  transition: border-color 0.2s, background 0.2s, transform 0.15s var(--ease);
}
.theme-card:active { transform: scale(0.96); }
.theme-card.on { border-color: var(--accent); background: rgb(var(--accent-rgb) / 0.1); }
.theme-emoji { font-size: 20px; line-height: 1; }
.theme-name { font-size: 13px; font-weight: 700; }
.dots { display: flex; gap: 3px; }
.dots i { width: 12px; height: 12px; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.15); }
.auto-note { font-size: 11px; color: var(--text-3); }
.warn { border-color: rgba(245, 165, 36, 0.45); background: rgba(245, 165, 36, 0.06); }
.m-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.m-icon { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: rgba(245, 165, 36, 0.15); color: #f5a524; }
.m-head b { font-size: 16px; }
.main-switch { font-size: 15px; font-weight: 600; padding: 8px 0; }
.msg { margin-top: 16px; margin-bottom: 0; }
textarea.input.short { min-height: 80px; }
</style>
