"""Profil kalibracji: przelicznik RC (``-100..100``) na cm/s i °/s.

Biblioteka **i** symulator używają tego samego modelu sterowania RC, żeby trasa
w 3D odpowiadała temu, co zakłada biblioteka:

    prędkość liniowa [cm/s] = rc / 100 * max_speed_cm_s
    prędkość obrotu [°/s]   = rc / 100 * max_yaw_rate_dps

(opcjonalnie z nieliniowością ``response_exponent``, domyślnie liniowo).

Profil domyślny odpowiada DJI Tello. Własny profil (zmierzony taśmą na
prawdziwym dronie) można zapisać do JSON skryptem ``calibrate.py``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = ["CalibrationProfile", "TELLO_PROFILE", "load_profile", "save_profile"]

#: Domyślna martwa strefa drążków.
DEFAULT_DEADZONE = 0


@dataclass(frozen=True)
class CalibrationProfile:
    """Parametry zamiany wychylenia drążków RC na prędkości.

    :param name: nazwa profilu (informacyjna)
    :param max_speed_cm_s: prędkość przy pełnym wychyleniu ``rc=100`` (cm/s)
    :param max_yaw_rate_dps: prędkość obrotu przy ``rc=100`` (°/s)
    :param max_vertical_cm_s: prędkość pionowa przy ``ud=100`` (cm/s)
    :param response_delay_s: opóźnienie reakcji drona (s)
    :param deadzone: wychylenie poniżej tej wartości traktowane jako 0
    :param response_exponent: wykładnik nieliniowości (1.0 = liniowo)
    :param max_accel_cm_s2: maksymalne przyspieszenie przyjmowane przez planer
    """

    name: str = "tello-default"
    max_speed_cm_s: float = 50.0
    max_yaw_rate_dps: float = 90.0
    max_vertical_cm_s: float = 50.0
    response_delay_s: float = 0.15
    deadzone: int = DEFAULT_DEADZONE
    response_exponent: float = 1.0
    max_accel_cm_s2: float = 150.0
    notes: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ przeliczniki
    def _shape(self, rc: float) -> float:
        """Znormalizowane wychylenie [-1, 1] z martwą strefą i nieliniowością."""
        value = max(-100.0, min(100.0, float(rc))) / 100.0
        if abs(value) * 100.0 <= self.deadzone:
            return 0.0
        sign = -1.0 if value < 0 else 1.0
        return sign * (abs(value) ** self.response_exponent)

    def rc_to_speed(self, rc: float) -> float:
        """Wychylenie ``rc`` -> prędkość liniowa [cm/s]."""
        return self._shape(rc) * self.max_speed_cm_s

    def rc_to_yaw_rate(self, rc: float) -> float:
        """Wychylenie ``rc`` (obrót) -> prędkość kątowa [°/s] (plus = w lewo)."""
        return self._shape(rc) * self.max_yaw_rate_dps

    def rc_to_vertical(self, rc: float) -> float:
        """Wychylenie ``rc`` (pion) -> prędkość pionowa [cm/s] (plus = w górę)."""
        return self._shape(rc) * self.max_vertical_cm_s

    def speed_to_rc(self, speed_cm_s: float) -> int:
        """Prędkość [cm/s] -> wychylenie RC (zaokrąglone)."""
        if self.max_speed_cm_s <= 0:
            raise ValueError("max_speed_cm_s musi być dodatnie")
        ratio = max(-1.0, min(1.0, speed_cm_s / self.max_speed_cm_s))
        if self.response_exponent != 1.0:
            ratio = math.copysign(abs(ratio) ** (1.0 / self.response_exponent), ratio)
        return int(round(ratio * 100))

    def yaw_rate_to_rc(self, yaw_rate_dps: float) -> int:
        """Prędkość obrotu [°/s] -> wychylenie RC."""
        if self.max_yaw_rate_dps <= 0:
            raise ValueError("max_yaw_rate_dps musi być dodatnie")
        ratio = max(-1.0, min(1.0, yaw_rate_dps / self.max_yaw_rate_dps))
        return int(round(ratio * 100))

    # ------------------------------------------------------------------- JSON
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        """Zapisz profil do pliku JSON."""
        return save_profile(self, path)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationProfile":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        fields = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        profile = cls(**fields)
        if extra:
            profile = replace(profile, extra=extra)
        return profile

    def with_measurements(self, label: str, distance_cm: float,
                          duration_s: float) -> "CalibrationProfile":
        """Zwróć profil przeliczony na podstawie pomiaru taśmą.

        :param label: ``forward`` (dystans cm), ``yaw`` (kąt °), ``up`` (cm)
        :param distance_cm: zmierzona wartość przy ``rc=100``
        :param duration_s: czas trwania pomiaru
        """
        if duration_s <= 0:
            raise ValueError("duration_s musi być > 0")
        measured = distance_cm / duration_s
        if label == "forward":
            return replace(self, max_speed_cm_s=round(measured, 2),
                           notes=f"kalibracja: {distance_cm} cm w {duration_s} s")
        if label == "yaw":
            return replace(self, max_yaw_rate_dps=round(measured, 2),
                           notes=f"kalibracja: {distance_cm}° w {duration_s} s")
        if label == "up":
            return replace(self, max_vertical_cm_s=round(measured, 2),
                           notes=f"kalibracja: {distance_cm} cm pion w {duration_s} s")
        raise ValueError("label musi być jednym z: forward, yaw, up")


#: Profil domyślny: DJI Tello (100% drążka = 50 cm/s poziomo, 90 °/s obrotu).
TELLO_PROFILE = CalibrationProfile(name="tello-default")


def load_profile(path: str | Path) -> CalibrationProfile:
    """Wczytaj profil z JSON (brakujące pola uzupełnia profil domyślny)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Profil kalibracji musi być obiektem JSON: {path}")
    return CalibrationProfile.from_dict(data)


def save_profile(profile: CalibrationProfile, path: str | Path) -> Path:
    """Zapisz profil do JSON (UTF-8, wcięcia)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = profile.to_dict()
    payload["format"] = "dronemoves-calibration"
    payload["version"] = 1
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def default_profile_path() -> Optional[Path]:
    """Opcjonalna ścieżka profilu użytkownika (``~/.dronemoves/profile.json``)."""
    candidate = Path.home() / ".dronemoves" / "profile.json"
    return candidate if candidate.exists() else None

