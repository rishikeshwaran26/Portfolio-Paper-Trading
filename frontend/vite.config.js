import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server runs on 5173 — the origin we whitelisted for CORS in the
// Flask API (api/__init__.py). The React app calls the API directly at
// http://127.0.0.1:5000; no proxy needed because CORS is enabled.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
