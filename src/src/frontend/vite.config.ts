import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API is proxied so the browser talks to one origin and
// CORS never enters the picture. In production the container serves the built
// files and nginx proxies /api to the API service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
