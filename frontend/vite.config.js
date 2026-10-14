import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import pkg from './package.json' with { type: 'json' }

export default defineConfig({
  plugins: [vue()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: {
    target: 'es2020',
    outDir: 'dist',
    assetsInlineLimit: 2048,
    sourcemap: false,
    cssCodeSplit: true,
    rollupOptions: {
      output: {
        manualChunks: { vendor: ['vue', 'vue-router', 'pinia'] },
      },
    },
  },
  server: {
    proxy: { '/api': 'http://localhost:3000', '/media': 'http://localhost:3000' },
  },
})
