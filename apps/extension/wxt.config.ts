import { resolve } from 'node:path';
import { defineConfig } from 'wxt';

// P1: bundled panel only (D14). No hosted iframe, no remote code, no backend host permission yet.
export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  alias: {
    '@fazetime/contracts': resolve(__dirname, '../../packages/contracts/src/index.ts'),
    '@fixtures': resolve(__dirname, '../../packages/contracts/fixtures'),
  },
  manifest: {
    name: 'FaZeTime (MOCK demo)',
    description: 'FaZeTime hackathon demo panel for Twitch. P1 build: local MOCK/FIXTURE data only, no real money.',
    permissions: ['storage'],
    action: { default_title: 'FaZeTime profile (MOCK)' },
  },
  vite: () => ({
    server: { fs: { allow: [resolve(__dirname, '../..')] } },
  }),
});
