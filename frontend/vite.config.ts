import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'

const backend = 'http://localhost:8000'

export default defineConfig({
  plugins: [
    react(),
    {
      // /app without the slash would get the website: send it to /app/
      name: 'app-slash',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/app') {
            res.writeHead(301, { Location: '/app/' }).end()
            return
          }
          next()
        })
      },
    },
  ],
  // Two pages: the website on / and the app on /app/
  build: { rollupOptions: { input: { site: resolve(__dirname, 'index.html'), app: resolve(__dirname, 'app/index.html') } } },
  server: {
    proxy: { '/api': backend },
  },
})
