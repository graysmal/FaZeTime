"""The picture a FaceTime Video caller sees: a simple animated face, drawn with numpy.

Python port of the idea in Chert's examples/video-agent/face.mjs: one RGBA frame per
call, 640x360 at 15 fps. The mouth moves while the agent speaks, the eyes blink every
four seconds, and a small bar slides along the bottom so a frozen picture is easy to
spot. Static layers and masks are precomputed, so a frame costs a few array copies.
"""

from __future__ import annotations

import math

import numpy as np

WIDTH = 640
HEIGHT = 360
FPS = 15

BACKGROUND = (14, 17, 28)
FACE = (236, 240, 245)
INK = (24, 28, 40)
RING_IDLE = (70, 82, 110)
RING_SPEAKING = (230, 40, 40)
BAR = (230, 40, 40)

_CX, _CY = WIDTH // 2, HEIGHT // 2 - 10
_RADIUS = int(HEIGHT * 0.36)
_RING = 7
_EYE_DX, _EYE_DY, _EYE_HALF_W, _EYE_HALF_H = 45, 35, 10, 14
_MOUTH_DY, _MOUTH_HALF_W = 45, 48
_BAR_W, _BAR_Y0, _BAR_Y1 = 40, HEIGHT - 22, HEIGHT - 12


def _rgba(color: tuple[int, int, int]) -> np.ndarray:
    return np.array((*color, 255), dtype=np.uint8)


class FaceRenderer:
    """Renders successive frames. render() returns WIDTH*HEIGHT*4 RGBA bytes."""

    def __init__(self) -> None:
        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
        dist2 = (xx - _CX) ** 2 + (yy - _CY) ** 2
        face_mask = dist2 < _RADIUS**2
        self._ring_mask = (dist2 >= _RADIUS**2) & (dist2 < (_RADIUS + _RING) ** 2)

        self._base = np.empty((HEIGHT, WIDTH, 4), dtype=np.uint8)
        self._base[:] = _rgba(BACKGROUND)
        self._base[face_mask] = _rgba(FACE)
        self._base[self._ring_mask] = _rgba(RING_IDLE)
        self._frame = np.empty_like(self._base)

        # Mouth masks for each half-height, cut to the mouth's bounding box.
        self._mouth_box = (
            slice(_CY + _MOUTH_DY - 22, _CY + _MOUTH_DY + 23),
            slice(_CX - _MOUTH_HALF_W, _CX + _MOUTH_HALF_W + 1),
        )
        by, bx = np.mgrid[self._mouth_box[0], self._mouth_box[1]]
        self._mouth_masks = {
            h: ((bx - _CX) / _MOUTH_HALF_W) ** 2 + ((by - (_CY + _MOUTH_DY)) / h) ** 2 < 1
            for h in range(3, 23)
        }
        self._tick = 0

    def render(self, speaking: bool) -> bytes:
        tick = self._tick
        self._tick += 1
        f = self._frame
        np.copyto(f, self._base)

        if speaking:
            f[self._ring_mask] = _rgba(RING_SPEAKING)

        blink = tick % 60 < 3
        half_h = 2 if blink else _EYE_HALF_H
        for ex in (_CX - _EYE_DX, _CX + _EYE_DX):
            f[_CY - _EYE_DY - half_h : _CY - _EYE_DY + half_h, ex - _EYE_HALF_W : ex + _EYE_HALF_W] = _rgba(INK)

        mouth_h = int(6 + 14 * abs(math.sin(tick * 0.8))) if speaking else 4
        mouth = f[self._mouth_box]
        mouth[self._mouth_masks[max(3, min(22, mouth_h))]] = _rgba(INK)

        x0 = (tick * 6) % (WIDTH - _BAR_W)
        f[_BAR_Y0:_BAR_Y1, x0 : x0 + _BAR_W] = _rgba(BAR)
        return f.tobytes()


def write_png(path: str, rgba: bytes, width: int = WIDTH, height: int = HEIGHT) -> None:
    """Save one frame as a PNG (stdlib only), for previews and tests."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
