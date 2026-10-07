import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the API runs separately; in production FastAPI serves the built files.
    proxy: { "/api": api, "/health": api, "/docs": api, "/openapi.json": api },
    // The sample files live in ../samples.
    fs: { allow: [".."] },
  },
  build: {
    // MapLibre GL alone is ~800 kB minified; keep it in its own long-cacheable chunk.
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { maplibre: ["maplibre-gl"] } } },
  },
});
