import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: path.resolve(__dirname, 'popup.html'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name].[ext]',
      },
    },
    // Chrome Extension CSP doesn't allow eval
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
      },
    },
    // Copy public directory (manifest.json, icons) to dist
    copyPublicDir: true,
  },
  publicDir: 'public',
  server: {
    port: 5173,
    strictPort: true,
  },
})

