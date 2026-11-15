/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin, type ProxyOptions } from 'vite';

// Deployment model: the API serves dist/ same-origin at /operator/ (FAZETIME_OPERATOR_DIST), so all API
// calls are relative (/v1/...) and need no CORS entry. Dev and preview proxy those paths to a local API.
const root = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const apiTarget = process.env.FAZETIME_API_PROXY || 'http://127.0.0.1:8000';
const target = new URL(apiTarget);
if (target.protocol !== 'http:' && target.protocol !== 'https:') throw new Error('FAZETIME_API_PROXY must be http(s)');

const proxy: Record<string, ProxyOptions> = {
  '/v1': { target: target.origin },
  '/openapi.json': { target: target.origin },
  '/healthz': { target: target.origin },
};

// Build-only CSP (dev needs Vite's inline HMR preamble). form-action 'none' stops a JS-less form submit
// from ever putting an invite code into a URL; blob: is for authenticated evidence thumbnails.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' blob:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

function buildCsp(): Plugin {
  return {
    name: 'fazetime-operator-csp',
    apply: 'build',
    transformIndexHtml() {
      return [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' }];
    },
  };
}

export default defineConfig({
  root,
  base: '/operator/',
  plugins: [react(), buildCsp()],
  resolve: {
    alias: { '@fazetime/contracts': `${repoRoot}packages/contracts/src/index.ts` },
  },
  server: { host: '127.0.0.1', port: 5174, strictPort: true, proxy, fs: { allow: [repoRoot] } },
  preview: { host: '127.0.0.1', port: 4174, strictPort: true, proxy },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, target: 'es2022' },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.{ts,tsx}'],
    execArgv: ['--no-experimental-webstorage'],
  },
});
