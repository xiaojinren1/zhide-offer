import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendPort = Number(process.env.JOBAGENT_PORT || 8000)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': `http://127.0.0.1:${backendPort}`
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
