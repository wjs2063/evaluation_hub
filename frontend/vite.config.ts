import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig, loadEnv } from "vite"

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const backendTarget = env.VITE_DEV_API_URL || "http://127.0.0.1:8000"

  return {
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    plugins: [
      tanstackRouter({
        target: "react",
        autoCodeSplitting: true,
      }),
      react(),
      tailwindcss(),
    ],
    // Production uses nginx for this proxy. Keep the same-origin API contract
    // when running `npm run dev`, otherwise Vite serves index.html for /api.
    server: {
      proxy: {
        "/api": { target: backendTarget, changeOrigin: true },
        "/docs": { target: backendTarget, changeOrigin: true },
        "/redoc": { target: backendTarget, changeOrigin: true },
      },
    },
  }
})
