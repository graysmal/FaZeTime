// FaZe theme assets, bundled into the content script as data URLs (D14: no remote code or hosted assets).
// - Fonts: Chrome ignores @font-face inside a ShadowRoot, so the faces are registered on the page's
//   document.fonts (shared with our shadow trees) under FaZeTime-only family names that cannot collide
//   with Twitch's own fonts. Nothing is inserted into Twitch's DOM.
// - Texture: the DiamondPatterns artwork, exposed to the shadow CSS as the --ft-diamond custom property.
import antonUrl from '../assets/fonts/Anton-Regular.woff?inline';
import fazedUrl from '../assets/fonts/Sample_FaZed_Sans.otf?inline';
import sourceSansUrl from '../assets/fonts/SourceSansPro-Black.woff?inline';
import diamondUrl from '../assets/diamond.jpg?inline';
import meanderUrl from '../assets/meander.svg?inline';
import cinzelUrl from '../assets/fonts/Cinzel.woff?inline';
import barlowMediumUrl from '../assets/fonts/BarlowSemiCondensed-Medium.woff?inline';
import barlowSemiBoldUrl from '../assets/fonts/BarlowSemiCondensed-SemiBold.woff?inline';
import barlowBoldUrl from '../assets/fonts/BarlowSemiCondensed-Bold.woff?inline';

export const FONT_TITLE = 'FT FaZed Sans';
export const FONT_HEAD = 'FT Anton';
export const FONT_BODY = 'FT Source Sans';

export const DIAMOND_CSS_VALUE = `url("${diamondUrl}")`;
/** ENRAGE (Odyssey) theme: the Greek-key band. */
export const MEANDER_CSS_VALUE = `url("${meanderUrl}")`;
export const FONT_ODY_TITLE = 'FT Cinzel';
export const FONT_ODY_TEXT = 'FT Barlow SC';

/** CALM = FaZe theme, ENRAGE = Odyssey theme (owner request, 2026-11-15). Stored per browser. */
export type ThemeName = 'calm' | 'enrage';
export const THEME_KEY = 'local:fazetime.theme';
export const themeAttr = (t: ThemeName | null | undefined) => (t === 'enrage' ? 'odyssey' : 'faze');

const FACES: [family: string, url: string, weight: string][] = [
  [FONT_TITLE, fazedUrl, '400'],
  [FONT_HEAD, antonUrl, '400'],
  [FONT_BODY, sourceSansUrl, '100 900'],
  ['FT Cinzel', cinzelUrl, '400 900'],
  ['FT Barlow SC', barlowMediumUrl, '500'],
  ['FT Barlow SC', barlowSemiBoldUrl, '600'],
  ['FT Barlow SC', barlowBoldUrl, '700'],
];

const registered = new WeakSet<Document>();

/** Idempotent per document. Best effort: the CSS falls back to Twitch-like system fonts. */
export function registerFonts(doc: Document): void {
  if (registered.has(doc)) return;
  registered.add(doc);
  const set = doc.fonts as FontFaceSet | undefined;
  const Face = (doc.defaultView as (Window & typeof globalThis) | null)?.FontFace ?? globalThis.FontFace;
  if (!set || typeof Face !== 'function') return;
  for (const [family, url, weight] of FACES) {
    try {
      const face = new Face(family, `url("${url}")`, { weight, style: 'normal', display: 'swap' });
      set.add(face);
      void face.load().catch(() => undefined);
    } catch {
      /* fonts are cosmetic */
    }
  }
}

/** Retrigger the diamond glaze on the clicked button (pointer or keyboard click). */
export function glazeFromEvent(target: EventTarget | null): void {
  const el = target instanceof Element ? target.closest('button') : null;
  if (!el || (el as HTMLButtonElement).disabled) return;
  el.classList.remove('ft-glaze');
  void (el as HTMLElement).offsetWidth; // restart the animation
  el.classList.add('ft-glaze');
  const done = () => {
    el.classList.remove('ft-glaze');
    el.removeEventListener('animationend', done);
  };
  el.addEventListener('animationend', done);
}

/**
 * Hover: play the same diamond glaze once each time the pointer ENTERS a button (tabs included). Moving inside
 * the button (between its child elements) does not replay it. Mouse/pen only, so a tap does not glaze twice.
 */
export function glazeOnHover(e: { target: EventTarget | null; relatedTarget: EventTarget | null; pointerType?: string }): void {
  if (e.pointerType === 'touch') return;
  const btn = e.target instanceof Element ? e.target.closest('button') : null;
  if (!btn) return;
  const from = e.relatedTarget instanceof Element ? e.relatedTarget.closest('button') : null;
  if (from === btn) return;
  glazeFromEvent(btn);
}
