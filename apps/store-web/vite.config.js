import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Shared code lives in packages/web-kit (T14). Two levels up works both in the repo and in the Docker build (/app -> /packages).
const apiClient = fileURLToPath(new URL('../../packages/api-client/src/index.js', import.meta.url));
const webKit = fileURLToPath(new URL('../../packages/web-kit/src', import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@melorin/web-kit': webKit, '@melorin/api-client': apiClient },
    // web-kit sits outside this app's node_modules: make it use the app's single copy of react.
    dedupe: ['react', 'react-dom'],
  },
  server: { fs: { allow: ['../..'] } },
});
