import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react()],
  resolve: {
    // "@/..." resolves to src/, so imports do not turn into ../../../ chains
    // as the module tree deepens.
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    // Proxy /api to Django in development. Keeps the browser on one origin,
    // so CORS and cookie behaviour in dev match production behind a reverse
    // proxy rather than being a special case that hides problems.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
})
