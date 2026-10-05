import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// 开发期：5173 端口跑页面，/cases、/assist 请求代理到 8000 的 FastAPI
// 生产期：npm run build 产物在 dist/，由 FastAPI 的 StaticFiles 同源托管
export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入：只打包实际用到的组件及其样式（tree-shaking）
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/auth': { target: 'http://localhost:8000', changeOrigin: true },
      '/cases': { target: 'http://localhost:8000', changeOrigin: true },
      '/assist': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
  },
})
