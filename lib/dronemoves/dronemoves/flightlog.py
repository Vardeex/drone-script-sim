"""Rejestrator lotu **prawdziwego** Tello - dane do porównań i kalibracji.

Czym to jest (i czym nie jest)
------------------------------
``FlightRecorder`` **tylko czyta** stan drona publicznym API ``djitellopy``
(``get_height``, ``get_yaw``, ``get_speed_x/y/z``, ``get_battery``,
``get_flight_time``, ``get_acceleration_x/y/z``, ``get_distance_tof``,
``get_mission_pad_id`` jeśli włączone maty) i zapisuje wywołane komendy.
**Nie steruje dronem** - komendy wysyła Twój kod, rejestrator jest tylko
observatorem (opakowanie obiektu ``Tello``). Nie modyfikujemy ``djitellopy``.

Zapis jest w formacie lotu symulatora z dodatkową flagą ``"source": "real"``,
dzięki czemu plik da się wczytać w aplikacji i porównać z lotem symulowanym.

Pozycja jest **szacowana** z prędkości (Tello nie podaje pozycji):

* ``get_yaw()`` rośnie w prawo (CW+), a układ projektu ma ``y`` = lewo
  i kurs wewnętrzny CCW+ - dlatego ``psi = -yaw``,
* prędkości z Tello są w układzie drona (przód/lewo/góra),
* całkowanie: ``x += (vgx*cos psi - vgy*sin psi) * dt`` itd.

Błąd takiego szacowania rośnie w czasie (dryf), więc do porównań nadają się
krótkie loty (kilkadziesiąt sekund), a nie całe misje.
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: co ile sekund czytamy stan drona (Tello i tak odświeża stan ~10 Hz)
DEFAULT_INTERVAL_S = 0.1
#: wysokość, od której uznajemy drona za będącego w powietrzu [cm]
AIRBORNE_HEIGHT_CM = 10.0
#: wersja formatu pliku (zgodna z ``app.storage``)
FLIGHT_FORMAT = "drone-script-simulator"
FLIGHT_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe(getter: Callable[[], Any], default: Any = None) -> Any:
    """Odczyt z drona - brak wsparcia dla pola nie może przerwać rejestracji."""
    try:
        return getter()
    except Exception:                       # noqa: BLE001 - np. brak maty/zasięgu
        return default


class FlightRecorder:
    """Rejestruje lot prawdziwego Tello (tylko odczyt stanu + komendy).

    :param tello: obiekt ``djitellopy.Tello`` (albo zgodny zamiennik, np. w testach),
    :param interval_s: odstęp próbkowania (domyślnie 100 ms),
    :param mission_pads: ``True``, gdy maty Mission Pad są włączone (wtedy czytamy
        ``get_mission_pad_id``); ``None`` = wykryj automatycznie,
    :param name: nazwa w zapisie lotu.

    Użycie::

        recorder = FlightRecorder(tello)
        drone = recorder.proxy()             # komendy wysyła Twój kod
        with recorder:
            drone.connect()
            drone.takeoff()                  # komendy są zapisywane
            drone.move_forward(50)
            drone.land()
        recorder.save("lot_real.json")
    """

    def __init__(self, tello: Any, interval_s: float = DEFAULT_INTERVAL_S,
                 mission_pads: Optional[bool] = None, name: str = "lot_real") -> None:
        self.tello = tello
        self.interval_s = max(0.02, float(interval_s))
        self.name = name
        self._mission_pads = mission_pads
        self.samples: List[Dict[str, Any]] = []
        self.commands: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._t0 = 0.0
        self._position = [0.0, 0.0, 0.0]
        self._last_sample_t = 0.0
        self._state = "idle"

    # ------------------------------------------------------------- sterowanie
    def start(self) -> "FlightRecorder":
        """Rozpocznij próbkowanie w tle (idempotentnie)."""
        if self._thread is not None:
            return self
        self._t0 = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="flight-recorder",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> "FlightRecorder":
        """Zatrzymaj próbkowanie i dołącz ostatnią próbkę."""
        if self._thread is None:
            return self
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._thread = None
        self._sample()
        return self

    def __enter__(self) -> "FlightRecorder":
        return self.start()

    def __exit__(self, *exc_info: Any) -> None:
        self.stop()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._sample()

    def proxy(self) -> "RecordedTello":
        """Opakowanie drona, które zapisuje wywołane komendy (i je przekazuje)."""
        return RecordedTello(self)

    # ------------------------------------------------------------------ próbki
    def _read(self) -> Dict[str, Any]:
        """Odczyt jednego zestawu pól z drona (pola opcjonalne mogą być ``None``)."""
        tello = self.tello
        if self._mission_pads is None:
            self._mission_pads = hasattr(tello, "get_mission_pad_id")
        return {
            "height": _safe(tello.get_height),
            "yaw": _safe(tello.get_yaw),
            "speed_x": _safe(tello.get_speed_x),
            "speed_y": _safe(tello.get_speed_y),
            "speed_z": _safe(tello.get_speed_z),
            "battery": _safe(tello.get_battery),
            "flight_time": _safe(tello.get_flight_time),
            "acc_x": _safe(tello.get_acceleration_x),
            "acc_y": _safe(tello.get_acceleration_y),
            "acc_z": _safe(tello.get_acceleration_z),
            "tof": _safe(tello.get_distance_tof),
            "pad": (_safe(tello.get_mission_pad_id)
                    if self._mission_pads else None),
        }

    def _sample(self) -> Optional[Dict[str, Any]]:
        """Jedna próbka: przelicz prędkości na pozycję i zapisz."""
        raw = self._read()
        moment = time.monotonic() - self._t0
        dt = max(0.0, moment - self._last_sample_t)
        self._last_sample_t = moment
        height = float(raw["height"] or 0.0)
        yaw_right = float(raw["yaw"] or 0.0)          # Tello: + = w prawo
        psi = math.radians(-yaw_right)                # projekt: + = w lewo (CCW)
        vgx = float(raw["speed_x"] or 0.0)            # przód
        vgy = float(raw["speed_y"] or 0.0)            # lewo
        vgz = float(raw["speed_z"] or 0.0)            # góra
        vx = vgx * math.cos(psi) - vgy * math.sin(psi)
        vy = vgx * math.sin(psi) + vgy * math.cos(psi)
        with self._lock:
            self._position[0] += vx * dt
            self._position[1] += vy * dt
            self._position[2] = height
            if height > AIRBORNE_HEIGHT_CM:
                self._state = "airborne"
            elif self._state == "airborne":
                self._state = "landed"
            sample = {
                "t": round(moment, 3),
                "x": round(self._position[0], 2),
                "y": round(self._position[1], 2),
                "z": round(height, 2),
                "yaw": round(-yaw_right, 2),          # kurs wewnętrzny (CCW+)
                "vx": round(vx, 2), "vy": round(vy, 2), "vz": round(vgz, 2),
                "battery": float(raw["battery"]) if raw["battery"] is not None else 0.0,
                "state": self._state,
                # pola dodatkowe (tylko lot rzeczywisty) - diagnostyka i kalibracja
                "yaw_right": round(yaw_right, 2),
                "tof_cm": raw["tof"],
                "acc": [raw["acc_x"], raw["acc_y"], raw["acc_z"]],
                "flight_time_s": raw["flight_time"],
                "mission_pad": raw["pad"],
            }
            self.samples.append(sample)
        return sample

    # --------------------------------------------------------------- komendy
    def record_command(self, name: str, args: Any, result: Any = None,
                       error: Optional[str] = None) -> None:
        """Zapisz wywołanie komendy (czas liczony od ``start()``)."""
        with self._lock:
            moment = time.monotonic() - self._t0 if self._t0 else 0.0
            sample = self.samples[-1] if self.samples else {}
            self.commands.append({
                "t": round(moment, 3),
                "command": name,
                "args": list(args) if args else [],
                "result": result if isinstance(result, (int, float, str, bool)) else None,
                "error": error,
                "x": sample.get("x", 0.0), "y": sample.get("y", 0.0),
                "z": sample.get("z", 0.0), "yaw": sample.get("yaw", 0.0),
            })

    # ------------------------------------------------------------------- zapis
    def stats(self) -> Dict[str, Any]:
        """Statystyki w formacie jak w locie symulatora (te same klucze)."""
        with self._lock:
            samples = list(self.samples)
        duration = samples[-1]["t"] if samples else 0.0
        distance = 0.0
        for previous, current in zip(samples, samples[1:]):
            distance += math.dist((previous["x"], previous["y"], previous["z"]),
                                  (current["x"], current["y"], current["z"]))
        airborne = [s for s in samples if s["state"] == "airborne"]
        battery = [s["battery"] for s in samples if s["battery"]]
        final = samples[-1] if samples else {}
        return {
            "duration_s": round(duration, 2),
            "flight_time_s": round(airborne[-1]["t"] - airborne[0]["t"], 2)
            if airborne else 0.0,
            "distance_cm": round(distance, 1),
            "max_height_cm": round(max((s["z"] for s in samples), default=0.0), 1),
            "battery_used_pct": round(battery[0] - battery[-1], 1) if len(battery) > 1 else 0.0,
            "battery_left_pct": round(battery[-1], 1) if battery else 0.0,
            "final_position_cm": [final.get("x", 0.0), final.get("y", 0.0),
                                  final.get("z", 0.0)],
            "final_yaw_deg": final.get("yaw", 0.0),
            "samples": len(samples),
            "events": len(self.commands),
            "warnings": 0,
            "errors": sum(1 for command in self.commands if command["error"]),
        }

    def to_flight(self, flight_id: Optional[str] = None) -> Dict[str, Any]:
        """Lot w formacie symulatora z ``"source": "real"`` (gotowy do zapisu)."""
        with self._lock:
            samples = [dict(sample) for sample in self.samples]
            commands = [dict(command) for command in self.commands]
        flight_id = flight_id or f"real-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        events = []
        for index, command in enumerate(commands, start=1):
            events.append({
                "index": index, "t": command["t"], "t_end": command["t"],
                "duration": 0.0, "command": command["command"],
                "args": command["args"], "status": "error" if command["error"] else "ok",
                "warning": None, "message": command["error"],
                "line": None, "file": self.name,
                "x": command["x"], "y": command["y"], "z": command["z"],
                "yaw": command["yaw"], "battery": samples[-1]["battery"] if samples else 0.0,
            })
        return {
            "format": FLIGHT_FORMAT,
            "version": FLIGHT_VERSION,
            "source": "real",
            "id": flight_id,
            "created_at": _now_iso(),
            "script_name": self.name,
            "adapter": "tello-real",
            "status": "ok" if not any(e["status"] == "error" for e in events) else "error",
            "final_state": samples[-1]["state"] if samples else "idle",
            "duration": round(samples[-1]["t"], 3) if samples else 0.0,
            "real_seconds": round(samples[-1]["t"], 3) if samples else 0.0,
            "stats": self.stats(),
            "limits": {},
            "script_source": "",
            "samples": samples,
            "events": events,
            "segments": [],
            "warnings": [],
            "errors": [{"message": c["error"], "line": None, "command": c["command"]}
                       for c in commands if c["error"]],
            "stdout": [],
            "stderr": [],
            "recorder": {
                "interval_s": self.interval_s,
                "mission_pads": bool(self._mission_pads),
                "position_source": "estimated_from_speed",
                "note": "Pozycja szacowana z prędkości (Tello nie podaje pozycji).",
            },
        }

    def save(self, path: Any, flight_id: Optional[str] = None) -> Path:
        """Zapisz lot do pliku JSON (format symulatora, ``source: real``)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_flight(flight_id)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        return target


class RecordedTello:
    """Przezroczyste opakowanie drona: przekazuje wywołania i zapisuje je.

    Rejestrator **nie wysyła** komend sam - robi to wyłącznie kod użytkownika,
    a opakowanie tylko notuje, co zostało wywołane (z czasem i pozycją).
    """

    def __init__(self, recorder: FlightRecorder) -> None:
        object.__setattr__(self, "_recorder", recorder)

    def __getattr__(self, name: str) -> Any:
        recorder: FlightRecorder = object.__getattribute__(self, "_recorder")
        attribute = getattr(recorder.tello, name)
        if not callable(attribute):
            return attribute

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = attribute(*args, **kwargs)
            except Exception as exc:                    # noqa: BLE001 - zapisz i podnieś
                recorder.record_command(name, args, error=f"{type(exc).__name__}: {exc}")
                raise
            recorder.record_command(name, args, result=result)
            return result

        return wrapper
