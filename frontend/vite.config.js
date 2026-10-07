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
  // vitest 配置（仅测试时生效）：组件冒烟测试跑在 happy-dom 里，
  // element-plus 需内联走 vite 管道才能处理其 CSS import
  test: {
    environment: 'happy-dom',
    server: { deps: { inline: ['element-plus'] } },
  },
  server: {
    port: 5173,
    proxy: {
      '/auth': { target: 'http://localhost:8000', changeOrigin: true },
      '/cases': { target: 'http://localhost:8000', changeOrigin: true },
      '/assist': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE 流式关键：禁用压缩和缓冲，让代理逐 chunk 透传
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              // 删除 content-length，让浏览器按 chunk 读取
              delete proxyRes.headers['content-length']
              delete proxyRes.headers['content-encoding']
            }
          })
        },
      },
      '/admin': { target: 'http://localhost:8000', changeOrigin: true },
      '/stats': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
  },
})
