import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxyTarget = process.env.VITE_PROXY_AGILE_API || "http://127.0.0.1:9120";
const chatProxyTarget = process.env.VITE_PROXY_AGILE_CHAT_API || "http://127.0.0.1:9130";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      "/agile-api": {
        target: proxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agile-api/, "") || "/",
      },
      "/agile-chat-api": {
        target: chatProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agile-chat-api/, "") || "/",
      },
      "/agile-chat-ws": {
        target: chatProxyTarget,
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agile-chat-ws/, "") || "/",
      },
      "/socket.io": {
        target: chatProxyTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
