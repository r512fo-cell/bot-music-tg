<script setup>
import { useUi } from '../stores/ui'
const ui = useUi()
</script>

<template>
  <Transition name="toast">
    <div v-if="ui.toastText" class="toast glass" role="status">{{ ui.toastText }}</div>
  </Transition>
</template>

<style scoped>
.toast {
  position: fixed;
  z-index: 100;
  left: 50%;
  top: calc(var(--safe-top) + 14px);
  transform: translateX(-50%);
  padding: 10px 18px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 500;
  border: 1px solid var(--border);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  max-width: calc(100% - 32px);
}
.toast-enter-active, .toast-leave-active { transition: opacity 0.25s, transform 0.35s var(--ease); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, -12px); }
</style>
