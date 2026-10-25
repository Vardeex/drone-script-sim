"""Test dokumentacji: każdy zrzut ekranu w README/poradniku istnieje i nie jest pusty.

Sprawdzenie jest programowe, bez otwierania obrazu w przeglądarce: czytamy
nagłówek PNG (szerokość/wysokość z ``IHDR``) i wielkość pliku. Pusty zrzut
(jednolite tło, „biała plama") ma mało kilobajtów, więc próg rozmiaru go łapie.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
#: minimalny rozmiar PNG, poniżej którego zrzut jest podejrzanie pusty
MIN_BYTES = 20_000
#: minimalna szerokość zrzutu [px]
MIN_WIDTH = 800
DOCS = (PROJECT_ROOT / "README.md", PROJECT_ROOT / "docs" / "PORADNIK.md")
IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)]+\.png)\)")


def png_size(path: Path) -> tuple[int, int]:
    """Odczytaj ``(szerokość, wysokość)`` z nagłówka PNG (bez zewnętrznych bibliotek)."""
    raw = path.read_bytes()[:33]
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name}: to nie jest PNG"
    assert raw[12:16] == b"IHDR", f"{path.name}: brak nagłówka IHDR"
    width, height = struct.unpack(">II", raw[16:24])
    return int(width), int(height)


def _images() -> list:
    """Wszystkie obrazy linkowane z dokumentacji (ścieżki bezwzględne)."""
    found = []
    for document in DOCS:
        assert document.exists(), document
        text = document.read_text(encoding="utf-8")
        for relative in IMAGE_LINK.findall(text):
            target = (document.parent / relative).resolve()
            found.append(pytest.param(target, id=f"{document.name}:{relative}"))
    return found


def test_docs_link_at_least_the_new_screens():
    """Dokumentacja pokazuje nowe funkcje (lot ręczny, edytor, porównanie)."""
    text = "\n".join(document.read_text(encoding="utf-8") for document in DOCS)
    for name in ("10-lot-reczny.png", "11-edytor-ostrzezenia.png",
                 "12-porownanie.png"):
        assert name in text, f"brak zrzutu {name} w dokumentacji"


@pytest.mark.parametrize("image", _images())
def test_screenshot_is_not_empty(image: Path):
    """Każdy zrzut istnieje, jest PNG i nie jest pustym prostokątem."""
    assert image.exists(), f"brak pliku {image}"
    size = image.stat().st_size
    assert size >= MIN_BYTES, f"{image.name}: tylko {size // 1024} kB - podejrzanie pusty"
    width, height = png_size(image)
    assert width >= MIN_WIDTH, f"{image.name}: szerokość {width} px"
    assert height >= 400, f"{image.name}: wysokość {height} px"
