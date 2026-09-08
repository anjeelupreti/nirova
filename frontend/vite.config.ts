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
  build: {
    // Vendor code splitting.
    //
    // Without this, React, the router, the query client and every Radix
    // primitive are inlined into whichever chunk imports them first, so a
    // one-line change to a page invalidates the browser's cache for all of
    // it. Split out, the vendor chunks are keyed on their own content and
    // survive every deployment that does not change a dependency -- which is
    // almost all of them.
    //
    // Split by *how often each changes*, not by size. `react` and the router
    // change on an upgrade; the UI primitives change when the design does;
    // application pages change daily.
    //
    // Splitting these was also what showed `@tanstack/react-query` to be
    // dead: its chunk built to 1 kB, because nothing imports it. It has
    // been removed from package.json rather than chunked.
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-ui": [
            "@radix-ui/react-dialog",
            "@radix-ui/react-dropdown-menu",
            "@radix-ui/react-label",
            "@radix-ui/react-progress",
            "@radix-ui/react-select",
            "@radix-ui/react-slot",
            "@radix-ui/react-tabs",
            "class-variance-authority",
            "clsx",
            "tailwind-merge",
          ],
          // lucide-react is ~1400 icon modules. Tree shaking keeps only the
          // ones imported, but they are imported from twenty different pages,
          // so leaving them unsplit duplicates icons across route chunks.
          "vendor-icons": ["lucide-react"],
        },
      },
    },
    // Raised from Vite's 500 kB default. The warning existed to flag the
    // single 943 kB bundle; now that the largest chunk is the React runtime,
    // which cannot be split further and is cached across deployments, the
    // default only cries wolf. Kept low enough that a page chunk growing past
    // it is still reported.
    chunkSizeWarningLimit: 700,
  },

  server: {
    // 0.0.0.0 when asked, so the dev server is reachable from outside a
    // container. Harmless on a host: Vite still prints the localhost URL.
    host: true,
    port: 5173,
    // Proxy /api to Django in development. Keeps the browser on one origin,
    // so CORS and cookie behaviour in dev match production behind a reverse
    // proxy rather than being a special case that hides problems.
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
