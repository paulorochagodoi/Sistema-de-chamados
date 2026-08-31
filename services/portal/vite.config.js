import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Em produção o nginx do container serve o bundle e faz o proxy de /api para o
// itsm-bridge; no `npm run dev` o proxy abaixo cumpre o mesmo papel.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
