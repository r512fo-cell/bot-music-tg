<script setup>
defineProps({ active: { type: Boolean, default: true } })
</script>

<template>
  <span class="eq" :class="{ paused: !active }" aria-hidden="true"><i /><i /><i /></span>
</template>

<style scoped>
.eq { display: inline-flex; align-items: flex-end; gap: 2px; height: 14px; }
.eq i {
  width: 3px;
  height: 100%;
  border-radius: 2px;
  background: currentColor;
  transform-origin: bottom;
  animation: eq 0.9s ease-in-out infinite;
}
.eq i:nth-child(2) { animation-delay: -0.3s; }
.eq i:nth-child(3) { animation-delay: -0.6s; }
.eq.paused i { animation-play-state: paused; }
@keyframes eq { 0%, 100% { transform: scaleY(0.3); } 50% { transform: scaleY(1); } }
</style>
