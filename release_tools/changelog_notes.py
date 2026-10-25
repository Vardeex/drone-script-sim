"""Wyciąga z ``CHANGELOG.md`` sekcję dla danej wersji (notatki wydania).

Używane przez ``.github/workflows/release.yml``: notatki GitHub Release
pochodzą z CHANGELOG-a, a nie z ręcznie przepisywanego tekstu (jedno źródło
prawdy - mniej okazji, żeby wydanie opisywało coś innego niż kod).

Kolejność dopasowania:

1. sekcja z dokładną wersją (``## [0.3.0]`` albo ``## [v0.3.0]``),
2. sekcja ``[Niewydane]`` (typowa sytuacja: wersja w ``app/__init__.py`` jest
   podniesiona, a wpis w CHANGELOG-u wciąż czeka w „Niewydane”),
3. pierwsza sekcja wersji w pliku (z ostrzeżeniem na stderr).

Uruchomienie:

    python release_tools/changelog_notes.py --version v0.3.0 --out release_notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
HEADER = re.compile(r"^##\s+(?P<title>.+?)\s*$")


def sections(text: str) -> List[tuple]:
    """Podziel CHANGELOG na ``(tytuł, treść)`` - od ``## nagłówek`` do następnego."""
    result: List[tuple] = []
    title: Optional[str] = None
    body: List[str] = []
    for line in text.splitlines():
        match = HEADER.match(line)
        if match:
            if title is not None:
                result.append((title, "\n".join(body).strip()))
            title, body = match.group("title"), []
        elif title is not None:
            body.append(line)
    if title is not None:
        result.append((title, "\n".join(body).strip()))
    return result


def _normalise(version: str) -> str:
    """``v0.3.0`` / ``0.3.0`` -> ``0.3.0`` (tag GitHub bywa z ``v``)."""
    return version.strip().lstrip("vV")


def notes_for(text: str, version: str) -> str:
    """Treść sekcji CHANGELOG-a dla ``version`` (z fallbackiem, patrz docstring)."""
    wanted = _normalise(version)
    found = sections(text)
    for title, body in found:
        if _normalise(title.split("]")[0].strip("[ ")) == wanted:
            return body
    for title, body in found:
        if "niewydane" in title.lower() or "unreleased" in title.lower():
            print(f"[notes] brak sekcji {wanted} - używam „{title}”", file=sys.stderr)
            return body
    if found:
        print(f"[notes] brak sekcji {wanted} - używam pierwszej „{found[0][0]}”",
              file=sys.stderr)
        return found[0][1]
    return ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Notatki wydania z CHANGELOG.md")
    parser.add_argument("--version", required=True, help="wersja albo tag (np. v0.3.0)")
    parser.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    parser.add_argument("--out", default=None, help="plik wyjściowy (domyślnie stdout)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    text = Path(args.changelog).read_text(encoding="utf-8")
    body = notes_for(text, args.version) or "Brak wpisu w CHANGELOG.md dla tej wersji."
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"[notes] zapisano {args.out} ({len(body)} znaków)")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
