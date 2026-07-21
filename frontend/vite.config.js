import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev:   `npm run dev`   -> Vite dev server on :5173 with hot reload. The proxy below
//        forwards API calls to the FastAPI server (api.py) on :8000, so the front-end
//        can use plain relative paths ("/chat") with no CORS or absolute URLs.
// Build: `npm run build` -> emits the static bundle straight into ../web, which api.py
//        serves from the same origin. One `python api.py` then runs API + UI together.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/chat': 'http://127.0.0.1:8000',
      '/refresh': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: '../web',
    emptyOutDir: true,
  },
})
