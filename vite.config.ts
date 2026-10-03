import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8"));

// Backend routes, proxied in `npm run dev` so the app can call them same-origin.
const API_PATHS = ["/auth", "/diagnose", "/chat", "/voice", "/diseases", "/health", "/privacy", "/delete-account"];

export default defineConfig({
  root: "web",
  envDir: ".",          // web/.env.local → VITE_API_BASE_URL for phone testing
  base: "./",           // relative asset paths: required inside the Android app
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: { outDir: "dist", emptyOutDir: true, target: "es2020" },
  server: {
    port: 5173,
    proxy: Object.fromEntries(API_PATHS.map(p => [p, "http://localhost:8000"])),
  },
});
