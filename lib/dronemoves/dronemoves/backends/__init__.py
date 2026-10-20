"""Backendy ruchu (jeden na rodzinę dronów / bibliotekę sterującą)."""

from .base import BackendError, MotionBackend

__all__ = ["BackendError", "MotionBackend", "TelloBackend"]


def __getattr__(name: str):
    """Leniwe wczytywanie ``TelloBackend`` (bez twardej zależności od djitellopy)."""
    if name == "TelloBackend":
        from .tello import TelloBackend

        return TelloBackend
    raise AttributeError(name)
