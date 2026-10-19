import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Le navigateur ne doit jamais garder une vieille version de l'application :
// pendant la démonstration, chaque rechargement sert le dernier build.
const noCache = { 'Cache-Control': 'no-store' }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true, port: 5173, headers: noCache },
  preview: { host: true, port: 4173, headers: noCache },
})
