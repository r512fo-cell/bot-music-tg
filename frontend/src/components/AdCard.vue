<script setup>
// Внешний вид рекламного блока: ₽ слева, текст по центру, кнопка справа (если задана).
import { t } from '../lib/i18n'

defineProps({ ad: { type: Object, required: true } })
const emit = defineEmits(['click'])
</script>

<template>
  <aside class="ad" :aria-label="t('ads.label')">
    <div class="ad-icon" aria-hidden="true">₽</div>
    <div class="ad-body">
      <div class="ad-title ellipsis">{{ ad.title }}</div>
      <p class="ad-text"><span class="ad-mark">{{ t('ads.mark') }}</span>{{ ad.text }}</p>
    </div>
    <button v-if="ad.button_text && ad.button_url" type="button" class="ad-btn" @click="emit('click')">
      {{ ad.button_text }}
    </button>
  </aside>
</template>

<style scoped>
.ad {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 12px;
  border-radius: 16px;
  background:
    linear-gradient(120deg, rgb(var(--accent-rgb) / 0.16), rgb(var(--accent-2-rgb) / 0.08) 60%, transparent),
    rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  overflow: hidden;
}
.ad-icon {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 19px;
  font-weight: 800;
  color: var(--on-accent);
  background: var(--accent-grad);
  box-shadow: 0 6px 16px -6px rgb(var(--accent-mid-rgb) / 0.7);
}
.ad-body { flex: 1; min-width: 0; }
.ad-title { font-size: 14px; font-weight: 700; letter-spacing: -0.01em; }
.ad-mark {
  display: inline-block;
  vertical-align: 1px;
  margin-right: 6px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
  padding: 0 4px;
  line-height: 14px;
  border-radius: 4px;
  border: 1px solid var(--border);
}
.ad-text {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.35;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ad-btn {
  flex-shrink: 0;
  max-width: 40%;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: #0b0b0f;
  background: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: transform 0.15s var(--ease);
}
.ad-btn:active { transform: scale(0.95); }
</style>
