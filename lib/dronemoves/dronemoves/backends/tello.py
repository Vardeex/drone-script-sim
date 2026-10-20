"""Backend ruchu dla DJI Tello (biblioteka ``djitellopy``).

Rdzeń ``dronemoves`` nie zależy od ``djitellopy`` - ten moduł importuje ją
leniwie i przy braku biblioteki wyjaśnia, jak ją doinstalować::

    pip install dronemoves[tello]

Używa tylko publicznego API: ``send_rc_control``, ``go_xyz_speed``,
``curve_xyz_speed``, ``get_battery``, ``get_height``. Nie sięga do środka
symulatora - opcjonalny ``annotate`` jest wywoływany tylko wtedy, gdy obiekt
drona go udostępnia (mock symulatora).
"""

from __future__ import annotations

from typing import Any, Optional

from .base import BackendAdapter, BackendError, MotionBackend

__all__ = ["TelloBackend", "check_djitellopy", "backend_for"]

INSTALL_HINT = (
    "Brak biblioteki 'djitellopy', która jest potrzebna do sterowania DJI Tello.\n"
    "Doinstaluj backend Tello poleceniem:\n"
    "    pip install dronemoves[tello]\n"
    "albo bezpośrednio:\n"
    "    pip install djitellopy"
)


def check_djitellopy() -> Any:
    """Zaimportuj ``djitellopy`` albo rzuć ``ImportError`` z instrukcją."""
    try:
        import djitellopy  # noqa: F401
    except ImportError as exc:  # pragma: no cover - zależy od środowiska
        raise ImportError(INSTALL_HINT) from exc
    return djitellopy


def _clamp_rc(value: float) -> int:
    """Zamień wartość na całkowite wychylenie RC w zakresie -100..100."""
    return int(max(-100, min(100, round(value))))


class TelloBackend(BackendAdapter):
    """Backend dla ``djitellopy.Tello`` (mock w symulatorze, prawdziwy dron)."""

    name = "tello"

    def __init__(self, drone: Any) -> None:
        super().__init__(drone)
        if not hasattr(drone, "send_rc_control"):
            raise TypeError(
                "Obiekt drona nie ma metody send_rc_control - to nie jest "
                "Tello/djitellopy. Użyj odpowiedniego backendu."
            )

    # ------------------------------------------------------------------- RC
    def rc(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        """``vx`` przód, ``vy`` lewo, ``vz`` góra, ``yaw_rate`` w lewo (wartości RC)."""
        lr = _clamp_rc(vy)
        fb = _clamp_rc(vx)
        ud = _clamp_rc(vz)
        yaw = _clamp_rc(yaw_rate)
        try:
            self.drone.send_rc_control(lr, fb, ud, yaw)
        except Exception as exc:  # wyjątki drona przekazujemy dalej z kontekstem
            self.stop()
            raise BackendError(f"Błąd send_rc_control({lr}, {fb}, {ud}, {yaw}): {exc}") from exc

    def stop(self) -> None:
        try:
            self.drone.send_rc_control(0, 0, 0, 0)
        except Exception:
            # zatrzymanie nie może rzucać - to ścieżka bezpieczeństwa
            pass

    # ---------------------------------------------------------------- native
    def go(self, x: int, y: int, z: int, speed: int) -> None:
        if not self._call("go_xyz_speed", x, y, z, speed):
            raise BackendError("Dron nie udostępnia go_xyz_speed (wymaga djitellopy)")

    def curve(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, speed: int) -> None:
        if not self._call("curve_xyz_speed", x1, y1, z1, x2, y2, z2, speed):
            raise BackendError("Dron nie udostępnia curve_xyz_speed")

    def supports_native(self) -> bool:
        return hasattr(self.drone, "curve_xyz_speed") and hasattr(self.drone, "go_xyz_speed")

    # --------------------------------------------------------------- odczyty
    def get_battery(self) -> Optional[int]:
        try:
            return int(self.drone.get_battery())
        except Exception:
            return None

    def get_height(self) -> Optional[int]:
        try:
            return int(self.drone.get_height())
        except Exception:
            return None

    # ------------------------------------------------------ integracja/UI
    def annotate(self, label: str) -> None:
        """Wywołaj ``annotate`` tylko jeśli dron je ma (mock symulatora)."""
        func = getattr(self.drone, "annotate", None)
        if callable(func):
            func(label)


def backend_for(drone: Any) -> MotionBackend:
    """Wybierz backend dla obiektu drona.

    Rozpoznaje ``djitellopy.Tello`` / mock symulatora po metodzie
    ``send_rc_control``; inne obiekty wymagają własnego backendu.
    """
    if hasattr(drone, "send_rc_control"):
        return TelloBackend(drone)
    raise TypeError(
        "Nieznany typ obiektu drona - brak send_rc_control. "
        "Zaimplementuj backend w dronemoves.backends i przekaż go do Pilot(backend=...)."
    )
