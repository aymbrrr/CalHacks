import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies FastAPI endpoints to the running uvicorn server so the dev tab can
// hit /api, /findings, /alerts without CORS. Backend defaults to :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/findings": "http://localhost:8000",
      "/alerts": "http://localhost:8000",
    },
  },
});
