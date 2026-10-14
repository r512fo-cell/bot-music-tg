<script setup>
// Число просмотров на обложке открытого альбома (у закрытых сервер не присылает views).
import { compact } from '../lib/format'
import { t } from '../lib/i18n'
import Icon from './Icon.vue'

defineProps({ views: { type: Number, default: null } })
</script>

<template>
  <span v-if="views != null" class="views-badge" :title="t('album.views_hint')">
    <Icon name="eye" :size="12" />{{ compact(views) }}
  </span>
</template>

<style scoped>
.views-badge {
  position: absolute;
  right: 7px;
  bottom: 7px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: rgba(10, 10, 14, 0.55);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  pointer-events: none;
}
</style>
