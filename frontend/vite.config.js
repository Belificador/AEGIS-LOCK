import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const modelsRoot = fileURLToPath(new URL("../models_3d/", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: ["aegis-lock.onrender.com"],
    fs: {
      allow: [frontendRoot, modelsRoot],
    },
  },
  preview: {
    host: true,
    allowedHosts: ["aegis-lock.onrender.com"],
  },
});
