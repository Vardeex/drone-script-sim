"""Bezpieczeństwo lotu: preflight, geofence, powrót do startu, nadzór baterii.

Moduł korzysta wyłącznie z publicznego API drona (``djitellopy``) i z szacowanej
pozycji pilota, więc działa tak samo z symulatorem (mock) jak z Tello.

Progi preflight (założenia - patrz README „Bezpieczeństwo”):

* **bateria**: błąd < 50 %, ostrzeżenie < 60 % (Tello zużywa ~1 % na 10 s lotu;
  przy 50 % zostaje ok. 8 min, z zapasem na powrót),
* **temperatura** (``get_highest_temperature``, °C): błąd >= 80, ostrzeżenie
  >= 70 - Tello podaje ``temph`` z telemetrii; 80 °C to ok. górna granica pracy
  bez ryzyka przegrzania układów,
* **Wi-Fi** (``query_wifi_signal_noise_ratio``): brak odczytu = ostrzeżenie,
  SNR < 10 dB = ostrzeżenie (przy < 5 dB obraz/sterowanie zaczynają przerywać),
* **czy dron odpowiada**: ``connect()`` i ``query_sdk_version()``,
* **czy dron stoi na ziemi**: ``get_height()`` < 20 cm przed startem,
* **czas trasy vs bateria**: szacowany czas z planu (``plan_eta_s``) i zapas
  zwrotny 60 s - ostrzeżenie, gdy lot zjada więcej niż dostępne 80 % baterii.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

__all__ = [
    "BATTERY_ERROR", "BATTERY_WARNING", "TEMP_ERROR", "TEMP_WARNING",
    "SNR_WARNING", "GROUND_HEIGHT_CM", "PreflightError", "PreflightReport",
    "Check", "preflight", "safe_start", "Geofence",
]

#: próg błędu baterii [%] - poniżej nie startujemy
BATTERY_ERROR = 50
#: próg ostrzeżenia baterii [%]
BATTERY_WARNING = 60
#: najwyższa temperatura [°C] - powyżej błąd
TEMP_ERROR = 80
#: najwyższa temperatura [°C] - powyżej ostrzeżenie
TEMP_WARNING = 70
#: minimalny SNR Wi-Fi [dB], poniżej ostrzeżenie
SNR_WARNING = 10
#: wysokość [cm] uznawana za „na ziemi”
GROUND_HEIGHT_CM = 20
#: zapas czasu na powrót i lądowanie [s]
RETURN_MARGIN_S = 60


class PreflightError(RuntimeError):
    """Preflight znalazł błąd krytyczny - start jest wstrzymany."""


@dataclass
class Check:
    """Pojedynczy test preflight: ``level`` to ``ok``/``warning``/``error``."""

    name: str
    level: str
    message: str

    def as_dict(self) -> dict:
        return {"name": self.name, "level": self.level, "message": self.message}


@dataclass
class PreflightReport:
    """Raport preflight: lista testów + werdykt."""

    checks: List[Check] = field(default_factory=list)

    def add(self, name: str, level: str, message: str) -> None:
        self.checks.append(Check(name, level, message))

    @property
    def errors(self) -> List[Check]:
        return [c for c in self.checks if c.level == "error"]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checks": [c.as_dict() for c in self.checks],
                "errors": [c.message for c in self.errors],
                "warnings": [c.message for c in self.warnings]}

    def __str__(self) -> str:                     # pragma: no cover - diagnostyka
        lines = [f"{c.level.upper():7} {c.name}: {c.message}" for c in self.checks]
        return "\n".join(lines)


def _read(drone: Any, name: str) -> Any:
    """Wywołaj metodę drona, jeśli istnieje; ``None`` przy braku lub błędzie."""
    method = getattr(drone, name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _parse_snr(value: Any) -> Optional[float]:
    """Wyciągnij SNR [dB] z odpowiedzi Tello (np. ``"24"`` albo ``"snr:24"``)."""
    if value is None:
        return None
    text = str(value)
    digits = ""
    for char in text:
        if char.isdigit() or (char == "-" and not digits) or (char == "." and digits):
            digits += char
        elif digits:
            break
    try:
        return float(digits)
    except ValueError:
        return None


def preflight(drone: Any, *, battery_error: int = BATTERY_ERROR,
              battery_warning: int = BATTERY_WARNING,
              temp_error: float = TEMP_ERROR, temp_warning: float = TEMP_WARNING,
              plan_eta_s: Optional[float] = None,
              connect: bool = False) -> PreflightReport:
    """Sprawdź, czy można startować. Zwraca raport (nie startuje drona).

    :param drone: obiekt drona (``djitellopy.Tello`` lub mock symulatora)
    :param plan_eta_s: szacowany czas planowanego lotu [s] (opcjonalnie)
    :param connect: jeśli ``True``, wywołaj ``drone.connect()`` (i sprawdź SDK)
    """
    report = PreflightReport()

    if connect:
        method = getattr(drone, "connect", None)
        if callable(method):
            try:
                method()
            except Exception as exc:                 # noqa: BLE001 - raport
                report.add("połączenie", "error", f"Brak połączenia z dronem: {exc}")

    sdk = _read(drone, "query_sdk_version")
    if sdk in (None, "", "None"):
        report.add("dron", "warning", "Brak odpowiedzi na zapytanie o wersję SDK "
                                      "- sprawdź połączenie z dronem.")
    else:
        report.add("dron", "ok", f"Dron odpowiada (SDK {sdk}).")

    battery = _read(drone, "get_battery")
    if battery is None:
        report.add("bateria", "warning", "Brak odczytu baterii.")
    elif battery < battery_error:
        report.add("bateria", "error",
                   f"Bateria {battery}% < {battery_error}% - start wstrzymany.")
    elif battery < battery_warning:
        report.add("bateria", "warning",
                   f"Bateria {battery}% - poniżej zalecanych {battery_warning}%.")
    else:
        report.add("bateria", "ok", f"Bateria {battery}%.")

    temperature = _read(drone, "get_highest_temperature")
    if temperature is None:
        temperature = _read(drone, "get_temperature")
    if temperature is None:
        report.add("temperatura", "warning", "Brak odczytu temperatury.")
    elif float(temperature) >= temp_error:
        report.add("temperatura", "error",
                   f"Temperatura {float(temperature):.0f} °C >= {temp_error:.0f} °C "
                   "- dron może się przegrzać.")
    elif float(temperature) >= temp_warning:
        report.add("temperatura", "warning",
                   f"Temperatura {float(temperature):.0f} °C - wysoka "
                   f"(ostrzeżenie od {temp_warning:.0f} °C).")
    else:
        report.add("temperatura", "ok", f"Temperatura {float(temperature):.0f} °C.")

    snr = _parse_snr(_read(drone, "query_wifi_signal_noise_ratio"))
    if snr is None:
        report.add("wifi", "warning", "Brak odczytu sygnału Wi-Fi "
                                      "(to nie blokuje startu).")
    elif snr < SNR_WARNING:
        report.add("wifi", "warning", f"SNR Wi-Fi {snr:.0f} dB - słaby sygnał "
                                      f"(zalecane >= {SNR_WARNING} dB).")
    else:
        report.add("wifi", "ok", f"SNR Wi-Fi {snr:.0f} dB.")

    height = _read(drone, "get_height")
    if height is None:
        report.add("na ziemi", "warning", "Brak odczytu wysokości.")
    elif float(height) > GROUND_HEIGHT_CM:
        report.add("na ziemi", "error",
                   f"Dron jest na {float(height):.0f} cm - start wymaga postawienia "
                   "go na ziemi.")
    else:
        report.add("na ziemi", "ok", f"Wysokość {float(height):.0f} cm (na ziemi).")

    if plan_eta_s is not None and battery is not None:
        # Tello: ~1 % baterii na 10 s lotu -> dostępne 80 % daje 800 s minus zapas
        available = max((battery - 10) * 10.0 - RETURN_MARGIN_S, 0.0)
        if plan_eta_s > available:
            report.add("czas trasy", "warning",
                       f"Planowany lot {plan_eta_s:.0f} s to więcej niż zapas baterii "
                       f"{available:.0f} s - rozważ krótszą trasę.")
        else:
            report.add("czas trasy", "ok",
                       f"Planowany lot {plan_eta_s:.0f} s (zapas {available:.0f} s).")
    return report


class Geofence:
    """Granice bezpiecznego rejonu: wysokość, odległość od startu, prostokąt XY.

    :param max_height_cm: maksymalna wysokość nad ziemią
    :param max_radius_cm: maksymalna odległość od punktu startu (koło)
    :param box_cm: opcjonalny prostokąt ``(x_min, x_max, y_min, y_max)``
    """

    def __init__(self, max_height_cm: float = 300.0, max_radius_cm: float = 500.0,
                 box_cm: Optional[Sequence[float]] = None) -> None:
        self.max_height_cm = float(max_height_cm)
        self.max_radius_cm = float(max_radius_cm)
        self.box_cm = tuple(float(v) for v in box_cm) if box_cm else None

    def violations(self, x: float, y: float, height_cm: float) -> List[str]:
        """Zwróć listę naruszeń dla pozycji ``(x, y)`` i wysokości nad ziemią."""
        problems: List[str] = []
        if height_cm > self.max_height_cm:
            problems.append(f"Wysokość {height_cm:.0f} cm > {self.max_height_cm:.0f} cm.")
        radius = (x * x + y * y) ** 0.5
        if radius > self.max_radius_cm:
            problems.append(f"Odległość {radius:.0f} cm od startu > "
                            f"{self.max_radius_cm:.0f} cm.")
        if self.box_cm:
            x_min, x_max, y_min, y_max = self.box_cm
            if not (x_min <= x <= x_max and y_min <= y <= y_max):
                problems.append(f"Pozycja ({x:.0f}, {y:.0f}) poza prostokątem "
                                f"X {x_min:.0f}..{x_max:.0f}, Y {y_min:.0f}..{y_max:.0f}.")
        return problems

    def check(self, x: float, y: float, height_cm: float) -> None:
        """Rzuć ``SafetyError`` (import lokalnie), gdy pozycja łamie granice."""
        problems = self.violations(x, y, height_cm)
        if problems:
            from .pilot import SafetyError

            raise SafetyError("Geofence: " + " ".join(problems))


def safe_start(drone: Any, *, pilot: Any = None, confirm: bool = False,
               countdown_s: float = 0.0, plan_eta_s: Optional[float] = None,
               input_fn: Optional[Callable[[str], str]] = None,
               **options: Any) -> PreflightReport:
    """Preflight, potem ``takeoff`` i sprawdzenie, czy dron faktycznie wystartował.

    :param drone: obiekt drona (``djitellopy.Tello``)
    :param pilot: opcjonalny ``Pilot`` - jeśli podany, po starcie ustawia jego
        wysokość odniesienia (``_home_z``)
    :param confirm: czekaj na potwierdzenie z klawiatury (Enter) przed startem
    :param countdown_s: odliczanie przed ``takeoff`` [s]
    :param plan_eta_s: szacowany czas planowanego lotu (sprawdzany w preflight)
    :param input_fn: funkcja czytająca klawiaturę (domyślnie ``input``)
    :raises PreflightError: gdy preflight wykryje błąd - dron NIE startuje
    """
    report = preflight(drone, plan_eta_s=plan_eta_s,
                       connect=options.pop("connect", False), **options)
    if not report.ok:
        raise PreflightError("Preflight nieudany:\n" + "\n".join(
            c.message for c in report.errors))
    for warning in report.warnings:
        print(f"[preflight] OSTRZEŻENIE: {warning.message}")

    if confirm:
        reader = input_fn or input
        try:
            reader("Sprawdź otoczenie i naciśnij Enter, aby wystartować: ")
        except EOFError:
            pass

    if countdown_s > 0:
        remaining = float(countdown_s)
        while remaining > 0:
            print(f"Start za {remaining:.0f} s...")
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

    takeoff = getattr(drone, "takeoff", None)
    if not callable(takeoff):
        raise PreflightError("Obiekt drona nie ma metody takeoff().")
    takeoff()

    height = _read(drone, "get_height")
    report.add("takeoff", "ok" if height else "warning",
               f"Dron w powietrzu na {float(height or 0):.0f} cm."
               if height else "Po takeoff brak odczytu wysokości.")
    if pilot is not None and height is not None:
        pilot._home_z = float(height)
    return report

    return report
