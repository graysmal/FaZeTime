"""Grizz, the FaZeTime sock puppet: an animated sock puppet drawn with numpy.

Same interface as face.py (WIDTH, HEIGHT, FPS, render(speaking) -> RGBA bytes), so the
agent can show either. A grey striped sock rising from a little puppet booth, with googly
eyes, bushy grey brows, stubble, a pom-pom nose and wild yarn hair. While the agent speaks
the jaw flaps open and the puppet bobs; the pupils jiggle and the puppet sways all the
time, so a frozen picture is easy to spot.

Framing: FaceTime may crop the 640x360 video to fill an upright phone, which keeps only a
narrow middle column. So the puppet is drawn at full detail on its own "design" canvas,
scaled down (PuppetRenderer(scale=...), default 0.5) with anti-aliased edges, and placed in
the middle of the stage, where it survives that crop; the booth ledge hides the arm.
"""

from __future__ import annotations

import math

import numpy as np

WIDTH = 640
HEIGHT = 360
FPS = 15

BG_TOP, BG_BOTTOM = (16, 18, 32), (40, 28, 44)
CURTAIN = (150, 22, 34)
BOOTH, BOOTH_DARK, BOOTH_TRIM = (112, 66, 40), (78, 44, 26), (205, 32, 38)
SOCK = (138, 140, 148)
STRIPE_A, STRIPE_B = (205, 32, 38), (236, 234, 228)
MOUTH = (64, 10, 20)
TONGUE = (222, 96, 116)
EYE_WHITE = (250, 250, 246)
INK = (14, 14, 18)
NOSE, NOSE_HI = (212, 44, 44), (255, 150, 150)
BROW = (226, 224, 218)
STUBBLE = (78, 80, 88)
YARN = (196, 190, 178)
KEY = (255, 0, 255)  # design-canvas background; never used by the puppet

# Design canvas (the puppet at full detail, just wide enough for it and its sway).
# The arm runs to the bottom of it.
_DW, _DH = 360, 480
_CX = _DW // 2
_HEAD_CY, _HEAD_RX, _HEAD_RY = 150, 150, 92
_MOUTH_Y = 168  # mouth line at the centre; it droops toward the corners (a grumpy frown)
_MOUTH_RX = 140
_ARM_HALF_W, _ARM_TOP = 92, 190
_EYES = ((_CX - 58, 92), (_CX + 58, 92))
_EYE_R, _PUPIL_R = 30, 13
# Output stage.
_LEDGE_Y = 268  # top of the booth front panel; the arm disappears behind it
_HEAD_OUT_Y = 150  # where the head centre lands in the output


class _Sprite:
    """An RGB patch, its mask and its top-left corner in design coordinates."""

    def __init__(self, canvas: np.ndarray, mask: np.ndarray) -> None:
        ys, xs = np.nonzero(mask)
        self.y0, self.y1 = int(ys.min()), int(ys.max()) + 1
        self.x0, self.x1 = int(xs.min()), int(xs.max()) + 1
        self.rgb = canvas[self.y0 : self.y1, self.x0 : self.x1].copy()
        self.mask = mask[self.y0 : self.y1, self.x0 : self.x1].copy()

    def paste(self, frame: np.ndarray, dx: int, dy: int) -> None:
        fh, fw = frame.shape[:2]
        x0, y0 = self.x0 + dx, self.y0 + dy
        h, w = self.mask.shape
        fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(fw, x0 + w), min(fh, y0 + h)
        if fx1 <= fx0 or fy1 <= fy0:
            return
        sx, sy = fx0 - x0, fy0 - y0
        m = self.mask[sy : sy + fy1 - fy0, sx : sx + fx1 - fx0]
        frame[fy0:fy1, fx0:fx1][m] = self.rgb[sy : sy + fy1 - fy0, sx : sx + fx1 - fx0][m]


def _capsule(xx: np.ndarray, yy: np.ndarray, x0: float, y0: float, x1: float, y1: float, r: float) -> np.ndarray:
    """Pixels within r of the segment (x0, y0)-(x1, y1)."""
    vx, vy = x1 - x0, y1 - y0
    t = np.clip(((xx - x0) * vx + (yy - y0) * vy) / (vx * vx + vy * vy), 0.0, 1.0)
    return (xx - (x0 + t * vx)) ** 2 + (yy - (y0 + t * vy)) ** 2 <= r * r


def _paint(canvas: np.ndarray, mask: np.ndarray, color: tuple[int, int, int], shade: np.ndarray | None = None) -> None:
    if shade is None:
        canvas[mask] = color
    else:
        canvas[mask] = (np.array(color, dtype=np.float32) * shade[mask][:, None]).clip(0, 255).astype(np.uint8)


