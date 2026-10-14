import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUi = defineStore('ui', () => {
  const actionTrack = ref(null)
  const actionContext = ref(null) // { albumId, onRemoved } — действия внутри альбома
  const pickerTrack = ref(null) // «Добавить в альбом»
  const editor = ref(null) // { mode: 'create'|'edit', album?, trackId? }
  const toastText = ref('')
  let timer = null

  function openActions(track, context = null) { actionTrack.value = track; actionContext.value = context }
  function closeActions() { actionTrack.value = null; actionContext.value = null }
  function openPicker(track) { pickerTrack.value = track }
  function closePicker() { pickerTrack.value = null }
  function openEditor(opts) { editor.value = opts }
  function closeEditor() { editor.value = null }
  function toast(text) {
    toastText.value = text
    clearTimeout(timer)
    timer = setTimeout(() => { toastText.value = '' }, 2400)
  }
  return {
    actionTrack, actionContext, pickerTrack, editor, toastText,
    openActions, closeActions, openPicker, closePicker, openEditor, closeEditor, toast,
  }
})
