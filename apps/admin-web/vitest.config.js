import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Unit/component tests only: no Tailwind plugin (CSS is irrelevant here) and nothing from tests/ reaches the production bundle.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{js,jsx}'],
    setupFiles: ['tests/setup.js'],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