class PuppetRenderer:
    """Renders successive frames. render() returns WIDTH*HEIGHT*4 RGBA bytes."""

    def __init__(self, scale: float = 0.5) -> None:
        self._scale = scale = min(1.0, max(0.3, scale))
        self._build_stage()
        self._build_puppet()

        # Output placement of the sampled design region, and its 2x2 supersampling grid.
        self._out_w = int(round(_DW * scale))
        self._out_x0 = WIDTH // 2 - self._out_w // 2
        self._out_y0 = max(0, int(round(_HEAD_OUT_Y - _HEAD_CY * scale)))
        # Rows below the frame are hidden behind the booth anyway; do not sample them.
        self._out_h = min(int(round(_DH * scale)), HEIGHT - self._out_y0)
        rows = np.arange(self._out_h, dtype=np.float32)
        cols = np.arange(self._out_w, dtype=np.float32)
        self._grid = [
            np.ix_(
                np.clip(((rows + oy) / scale).astype(np.int32), 0, _DH - 1),
                np.clip(((cols + ox) / scale).astype(np.int32), 0, _DW - 1),
            )
            for oy in (0.25, 0.75)
            for ox in (0.25, 0.75)
        ]
        self._tick = 0

    # ------------------------------------------------------------------ building

    def _build_stage(self) -> None:
        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
        g = (yy / HEIGHT)[..., None]
        bg = (np.array(BG_TOP) * (1 - g) + np.array(BG_BOTTOM) * g).astype(np.uint8)
        folds = 0.62 + 0.38 * np.cos(xx * 0.22) ** 2
        _paint(bg, (xx < 78) | (xx > WIDTH - 78), CURTAIN, folds)
        valance = yy < 22 + 8 * np.abs(np.sin(xx * math.pi / 64))
        _paint(bg, valance, CURTAIN, 0.8 + 0.2 * np.cos(xx * 0.1))
        self._background = np.empty((HEIGHT, WIDTH, 4), dtype=np.uint8)
        self._background[..., :3] = bg
        self._background[..., 3] = 255

        # Booth front panel, drawn over the puppet: wood planks with a red trim.
        panel = yy >= _LEDGE_Y
        planks = 0.88 + 0.12 * ((xx.astype(np.int32) // 64) % 2)
        booth = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        _paint(booth, panel, BOOTH, planks)
        _paint(booth, panel & (yy < _LEDGE_Y + 9), BOOTH_TRIM)
        _paint(booth, panel & (yy >= _LEDGE_Y + 9) & (yy < _LEDGE_Y + 13), BOOTH_DARK)
        self._booth = booth[_LEDGE_Y:].copy()

    def _build_puppet(self) -> None:
        yy, xx = np.mgrid[0:_DH, 0:_DW].astype(np.float32)
        head = ((xx - _CX) / _HEAD_RX) ** 2 + ((yy - _HEAD_CY) / _HEAD_RY) ** 2 < 1
        mouth_line = _MOUTH_Y + 14 * ((xx - _CX) / _HEAD_RX) ** 2
        upper = head & (yy < mouth_line)
        arm = (np.abs(xx - _CX) < _ARM_HALF_W) & (yy >= _ARM_TOP)
        lower = (head & (yy >= mouth_line)) | arm

        knit = np.where((yy.astype(np.int32) // 3) % 2 == 0, 0.94, 1.0)
        head_shade = (1.0 - 0.28 * ((xx - _CX) / _HEAD_RX) ** 2 - 0.12 * (yy - _HEAD_CY) / _HEAD_RY) * knit
        arm_shade = (1.0 - 0.3 * ((xx - _CX) / _ARM_HALF_W) ** 2) * knit

        canvas = np.zeros((_DH, _DW, 3), dtype=np.uint8)
        _paint(canvas, head, SOCK, head_shade)
        _paint(canvas, arm & ~head, SOCK, arm_shade)
        cuff = arm & ~head & (yy >= 262)
        bands = ((yy - 262).astype(np.int32) // 22) % 2 == 0
        _paint(canvas, cuff & bands, STRIPE_A, arm_shade)
        _paint(canvas, cuff & ~bands, STRIPE_B, arm_shade)

        # Grizzled stubble on the lower jaw, near the mouth (3x3 specks, fixed seed).
        rng = np.random.default_rng(7)
        specks = (rng.random((_DH, _DW)) < 0.03) & head & (yy >= mouth_line + 5) & (yy < mouth_line + 46)
        for axis in (0, 1):
            specks |= np.roll(specks, 1, axis=axis) | np.roll(specks, -1, axis=axis)
        canvas[specks & head & (yy >= mouth_line + 3)] = STUBBLE

        # Upper head details: wild yarn hair, eye whites, bushy brows and a pom-pom nose.
        hair = np.zeros_like(head)
        for i in range(9):
            x = _CX - 72 + 18 * i
            y = 66 - 4 * math.sin(i * 1.3)
            for k in range(4):
                nx = x + 9 * math.sin(i * 2.1 + k * 1.7)
                ny = y - 11
                hair |= _capsule(xx, yy, x, y, nx, ny, 4.0)
                x, y = nx, ny
        _paint(canvas, hair, YARN)
        for ex, ey in _EYES:
            d2 = (xx - ex) ** 2 + (yy - ey) ** 2
            canvas[d2 < (_EYE_R + 4) ** 2] = INK
            canvas[d2 < _EYE_R**2] = EYE_WHITE
        (lx, ly), (rx, ry) = _EYES
        brows = _capsule(xx, yy, lx - 34, ly - 46, lx + 26, ly - 34, 8) | _capsule(xx, yy, rx + 34, ry - 46, rx - 26, ry - 34, 8)
        canvas[brows] = BROW
        canvas[(xx - _CX) ** 2 + (yy - 134) ** 2 < 18**2] = NOSE
        canvas[(xx - (_CX - 5)) ** 2 + (yy - 128) ** 2 < 6**2] = NOSE_HI

        self._upper = _Sprite(canvas, upper | hair | brows)
        self._lower = _Sprite(canvas, lower)

        py, px = np.mgrid[-_PUPIL_R : _PUPIL_R + 1, -_PUPIL_R : _PUPIL_R + 1]
        self._pupil = px**2 + py**2 <= _PUPIL_R**2
        self._glint = (px + 4) ** 2 + (py + 4) ** 2 <= 3**2
        self._mouth_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._design = np.empty((_DH, _DW, 3), dtype=np.uint8)
        self._frame = np.empty_like(self._background)

    def _mouth(self, half_h: int) -> tuple[np.ndarray, np.ndarray]:
        """Mouth and tongue masks for a given half-height, centred in their own box."""
        if half_h not in self._mouth_cache:
            my, mx = np.mgrid[-half_h : half_h + 1, -_MOUTH_RX : _MOUTH_RX + 1].astype(np.float32)
            mouth = (mx / _MOUTH_RX) ** 2 + (my / max(half_h, 1)) ** 2 <= 1
            tongue = mouth & (((mx - 12) / 52) ** 2 + ((my - half_h * 0.75) / max(half_h * 0.55, 1)) ** 2 <= 1)
            self._mouth_cache[half_h] = (mouth, tongue)
        return self._mouth_cache[half_h]

    # ------------------------------------------------------------------ drawing

    def _draw_design(self, t: int, speaking: bool) -> None:
        d = self._design
        d[:] = KEY
        sway = int(round(6 * math.sin(t * 0.12)))
        bob = int(round(3 * math.sin(t * 0.5))) if speaking else int(round(1.5 * math.sin(t * 0.2)))
        if speaking:
            opening = int(4 + 26 * abs(math.sin(t * 0.95)) * (0.65 + 0.35 * math.sin(t * 0.31)))
        else:
            opening = 2
        lift = int(opening * 0.45)  # the upper head lifts a little, the jaw drops more
        drop = opening - lift

        self._lower.paste(d, sway, bob + drop)
        half_h = max(1, opening // 2 + 2)
        mouth, tongue = self._mouth(half_h)
        mcx, mcy = _CX + sway, _MOUTH_Y + bob + (drop - lift) // 2
        region = d[mcy - half_h : mcy + half_h + 1, mcx - _MOUTH_RX : mcx + _MOUTH_RX + 1]
        region[mouth] = MOUTH
        if opening > 8:
            region[tongue] = TONGUE
        self._upper.paste(d, sway, bob - lift)

        jiggle = 1.5 if speaking else 1.0
        for i, (ex, ey) in enumerate(_EYES):
            dx = 9 * jiggle * math.sin(t * 0.7 + i * 1.7)
            dy = 7 + 4 * jiggle * math.sin(t * 1.1 + i)
            reach = math.hypot(dx, dy)
            limit = _EYE_R - _PUPIL_R - 2
            if reach > limit:
                dx, dy = dx * limit / reach, dy * limit / reach
            px, py = ex + sway + int(dx), ey + bob - lift + int(dy)
            r = _PUPIL_R
            stamp = d[py - r : py + r + 1, px - r : px + r + 1]
            stamp[self._pupil] = INK
            stamp[self._glint] = EYE_WHITE

    def render(self, speaking: bool) -> bytes:
        t = self._tick
        self._tick += 1
        self._draw_design(t, speaking)

        f = self._frame
        np.copyto(f, self._background)

        # Scale the design region down with 2x2 supersampling; KEY pixels are transparent,
        # so the puppet's edges blend smoothly into the stage.
        # With n of the 4 samples solid: out = (stage * (4 - n) + sum of solid samples) / 4.
        acc = np.zeros((self._out_h, self._out_w, 3), dtype=np.uint16)
        count = np.zeros((self._out_h, self._out_w, 1), dtype=np.uint16)
        for idx in self._grid:
            s = self._design[idx]
            solid = ((s[..., 0] != KEY[0]) | (s[..., 1] != KEY[1]) | (s[..., 2] != KEY[2]))[..., None]
            acc += s * solid
            count += solid
        y0, x0 = self._out_y0, self._out_x0
        region = f[y0 : y0 + self._out_h, x0 : x0 + self._out_w, :3]
        region[:] = ((region * (4 - count) + acc) >> 2).astype(np.uint8)

        f[_LEDGE_Y:, :, :3] = self._booth
        return f.tobytes()
