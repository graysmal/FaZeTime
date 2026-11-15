// Twitch route parsing. Only plain channel pages (twitch.tv/<login>) get the panel.

const RESERVED = new Set([
  'activate',
  'bits',
  'broadcast',
  'checkout',
  'creatorcamp',
  'dashboard',
  'directory',
  'downloads',
  'drops',
  'embed',
  'event',
  'following',
  'friends',
  'inventory',
  'jobs',
  'legal',
  'login',
  'logout',
  'messages',
  'moderator',
  'p',
  'passport',
  'payments',
  'popout',
  'prime',
  'privacy',
  'products',
  'redeem',
  'search',
  'settings',
  'signup',
  'store',
  'subscriptions',
  'team',
  'turbo',
  'u',
  'user',
  'videos',
  'wallet',
]);

/** Lowercased channel login for a channel page, or null for any other Twitch route. */
export function channelFromPath(pathname: string): string | null {
  const m = /^\/([A-Za-z0-9_]{1,25})\/?$/.exec(pathname);
  if (!m) return null;
  const login = (m[1] ?? '').toLowerCase();
  return RESERVED.has(login) ? null : login;
}
