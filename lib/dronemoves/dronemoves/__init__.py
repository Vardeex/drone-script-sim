"""dronemoves - płynne manewry dla dronów sterowanych z Pythona.

Biblioteka działa na publicznym API biblioteki drona (np. ``djitellopy``
dla DJI Tello), więc ten sam skrypt działa w symulatorze (Drone Script
Simulator, podstawiony mock) i na prawdziwym dronie.

Przykład::

    from djitellopy import Tello
    from dronemoves import Pilot

    tello = Tello(); tello.connect(); tello.takeoff()
    with Pilot(tello, speed=40) as p:
        p.forward(100)
        p.circle(radius=100, direction="right")
"""

from __future__ import annotations

from .calibration import CalibrationProfile, TELLO_PROFILE, load_profile, save_profile
from .executor import Executor
from .pilot import Maneuver, ManeuverCollection, Pilot, ManeuverError, SafetyError
from .safety import (Check, Geofence, PreflightError, PreflightReport, preflight,
                     safe_start)
from .trajectory import Trajectory

__version__ = "0.2.2"

__all__ = [
    "CalibrationProfile", "TELLO_PROFILE", "load_profile", "save_profile",
    "Executor", "Maneuver", "ManeuverCollection", "Pilot", "ManeuverError", "SafetyError",
    "Check", "Geofence", "PreflightError", "PreflightReport", "preflight", "safe_start",
    "Trajectory", "__version__",
]
