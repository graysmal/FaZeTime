/// <reference types="vite/client" />

declare module '*.css?inline' {
  const css: string;
  export default css;
}

// Injected by wxt.config.ts `define` (and by vitest.config.ts for tests).
declare const __FAZETIME_MODE__: string;
declare const __FAZETIME_API_BASE__: string;
declare const __FAZETIME_CHANNEL__: string;
declare const __FAZETIME_VERSION__: string;

declare module '*?inline' {
  const dataUrl: string;
  export default dataUrl;
}
