<template>
  <!-- Рождественская шапочка: сидит на углу первой буквы заголовка -->
  <svg class="hat" viewBox="0 0 64 56" aria-hidden="true">
    <path d="M8 40 C 14 18, 30 6, 48 10 C 54 12, 58 20, 56 30 C 50 24, 44 24, 40 28 C 34 34, 30 38, 30 44 Z" fill="#e2333f" />
    <path d="M40 28 C 44 24, 50 24, 56 30 C 54 22, 50 15, 44 13 C 46 18, 44 23, 40 28 Z" fill="#b8202c" opacity="0.6" />
    <rect x="3" y="38" width="34" height="11" rx="5.5" fill="#f4f8ff" />
    <circle cx="57" cy="32" r="6.5" fill="#f4f8ff" />
  </svg>
</template>

<style scoped>
.hat {
  position: absolute;
  left: -0.32em;
  top: -0.66em;
  width: 1.08em;
  height: auto;
  transform: rotate(-16deg);
  filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.35));
  pointer-events: none;
}
</style>
