import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Reads VITE_* from the repository-root .env. Without VITE_API_BASE_URL the app calls
// /api/v1 and the dev server proxies it to the FastAPI backend on port 8000.
export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
