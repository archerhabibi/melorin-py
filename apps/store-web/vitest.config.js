import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Unit/component tests only: no Tailwind plugin (CSS is irrelevant here) and nothing from tests/ reaches the production bundle.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@melorin/web-kit': fileURLToPath(new URL('../../packages/web-kit/src', import.meta.url)),
      '@melorin/api-client': fileURLToPath(new URL('../../packages/api-client/src/index.js', import.meta.url)),
    },
    dedupe: ['react', 'react-dom'],
  },
  test: {
    // vmThreads: per-file VM contexts in worker threads, cheaper than forked processes (T-R05/Phase 1).
    pool: 'vmThreads',
    environment: 'jsdom',
    include: ['tests/**/*.test.{js,jsx}'],
    setupFiles: ['tests/setup.js'],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
