import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Spotify rejects `localhost` as a redirect host, and session cookies are issued for
// whatever host the OAuth callback lands on, so the dev server binds 127.0.0.1 and
// proxies both /api and /auth to the backend. Always open http://127.0.0.1:5173.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
      '/auth': { target: backend, changeOrigin: false },
    },
  },
})
