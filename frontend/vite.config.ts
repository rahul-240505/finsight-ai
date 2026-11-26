import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// A strict Content-Security-Policy for the built app: only our own scripts, no inline code.
// (The dev server is left without it because React Fast Refresh injects an inline script.)
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; " +
  "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'";
const csp: Plugin = {
  name: "csp",
  apply: "build",
  transformIndexHtml: () => [
    { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: CSP }, injectTo: "head-prepend" },
  ],
};

// The dev server proxies /api to the FastAPI app, so the browser sees one origin:
// the session cookie stays first-party and the API's CSRF Origin check passes.
export default defineConfig({
  plugins: [react(), tailwindcss(), csp],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8000" } },
  },
  preview: { port: 5173, strictPort: true, proxy: { "/api": { target: "http://127.0.0.1:8000" } } },
});
