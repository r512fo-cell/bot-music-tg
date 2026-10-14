<script setup>
defineProps({ count: { type: Number, default: 6 } })
</script>

<template>
  <div v-for="i in count" :key="i" class="sk-row">
    <div class="skeleton sk-cover" />
    <div class="sk-meta">
      <div class="skeleton sk-line" :style="{ width: 40 + ((i * 37) % 45) + '%' }" />
      <div class="skeleton sk-line small" :style="{ width: 25 + ((i * 23) % 30) + '%' }" />
    </div>
  </div>
</template>

<style scoped>
.sk-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; }
.sk-cover { width: 48px; height: 48px; border-radius: 10px; }
.sk-meta { flex: 1; display: grid; gap: 8px; }
.sk-line { height: 13px; border-radius: 6px; }
.sk-line.small { height: 11px; }
</style>
