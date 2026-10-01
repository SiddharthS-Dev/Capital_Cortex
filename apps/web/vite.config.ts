/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5373,
    strictPort: true,
    proxy: { "/v1": { target: process.env.CORTEX_API ?? "http://localhost:8300", changeOrigin: true } },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // heavy libraries in their own cacheable chunks (Monaco is also lazy-loaded)
        manualChunks: { echarts: ["echarts"], cytoscape: ["cytoscape"], maps: ["topojson-client"] },
      },
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
