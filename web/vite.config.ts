import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the page runs on :5173 and forwards /api and /images to FastAPI on :8000 (same origin, no CORS needed).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/images": "http://127.0.0.1:8000" },
  },
});
