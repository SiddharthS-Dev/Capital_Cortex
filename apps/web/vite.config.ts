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
    // 127.0.0.1, not localhost: the API binds IPv4 loopback, and "localhost" resolves to ::1 first on Windows/Node,
    // costing a failed IPv6 attempt (~0.2 s measured) on every proxied connection.
    proxy: { "/v1": { target: process.env.CORTEX_API ?? "http://127.0.0.1:8300", changeOrigin: true } },
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
