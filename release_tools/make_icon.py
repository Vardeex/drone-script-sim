"""Generuje ikonę aplikacji ``release_tools/assets/dronesim.ico`` (bez zależności).

Ikona jest **własna i geometryczna**: ciemne zaokrąglone tło, cztery wirniki
i korpus - czytelny symbol quadcoptera, **bez** logo DJI/Tello (nie kopiujemy
znaków towarowych).

Format: ICO z wpisami PNG (Windows Vista+ czyta takie bez problemu), rozmiary
16, 24, 32, 48, 64, 128, 256 px. Wszystko liczone w czystym Pythonie (zlib),
więc budowanie paczki nie wymaga Pillow.

Uruchomienie::

    python release_tools/make_icon.py           # zapisz .ico (nadpisuje)
    python release_tools/make_icon.py --check   # tylko sprawdź, czy istnieje
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS / "dronesim.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: kolory (R, G, B, A)
BG = (11, 18, 32, 255)          # ciemne tło (jak motyw aplikacji)
BG_EDGE = (23, 34, 56, 255)     # jaśniejsza krawędź
BODY = (56, 189, 248, 255)      # akcent z UI
ROTOR = (226, 232, 240, 255)    # jasne wirniki
ARM = (148, 163, 184, 255)      # ramiona


def _blank(size: int) -> List[List[Tuple[int, int, int, int]]]:
    return [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]


def _rounded_rect(pixels, x0, y0, x1, y1, radius, color) -> None:
    """Wypełnij prostokąt z zaokrąglonymi narożnikami."""
    for y in range(max(0, y0), min(len(pixels), y1)):
        for x in range(max(0, x0), min(len(pixels[0]), x1)):
            cx = min(x - x0, x1 - 1 - x)          # odległość od narożnika
            cy = min(y - y0, y1 - 1 - y)
            if cx < radius and cy < radius:
                dx, dy = radius - cx, radius - cy
                if dx * dx + dy * dy > radius * radius:
                    continue
            pixels[y][x] = color


def _disc(pixels, cx, cy, radius, color) -> None:
    if radius <= 0:
        return
    r2 = radius * radius
    for y in range(max(0, int(cy - radius - 1)), min(len(pixels), int(cy + radius + 2))):
        for x in range(max(0, int(cx - radius - 1)),
                       min(len(pixels[0]), int(cx + radius + 2))):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                pixels[y][x] = color


def _thick_line(pixels, x0, y0, x1, y1, width, color) -> None:
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    for index in range(steps + 1):
        t = index / steps
        _disc(pixels, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width / 2.0, color)


def draw(size: int) -> List[List[Tuple[int, int, int, int]]]:
    """Narysuj ikonę w danym rozmiarze (skala liczona z rozmiaru)."""
    pixels = _blank(size)
    unit = size / 32.0                     # rysujemy w siatce 32 x 32
    radius = max(2, round(6 * unit))
    _rounded_rect(pixels, 1, 1, size - 1, size - 1, radius, BG_EDGE)
    inset = max(2, round(2 * unit))
    _rounded_rect(pixels, inset, inset, size - inset, size - inset,
                  max(1, radius - 1), BG)

    center = size / 2.0
    rotor_r = max(1.0, 3.4 * unit)
    offset = 10.0 * unit
    arm_w = max(1.0, 1.6 * unit)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        _thick_line(pixels, center, center, center + dx * offset,
                    center + dy * offset, arm_w, ARM)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        _disc(pixels, center + dx * offset, center + dy * offset, rotor_r, ROTOR)
    _disc(pixels, center, center, max(1.6, 4.2 * unit), BODY)
    return pixels


def png_bytes(pixels: Sequence[Sequence[Tuple[int, int, int, int]]]) -> bytes:
    """Zakoduj piksele jako PNG (RGBA, 8 bitów)."""
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)                      # filtr wiersza: brak
        for r, g, b, a in row:
            raw.extend((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def build_ico(sizes: Sequence[int] = SIZES) -> bytes:
    """Złóż plik ICO z obrazów PNG (każdy rozmiar = jeden wpis)."""
    images = [png_bytes(draw(size)) for size in sizes]
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    for size, data in zip(sizes, images):
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)
    return header + entries + b"".join(images)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ikona aplikacji (ICO)")
    parser.add_argument("--check", action="store_true",
                        help="tylko sprawdź, czy plik istnieje (nie zapisuj)")
    parser.add_argument("--out", default=str(ICON_PATH))
    args = parser.parse_args(list(argv) if argv is not None else None)

    target = Path(args.out)
    if args.check:
        ok = target.exists() and target.stat().st_size > 1000
        size = target.stat().st_size if target.exists() else 0
        print(f"{target}: {'OK' if ok else 'BRAK'} ({size} B)")
        return 0 if ok else 1
    target.parent.mkdir(parents=True, exist_ok=True)
    data = build_ico()
    target.write_bytes(data)
    print(f"zapisano {target} ({len(data)} B, rozmiary: "
          f"{', '.join(str(size) for size in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
