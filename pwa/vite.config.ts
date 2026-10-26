import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

function serviceWorker(): Plugin {
  return {
    name: "tb-service-worker",
    apply: "build",
    async generateBundle(_, bundle) {
      const assets = Object.keys(bundle)
        .filter((file) => file.startsWith("assets/"))
        .sort()
        .map((file) => "/" + file);
      const version = createHash("sha256").update(assets.join("\n")).digest("hex").slice(0, 12);
      const source = await readFile(new URL("./sw/sw.js", import.meta.url), "utf8");
      this.emitFile({
        type: "asset",
        fileName: "sw.js",
        source: source.replace("__SW_VERSION__", version).replace("__SW_ASSETS__", JSON.stringify(assets)),
      });
    },
  };
}

const gateway = process.env.GATEWAY_URL ?? "http://127.0.0.1:8090";
const proxy = { "/gw": { target: gateway, ws: true, changeOrigin: false } };

export default defineConfig({
  plugins: [svelte(), serviceWorker()],
  define: { __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "0.0.0") },
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
  build: { target: "es2022", sourcemap: false },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
