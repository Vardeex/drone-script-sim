"""Testy modelu 3D drona (moduł JS) uruchamiane z pytest.

Model jest w ``app/static/js/drone_model.js``; test sprawdza obrys
98 × 92,5 × 41 mm (tolerancja ±3 mm) i warunki geometryczne z zadania.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "drone_model_bbox.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="brak Node.js")
def test_drone_model_dimensions():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert "dlugosc: 98.50" in output, output
    assert "szerokosc: 92.50" in output, output


@pytest.mark.skipif(shutil.which("node") is None, reason="brak Node.js")
def test_drone_model_has_four_rotors_and_guards_option():
    source = (ROOT / "app" / "static" / "js" / "drone_model.js").read_text(encoding="utf-8")
    assert "guards = true" in source            # osłony włączane parametrem
    assert "rotors.push(rotor)" in source       # cztery śmigła w pętli po narożnikach
    assert "MOTOR_XY" in source                 # osie silników w punktach ±27, ±24
    assert "accent" in source                   # akcent przednich osłon
    # bez logo i napisów na modelu: brak tekstur z tekstem
    assert "CanvasTexture" not in source and "fillText" not in source
