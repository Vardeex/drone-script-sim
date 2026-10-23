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
        """Wyślij wychylenia RC (wartości już w konwencji **djitellopy**).

        ``Executor`` przygotowuje je w konwencji docelowej:
        ``vx`` = ``left_right`` (dodatnie = **w prawo**),
        ``vy`` = ``forward_backward`` (dodatnie = przód),
        ``vz`` = ``up_down`` (dodatnie = góra),
        ``yaw_rate`` = ``yaw`` (dodatnie = obrót **w prawo**, zgodnie z zegarem).

        Nazwy argumentów (``vx``/``vy``) pochodzą z interfejsu ``MotionBackend``,
        ale znaczenie jest tu „kanałowe”, bo taka jest kolejność ``rc a b c d``.
        """
        lr = _clamp_rc(vx)
        fb = _clamp_rc(vy)
        ud = _clamp_rc(vz)
        yaw = _clamp_rc(yaw_rate)
        try:
            self.drone.send_rc_control(lr, fb, ud, yaw)
        except Exception as exc:  # wyjątki drona przekazujemy dalej z kontekstem
            self.stop()
            raise BackendError(f"Błąd send_rc_control({lr}, {fb}, {ud}, {yaw}): {exc}") from exc

    def send_profile(self, vx_cm_s: float, vy_cm_s: float, v_up_cm_s: float,
                     yaw_rate_dps: float, world: bool = False,
                     yaw_deg: Optional[float] = None) -> bool:
        """Przekaż symulatorowi prędkości ruchu, zamiast wychyleń RC.

        Wywoływane tylko wtedy, gdy dron udostępnia ``send_dronemoves_profile``
        (mock symulatora). Prawdziwe ``djitellopy`` nie ma tej metody i wtedy
        sterowanie idzie przez :meth:`rc`.

        :param vx_cm_s: prędkość „do przodu” (``world=True``: globalna X)
        :param vy_cm_s: prędkość „w lewo” (``world=True``: globalna Y)
        :param v_up_cm_s: prędkość pionowa (cm/s)
        :param yaw_rate_dps: prędkość obrotu (°/s, dodatnia = w lewo)
        :param world: czy ``vx``/``vy`` są w układzie globalnym (tak liczy planer)
        :param yaw_deg: kurs nosa z planu (°, dodatni = w lewo)
        """
        func = getattr(self.drone, "send_dronemoves_profile", None)
        if not callable(func):
            return False
        func(vx_cm_s, vy_cm_s, v_up_cm_s, yaw_rate_dps, bool(world), yaw_deg)
        return True

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
    def get_yaw(self) -> Optional[float]:
        """Rzeczywisty kurs nosa (konwencja API: CW+, stopnie)."""
        try:
            return float(self.drone.get_yaw())
        except Exception:
            return None

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
