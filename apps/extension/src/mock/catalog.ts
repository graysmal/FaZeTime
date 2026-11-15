// P1-only fixed demo catalog (lives outside the contract folder, CONTRACTS 9.14).
// Fictional items. Nothing is scraped, sold, shipped or redeemable anywhere.
import type { RedeemItem } from '../api/types';

export const DEMO_CATALOG: readonly RedeemItem[] = [
  { item_id: 'demo_sticker_pack', title: 'Demo sticker pack', description: 'Pretend sticker sheet. Nothing ships.', price_minor: 500 },
  { item_id: 'demo_emote_slot', title: 'Demo emote unlock', description: 'Imaginary emote slot. Not a Twitch reward.', price_minor: 1000 },
  { item_id: 'demo_hoodie_coupon', title: 'Demo hoodie coupon', description: 'Fake coupon. No store accepts it.', price_minor: 2500 },
];

const CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789';

/** "DEMO-XXXX-XXXX" from a CSPRNG, unbiased by rejection sampling. Labelled NON-REDEEMABLE in the UI. */
export function generateDemoCode(): string {
  const chars: string[] = [];
  const limit = 256 - (256 % CODE_ALPHABET.length);
  const buf = new Uint8Array(16);
  while (chars.length < 8) {
    crypto.getRandomValues(buf);
    for (const b of buf) {
      if (b < limit && chars.length < 8) chars.push(CODE_ALPHABET.charAt(b % CODE_ALPHABET.length));
    }
  }
  return `DEMO-${chars.slice(0, 4).join('')}-${chars.slice(4).join('')}`;
}
