/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    // Parent of this file is src/spark_cli/ — same directory as web_server.py’s web_dist.
    outDir: "../web_dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:9119",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
