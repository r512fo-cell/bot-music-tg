<script setup>
// Создание / редактирование альбома: название с живой проверкой + выбор иконки.
import { computed, nextTick, ref, watch } from 'vue'
import { useUi } from '../stores/ui'
import { useAlbums } from '../stores/albums'
import { useSession } from '../stores/session'
import { errorText, t } from '../lib/i18n'
import { validateAlbumName } from '../lib/validate'
import { haptic } from '../lib/telegram'
import AlbumArt from './AlbumArt.vue'
import Icon from './Icon.vue'

const ui = useUi()
const albums = useAlbums()
const session = useSession()

const name = ref('')
const icon = ref('')
const touched = ref(false)
const saving = ref(false)
const serverError = ref('')
const input = ref(null)

const opts = computed(() => ui.editor)
const isEdit = computed(() => opts.value?.mode === 'edit')
const icons = computed(() => session.config.album_icons || ['🎧'])
const max = computed(() => session.config.album_name_max || 32)
const punct = computed(() => session.config.album_punct || "!#&'(),+-.:?_")
const check = computed(() => validateAlbumName(name.value, { max: max.value, punct: punct.value }))
const shownError = computed(() => serverError.value || (touched.value && check.value.error ? check.value.error : ''))
const preview = computed(() => ({ id: 0, name: check.value.value || t('album.name_placeholder'), icon: icon.value, covers: opts.value?.album?.covers || [] }))
const atLimit = computed(() => albums.restricted || (!isEdit.value && !albums.canCreate))

watch(opts, async (o) => {
  if (!o) return
  name.value = o.album?.name || ''
  icon.value = o.album?.icon || icons.value[0]
  touched.value = false
  serverError.value = ''
  saving.value = false
  if (o.mode === 'create' && albums.items == null) albums.load().catch(() => {})
  await nextTick()
  setTimeout(() => input.value?.focus(), 350)
})
watch(name, () => { serverError.value = ''; if (name.value) touched.value = true })

async function save() {
  touched.value = true
  if (check.value.error || saving.value || atLimit.value) { haptic.error(); return }
  saving.value = true
  try {
    if (isEdit.value) {
      const album = await albums.update(opts.value.album.id, { name: check.value.value, icon: icon.value })
      opts.value.onSaved?.(album)
      ui.toast(t('album.saved'))
    } else {
      const album = await albums.create(check.value.value, icon.value, opts.value.trackId)
      opts.value.onSaved?.(album)
      ui.toast(opts.value.trackId ? t('album.created_with_track', { name: album.name }) : t('album.created'))
    }
    ui.closeEditor()
  } catch (e) {
    serverError.value = e.message
    haptic.error()
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Transition name="sheet">
    <div v-if="opts" class="backdrop" @click.self="ui.closeEditor()">
      <form class="sheet glass" role="dialog" aria-modal="true" @submit.prevent="save">
        <div class="grab" />
        <h3>{{ isEdit ? t('album.edit_title') : t('album.create_title') }}</h3>

        <div class="top">
          <AlbumArt :album="preview" radius="18px" class="preview" />
          <div class="field">
            <label for="album-name" class="label">{{ t('album.name') }}</label>
            <div class="input-wrap" :class="{ invalid: shownError }">
              <input
                id="album-name"
                ref="input"
                v-model="name"
                :maxlength="max + 8"
                autocomplete="off"
                enterkeyhint="done"
                :placeholder="t('album.name_placeholder')"
              />
              <span class="counter tnum" :class="{ over: check.length > max }">{{ check.length }}/{{ max }}</span>
            </div>
            <p v-if="shownError" class="error">{{ errorText({ message: shownError }, { n: albums.limit, max }) }}</p>
            <p v-else class="hint">{{ t('album.name_hint', { chars: punct.split('').join(' ') }) }}</p>
          </div>
        </div>

        <div class="label">{{ t('album.icon') }}</div>
        <div class="icons">
          <button
            v-for="i in icons"
            :key="i"
            type="button"
            class="icon-choice"
            :class="{ on: icon === i }"
            :aria-pressed="icon === i"
            @click="icon = i; haptic.select()"
          >{{ i }}</button>
        </div>

        <p v-if="atLimit" class="error center">{{ albums.blockText }}</p>
        <div class="buttons">
          <button type="button" class="btn" @click="ui.closeEditor()">{{ t('common.cancel') }}</button>
          <button type="submit" class="btn btn-primary" :disabled="saving || atLimit || (touched && !!check.error)">
            <Icon :name="isEdit ? 'check' : 'plus'" :size="18" />{{ isEdit ? t('common.save') : t('album.create') }}
          </button>
        </div>
      </form>
    </div>
  </Transition>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(0, 0, 0, 0.55);
  -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px);
  display: flex; align-items: flex-end; justify-content: center;
}
.sheet {
  width: 100%; max-width: 560px;
  padding: 8px 18px calc(var(--safe-bottom) + 16px);
  border-radius: 24px 24px 0 0;
  border: 1px solid var(--border); border-bottom: 0;
  background: rgba(22, 22, 28, 0.9);
}
.grab { width: 38px; height: 5px; border-radius: 3px; background: var(--surface-3); margin: 0 auto 14px; }
h3 { font-size: 19px; font-weight: 700; margin-bottom: 16px; }
.top { display: flex; gap: 14px; align-items: flex-start; }
.preview { width: 84px; flex-shrink: 0; }
.field { flex: 1; min-width: 0; }
.label { font-size: 13px; color: var(--text-2); font-weight: 600; margin-bottom: 6px; display: block; }
.input-wrap {
  display: flex; align-items: center; gap: 8px; height: 46px; padding: 0 12px;
  border-radius: 12px; background: var(--surface-2); border: 1px solid var(--border);
  transition: border-color 0.2s;
}
.input-wrap:focus-within { border-color: rgb(var(--accent-rgb) / 0.6); }
.input-wrap.invalid { border-color: rgba(255, 92, 108, 0.7); }
input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; }
.counter { font-size: 12px; color: var(--text-3); }
.counter.over { color: var(--danger); }
.hint, .error { font-size: 12px; margin-top: 6px; line-height: 1.35; }
.hint { color: var(--text-3); }
.error { color: var(--danger); }
.center { text-align: center; margin-top: 12px; }
.icons { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-top: 4px; }
.icon-choice {
  aspect-ratio: 1; border-radius: 14px; font-size: 22px;
  background: var(--surface); border: 1px solid var(--border);
  transition: transform 0.15s var(--ease-spring), background 0.2s, border-color 0.2s;
}
.icon-choice.on { background: rgb(var(--accent-rgb) / 0.22); border-color: rgb(var(--accent-rgb) / 0.7); transform: scale(1.06); }
.buttons { display: grid; grid-template-columns: 1fr 1.4fr; gap: 10px; margin-top: 18px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.3s var(--ease); }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.4s var(--ease); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(100%); }
</style>
