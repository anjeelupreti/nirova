import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    // 0.0.0.0 when asked, so the dev server is reachable from outside a
    // container. Harmless on a host: Vite still prints the localhost URL.
    host: true,
    // 5174, so the staff console on 5173 and this can run side by side. They
    // are separate origins in development for the same reason they are
    // separate bundles in production: a patient should never be served the
    // staff application, even by accident.
    port: 5174,
    proxy: {
      "/api": {
        // Configurable because "localhost" means something different
        // inside a container: it is the container. The dev compose
        // override sets this to the backend service name.
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
})
