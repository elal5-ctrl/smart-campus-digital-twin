import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendUrl = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.VITE_DEV_HOST ?? '127.0.0.1',
    port: 5555,
    proxy: {
      '/api': backendUrl,
      '/health': backendUrl,
    },
  },
  preview: {
    host: process.env.VITE_PREVIEW_HOST ?? '127.0.0.1',
    port: 5555,
  },
});
