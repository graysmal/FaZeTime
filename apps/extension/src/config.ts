// Build-time configuration, injected by wxt.config.ts (`define`). Not secrets.
//   WXT_FAZETIME_MODE      mock | live            (default mock)
//   WXT_FAZETIME_API_BASE  API origin for live    (default http://127.0.0.1:8000; Pi: http://fazetime:8000)
//   WXT_FAZETIME_CHANNEL   live-mode mount target (default fazegavin1234; overridden only for tests)
export const FAZETIME_MODE: 'mock' | 'live' = __FAZETIME_MODE__ === 'live' ? 'live' : 'mock';
export const API_BASE: string = __FAZETIME_API_BASE__;
export const LIVE_CHANNEL: string = __FAZETIME_CHANNEL__;
export const EXTENSION_VERSION: string = __FAZETIME_VERSION__;
