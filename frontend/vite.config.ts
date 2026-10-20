import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Le navigateur ne doit jamais garder une vieille version de l'application :
// pendant la démonstration, chaque rechargement sert le dernier build.
const noCache = { 'Cache-Control': 'no-store' }

// En développement (npm run dev), Vite joue le rôle du relais nginx : mêmes chemins, même
// origine, donc le cookie de session part avec chaque appel. Services lancés en local.
const relay = {
  '/api': 'http://localhost:8000',
  '/auth': 'http://localhost:8300',
  '/detector': { target: 'http://localhost:8100', rewrite: (p: string) => p.replace(/^\/detector/, '') },
  '/remediation': { target: 'http://localhost:8200', rewrite: (p: string) => p.replace(/^\/remediation/, '') },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true, port: 5173, headers: noCache, proxy: relay },
  preview: { host: true, port: 4173, headers: noCache, proxy: relay },
})
