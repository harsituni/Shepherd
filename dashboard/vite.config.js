import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
    port: 5173,
    strictPort: true,
    // Allow importing ../shared/fixtures from outside the dashboard root.
    fs: { allow: ['..'] },
  },
})
