import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'wxt';

// Bundled panel only (D14): no hosted iframe, no remote code.
// Build-time switches (see src/config.ts): WXT_FAZETIME_MODE, WXT_FAZETIME_API_BASE, WXT_FAZETIME_CHANNEL.
const mode = process.env.WXT_FAZETIME_MODE === 'live' ? 'live' : 'mock';
const DEFAULT_API = 'http://127.0.0.1:8000';
const DEFAULT_CHANNEL = 'fazegavin1234';
const apiBase = new URL(process.env.WXT_FAZETIME_API_BASE || DEFAULT_API);
if (apiBase.protocol !== 'http:' && apiBase.protocol !== 'https:') throw new Error('WXT_FAZETIME_API_BASE must be http(s)');
if (apiBase.username || apiBase.password || apiBase.pathname !== '/' || apiBase.search) throw new Error('WXT_FAZETIME_API_BASE must be a bare origin');
const channel = (process.env.WXT_FAZETIME_CHANNEL || DEFAULT_CHANNEL).toLowerCase();
if (!/^[a-z0-9_]{1,25}$/.test(channel)) throw new Error('WXT_FAZETIME_CHANNEL must be a Twitch login');
const version = '0.2.0';

// PUBLIC key only: pins the unpacked extension ID (manifest-key.json records the derived ID).
const manifestKey = JSON.parse(readFileSync(resolve(__dirname, 'manifest-key.json'), 'utf8')) as { id: string; key: string };

// Output folder per variant so mock, live and test builds never overwrite each other.
let variant = '';
if (mode === 'live') {
  variant = '-live';
  if (apiBase.origin !== DEFAULT_API) variant += `-${apiBase.hostname.replace(/[^a-z0-9]/gi, '_')}`;
  if (channel !== DEFAULT_CHANNEL) variant += `-test-${channel}`;
}

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  outDirTemplate: `{{browser}}-mv{{manifestVersion}}${variant}`,
  alias: {
    '@fazetime/contracts': resolve(__dirname, '../../packages/contracts/src/index.ts'),
    '@fixtures': resolve(__dirname, '../../packages/contracts/fixtures'),
  },
  manifest: {
    name: mode === 'live' ? 'FaZeTime' : 'FaZeTime (MOCK demo)',
    description:
      mode === 'live'
        ? 'Predict what happens next on stream, with friends.'
        : 'FaZeTime hackathon demo panel for Twitch. P1 build: local MOCK/FIXTURE data only, no real money.',
    version,
    key: manifestKey.key,
    permissions: ['storage'],
    // Only the API origin, and only in live builds. Content scripts never call it (background only).
    host_permissions: mode === 'live' ? [`${apiBase.origin}/*`] : [],
    action: { default_title: mode === 'live' ? 'FaZeTime' : 'FaZeTime profile (MOCK)' },
  },
  vite: () => ({
    define: {
      __FAZETIME_MODE__: JSON.stringify(mode),
      __FAZETIME_API_BASE__: JSON.stringify(apiBase.origin),
      __FAZETIME_CHANNEL__: JSON.stringify(channel),
      __FAZETIME_VERSION__: JSON.stringify(version),
    },
    server: { fs: { allow: [resolve(__dirname, '../..')] } },
  }),
});
