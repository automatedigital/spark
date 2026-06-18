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
      // Override with SPARK_API_TARGET to point the dev proxy at a backend on a
      // non-default port (e.g. when the installed app already holds 9119).
      "/api": process.env.SPARK_API_TARGET || "http://127.0.0.1:9119",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
