import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  // 必须是绝对路径。计划原写 './'：history 路由下在 /b/书名/pipeline 刷新，
  // 浏览器会去要 /b/书名/assets/xx.js，SPA 兜底回的是 index.html，整页空白。
  // 后端本来就只在根上挂 /assets，所以相对路径换不来「挂任何前缀」。
  base: '/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
