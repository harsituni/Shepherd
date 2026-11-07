import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { shepherdVersion } from '../shared/gitVersion.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __SHEPHERD_VERSION__: JSON.stringify(shepherdVersion()),
  },
  // Relative asset paths so dist/index.html also works under VS Code Live Server.
  base: './',
  build: {
    chunkSizeWarningLimit: 1500, // maplibre-gl alone is ~1 MB
    rolldownOptions: {
      output: {
        // Emit the MapLibre worker as .js: simple static servers (e.g. Live Server)
        // may not send .mjs with a JavaScript MIME type, which breaks the worker.
        assetFileNames: (asset) =>
          asset.names?.[0]?.endsWith('.mjs') ? 'assets/[name]-[hash].js' : 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    host: true, // reachable from real phones on the same Wi-Fi
    // Allow importing ../shared/fixtures from outside the phone root.
    fs: { allow: ['..'] },
  },
})
