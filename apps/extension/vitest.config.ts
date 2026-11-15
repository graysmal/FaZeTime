import { defineConfig } from 'vitest/config';
import { WxtVitest } from 'wxt/testing/vitest-plugin';

export default defineConfig({
  plugins: [WxtVitest()],
  define: {
    __FAZETIME_MODE__: JSON.stringify('mock'),
    __FAZETIME_API_BASE__: JSON.stringify('http://127.0.0.1:8000'),
    __FAZETIME_CHANNEL__: JSON.stringify('fazegavin1234'),
    __FAZETIME_VERSION__: JSON.stringify('0.0.0-test'),
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
