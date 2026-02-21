import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { registerSW } from 'virtual:pwa-register'
import App from './App.vue'
import router from './router'
import './assets/main.css'
import './assets/app.css'

const updateSW = registerSW({
  immediate: true
})

updateSW(true)

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
