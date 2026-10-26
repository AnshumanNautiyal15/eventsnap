import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Django (manage.py runserver 0.0.0.0:8010) serves the API, photos and the built app.
const django = "http://localhost:8010";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Built files are served by Django under /static/; the dev server serves from the root.
  base: command === "build" ? "/static/" : "/",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    // `npm run dev` for live reload while editing the UI: proxy everything that isn't a page to Django.
    proxy: {
      "/api": django,
      "/google": django,
      "/p/": django,
      "/admin": django,
      "^/events/[^/]+/qr\\.png": django,
      "^/e/[^/]+/my-photos\\.zip": django,
    },
  },
}));
