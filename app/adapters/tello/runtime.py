"""Stan adaptera w podprocesie sandboxu (tworzy kontroler Tello).

Mock ``djitellopy`` pobiera z tego modułu jeden współdzielony kontroler,
powiązany z symulacją z :mod:`app.sandbox_runtime`.
"""

from __future__ import annotations

from typing import Optional

from .adapter import TelloController

_CONTROLLER: Optional[TelloController] = None


def controller() -> TelloController:
    """Zwróć (i w razie potrzeby utwórz) kontroler dla bieżącej symulacji."""
    global _CONTROLLER
    if _CONTROLLER is None:
        from app import sandbox_runtime

        sim = sandbox_runtime.get_sim()
        if sim is None:
            raise RuntimeError("Symulacja nie jest uruchomiona w sandboxie.")
        _CONTROLLER = TelloController(sim)
    return _CONTROLLER


def reset() -> None:
    global _CONTROLLER
    _CONTROLLER = None
