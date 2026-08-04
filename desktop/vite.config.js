import { defineConfig } from "vite";

export default defineConfig({
  base: "/launcher/",
  clearScreen: false,
  build: {
    outDir: "dist/launcher",
    emptyOutDir: false,
  },
  server: {
    strictPort: true,
  },
});
