/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server: serves index.html (the fake-CRM harness) on :5173.
// Build: library mode, one self-contained ES module for embedding in the CRM.
// React is bundled on purpose so we never depend on the host's React version.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  define: command === "build" ? { "process.env.NODE_ENV": JSON.stringify("production") } : {},
  build: {
    lib: {
      entry: "src/element.tsx",
      formats: ["es"],
      fileName: () => "crm-help-bot.js",
    },
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    css: true, // so `styles.css?inline` is real CSS in tests
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
