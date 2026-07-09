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
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "vendor-react";
          if (id.includes("node_modules/@xyflow/")) return "feature-canvas";
          if (id.includes("node_modules/@xterm/")) return "feature-terminal";
          if (
            id.includes("node_modules/@uiw/") ||
            (id.includes("node_modules/@codemirror/") &&
              !id.includes("node_modules/@codemirror/lang-") &&
              !id.includes("node_modules/@codemirror/legacy-modes/"))
          ) {
            return "feature-editor-core";
          }
        },
      },
    },
  },
  optimizeDeps: {
    // Do not crawl packaged Tauri/Python resource HTML under src-tauri.
    entries: ["index.html"],
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
