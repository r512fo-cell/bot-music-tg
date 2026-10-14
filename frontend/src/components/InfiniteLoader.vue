<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({ disabled: { type: Boolean, default: false } })
const emit = defineEmits(['load'])
const el = ref(null)
let io = null

onMounted(() => {
  io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && !props.disabled) emit('load')
  }, { rootMargin: '600px 0px' })
  io.observe(el.value)
})
onBeforeUnmount(() => io?.disconnect())
</script>

<template><div ref="el" class="sentinel" /></template>

<style scoped>
.sentinel { height: 1px; }
</style>
