// Odyssey (Θ) theme ornaments (owner request, 2026-11-15): laurel, the owl of Athena, an amphora. Decorative,
// aria-hidden SVG. Also the Θ copy flavour ("the Oracle"), set during render alongside the display currency.

let oracleFlavour = false;
/** Set by the panel and the over-video root from the stored theme, before their children render. */
export function setOracleFlavour(on: boolean): void {
  oracleFlavour = on;
}
/** "AI" in FaZe; "the Oracle" in Odyssey. */
export function aiName(capital = true): string {
  if (!oracleFlavour) return 'AI';
  return capital ? 'The Oracle' : 'the Oracle';
}

/** One laurel branch curving up; `flip` mirrors it for the right-hand side. */
export function Laurel({ flip = false, size = 22 }: { flip?: boolean; size?: number }) {
  const leaves = [8, 15, 22, 29, 36];
  return (
    <svg
      className="ft-laurel"
      viewBox="0 0 24 44"
      width={size * 0.55}
      height={size}
      aria-hidden="true"
      style={flip ? { transform: 'scaleX(-1)' } : undefined}
    >
      <path d="M18 43C8 36 5 22 12 2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      {leaves.map((y, i) => {
        const x = 12 - (40 - y) * 0.12 + (i === 0 ? 2 : 0);
        return (
          <g key={y}>
            <ellipse cx={x - 4} cy={y} rx="4.2" ry="1.9" transform={`rotate(-38 ${x - 4} ${y})`} fill="currentColor" />
            <ellipse cx={x + 3.6} cy={y - 2} rx="4.2" ry="1.9" transform={`rotate(32 ${x + 3.6} ${y - 2})`} fill="currentColor" />
          </g>
        );
      })}
    </svg>
  );
}

/** Athena's owl, used as a faint watermark. */
export function Owl() {
  return (
    <svg className="ft-owl" viewBox="0 0 60 72" aria-hidden="true">
      <path d="M12 14l6 8M48 14l-6 8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M30 14c-12 0-19 9-19 22 0 15 8 26 19 26s19-11 19-26c0-13-7-22-19-22z" fill="currentColor" />
      <circle cx="22" cy="31" r="7.5" fill="var(--ft-owl-face, #f4eee3)" />
      <circle cx="38" cy="31" r="7.5" fill="var(--ft-owl-face, #f4eee3)" />
      <circle cx="22" cy="31" r="3.2" fill="currentColor" />
      <circle cx="38" cy="31" r="3.2" fill="currentColor" />
      <path d="M30 35l-3 4h6z" fill="var(--ft-owl-beak, #b38b2e)" />
      <path d="M22 46c3 2 13 2 16 0M23 51c3 2 11 2 14 0" stroke="var(--ft-owl-face, #f4eee3)" strokeWidth="1.2" fill="none" opacity="0.6" />
      <path d="M8 63h44" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M25 62v4M29 62v4M33 62v4" stroke="var(--ft-owl-beak, #b38b2e)" strokeWidth="1.6" />
    </svg>
  );
}

/** A small amphora (the treasury jar). */
export function Amphora({ size = 18 }: { size?: number }) {
  return (
    <svg className="ft-amphora" viewBox="0 0 24 32" width={size * 0.75} height={size} aria-hidden="true">
      <path d="M8 1h8M9 1v5M15 1v5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M9 6c-6 3-7 9-5 15 2 5 5 8 8 9 3-1 6-4 8-9 2-6 1-12-5-15z" fill="currentColor" />
      <path d="M9 7C3 6 3 13 6 14M15 7c6-1 6 6 3 7" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5 16h14M6 20h12" stroke="var(--ft-owl-face, #f4eee3)" strokeWidth="1" opacity="0.8" />
    </svg>
  );
}
