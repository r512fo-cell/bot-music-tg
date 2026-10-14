import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { initTelegram } from './lib/telegram'
import './styles/main.css'
import './styles/themes.css'

initTelegram()

createApp(App).use(createPinia()).use(router).mount('#app')
