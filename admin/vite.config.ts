/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The admin app is a separate bundle from the chat widget and is never shipped inside it.
export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
  },
});
