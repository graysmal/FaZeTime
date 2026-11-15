// One control for the alert sound: a click toggles mute, a press-and-drag (left/right or up/down) sets the
// volume. Keyboard: Enter/Space toggles mute, arrow keys step the volume, Home/End go to 0/100%.
import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

const DRAG_PX_FOR_FULL = 120;
const DRAG_THRESHOLD_PX = 4;
const SEGMENTS = 6;

type Drag = { x: number; y: number; start: number; moved: boolean };

function SpeakerIcon({ level }: { level: number }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" className="vol-icon">
      <path d="M3 9h4l5-4v14l-5-4H3z" fill="currentColor" />
      {level === 0 ? (
        <path d="M16 9l5 6M21 9l-5 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" fill="none" />
      ) : (
        <>
          <path d="M15.5 9.5l1.6 2.5-1.6 2.5" stroke="currentColor" strokeWidth="2" fill="none" />
          {level > 0.45 && <path d="M18.5 7l3 5-3 5" stroke="currentColor" strokeWidth="2" fill="none" />}
        </>
      )}
    </svg>
  );
}

export function VolumeControl({
  volume,
  muted,
  unlocked,
  onVolume,
  onToggleMute,
  onCommit,
}: {
  volume: number;
  muted: boolean;
  unlocked: boolean;
  onVolume: (v: number) => void;
  onToggleMute: () => void;
  /** Called after a drag or key change settles (plays a preview beep). */
  onCommit: () => void;
}) {
  const drag = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const [dragging, setDragging] = useState(false);
  const level = muted ? 0 : volume;
  const pct = Math.round(level * 100);

  const down = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, start: level, moved: false };
  };
  const move = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d) return;
    const delta = e.clientX - d.x + (d.y - e.clientY);
    if (!d.moved && Math.abs(delta) < DRAG_THRESHOLD_PX) return;
    if (!d.moved) {
      d.moved = true;
      setDragging(true);
    }
    onVolume(Math.min(1, Math.max(0, d.start + delta / DRAG_PX_FOR_FULL)));
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) {
      suppressClick.current = true; // the click that follows a drag must not toggle mute
      setDragging(false);
      onCommit();
    }
  };
  const click = () => {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onToggleMute();
  };
  const key = (e: KeyboardEvent<HTMLButtonElement>) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 0.1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -0.1 : 0;
    let next: number | null = null;
    if (step) next = Math.min(1, Math.max(0, level + step));
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = 1;
    if (next === null) return;
    e.preventDefault();
    onVolume(Math.round(next * 10) / 10);
    onCommit();
  };

  const label = muted || level === 0 ? 'Sound off' : `Volume ${pct}%`;
  return (
    <button
      type="button"
      className={`vol ${muted || level === 0 ? 'muted' : ''} ${dragging ? 'dragging' : ''}`}
      role="slider"
      aria-label="Alert volume"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-valuetext={label}
      title={unlocked ? 'Click to mute or unmute. Drag to set the volume.' : 'Click anywhere to enable sound. Drag to set the volume.'}
      data-testid="sound-toggle"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onClick={click}
      onKeyDown={key}
    >
      <SpeakerIcon level={level} />
      <span className="vol-bars" aria-hidden="true">
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <span key={i} className={level > i / SEGMENTS + 0.001 ? 'on' : ''} />
        ))}
      </span>
      <span className="vol-pct">{muted || level === 0 ? 'MUTED' : `${pct}%`}</span>
    </button>
  );
}
