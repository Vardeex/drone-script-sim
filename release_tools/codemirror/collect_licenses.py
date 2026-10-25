#!/usr/bin/env python3
"""Zbiera licencje pakietów CodeMirror użytych w bundlu do jednego pliku.

Wymóg: bundle w ``app/static/vendor/codemirror`` musi mieć **dołączoną
licencję** (wszystkie pakiety są na MIT). Uruchamiane po ``npm install``
w katalogu roboczym budowania (patrz ``tools`` w dokumentacji wydania).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _utf8_console() -> None:
    """Wymuś UTF-8 na ``stdout``/``stderr`` (konsola Windows to cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


_utf8_console()

PACKAGES = [
    "@codemirror/state", "@codemirror/view", "@codemirror/commands",
    "@codemirror/language", "@codemirror/autocomplete", "@codemirror/lang-python",
    "@lezer/highlight", "@lezer/common", "@lezer/python", "@lezer/lr",
    "@marijn/find-cluster-break", "crelt", "style-mod", "w3c-keyname",
]


def license_text(package_dir: Path) -> str:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        candidate = package_dir / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def main(argv: list[str]) -> int:
    node_modules = Path(argv[1] if len(argv) > 1 else ".") / "node_modules"
    output = Path(argv[2] if len(argv) > 2 else "LICENSE")
    blocks = [
        "CodeMirror 6 - licencje pakietów użytych w codemirror.bundle.js",
        "=" * 72,
        "",
        "Bundle zawiera wyłącznie kod na licencji MIT (CodeMirror i Lezer:",
        "Marijn Haverbeke i współtwórcy). Poniżej pełne teksty licencji.",
        "",
    ]
    missing = []
    for package in PACKAGES:
        directory = node_modules / package
        text = license_text(directory) if directory.exists() else ""
        if not text:
            missing.append(package)
            continue
        blocks += ["-" * 72, f"Pakiet: {package}", "-" * 72, text, ""]
    output.write_text("\n".join(blocks), encoding="utf-8")
    print(f"zapisano {output} ({len(PACKAGES) - len(missing)} pakietów)")
    if missing:
        print(f"brak licencji dla: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
