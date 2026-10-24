"""Adapter DJI Tello - tłumaczy API ``djitellopy`` na operacje silnika.

Mock ``djitellopy`` (katalog :mod:`app.adapters.tello.djitellopy`) jest
podstawiony na ``sys.path`` sandboxu, więc skrypt użytkownika wykonuje te same
wywołania co na prawdziwym dronie, ale trafiają one tutaj.

Rodzaje wyjątków (jak w djitellopy / SDK 2.0):
  * ``TelloException`` - komenda odrzucona przez drona (błąd stanu lub
    przekroczenie zakresu). Zapisujemy zdarzenie jako błąd i rzucamy dalej.
  * ``ValueError`` - błędy walidacji parametrów w djitellopy (zły kierunek
    ``flip``, ``go_xyz_speed`` z odległością > 500 cm).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from ...paths import ADAPTERS_DIR
from ...sim import core
from ...sim import realism
from ...sim.core import CommandError, Event, Simulation
from ..base import DroneAdapter, register_adapter
from .limits import LIMITS


class LimitError(CommandError):
    """Parametr komendy poza dozwolonym zakresem Tello."""


def _as_int(value: Any, name: str) -> int:
    """Zamień wartość na int (djitellopy akceptuje int/float/str)."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError(f"Nieprawidłowa wartość parametru {name}: {value!r} (oczekiwano liczby).")


def _range(value: int, low: int, high: int, name: str, unit: str,
           line: Optional[int] = None) -> None:
    if not (low <= value <= high):
        raise LimitError(
            f"Parametr '{name}' = {value}{unit} jest poza zakresem Tello "
            f"({low}-{high}{unit}).", line=line, kind="range")


class TelloController:
    """Obiekt przekazywany mockowi Tello - wykonuje operacje w silniku.

    Jedna instancja na skrypt (mock ``Tello`` tworzy ją w ``__init__``).
    """

    #: obrazy stanu dla właściwości mocka (do testów i odczytów)
    def __init__(self, sim: Simulation) -> None:
        self.sim = sim
        self.connected = False
        self.streaming = False
        self.rc: Dict[str, int] = {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}
        #: profil ruchu RC przesłany przez bibliotekę dronemoves (cm/s, °/s) albo None
        self._dronemoves_rc: Optional[Tuple[float, float, float, float, bool]] = None
        self._dronemoves_rc_thread: Optional[int] = None
        #: kurs nosa z planu biblioteki (°, konwencja symulatora) albo None
        self._dronemoves_yaw: Optional[float] = None
        self.speed = LIMITS.default_speed
        #: czy wykrywanie mat (Mission Pad) jest włączone (``enable_mission_pads``)
        self.mission_pads = False
        #: kierunek wykrywania mat: 0 = dół, 1 = przód, 2 = oba (SDK 2.0)
        self.mission_pad_direction = 0
        #: kolejka opóźnionych wychyleń RC (tryb realistyczny): (czas, rc)
        self._rc_queue: list = []

    # ---------------------------------------------------------- pomocnicze
    def _event(self, command: str, args: Sequence[Any]) -> Event:
        event, _file, _line = self.sim.begin(command, args)
        return event

    @staticmethod
    def _fail(event: Event, exc: BaseException, sim: Simulation) -> None:
        """Zapisz nieudaną komendę jako zdarzenie i dodaj komunikat błędu."""
        event.status = "error"
        event.message = str(exc)
        sim.commit(event)
        sim.recorder.add_error(str(exc), line=event.line, file=event.file,
                               type_=type(exc).__name__)

    def _unsupported(self, command: str, args: Sequence[Any]) -> None:
        event = self._event(command, args)
        sim = self.sim
        sim.warn(f"Komenda '{command}' nie jest obsługiwana w symulacji - pominięto.",
                 event=event)
        sim.commit(event)

    # ------------------------------------------------------------ połączenie
    def connect(self) -> None:
        event = self._event("connect", [])
        self.connected = True
        self.sim.commit(event)

    def end(self) -> None:
        event = self._event("end", [])
        self.connected = False
        self.streaming = False
        self.sim.commit(event)

    def streamon(self) -> None:
        event = self._event("streamon", [])
        self.streaming = True
        self.sim.commit(event)

    def streamoff(self) -> None:
        event = self._event("streamoff", [])
        self.streaming = False
        self.sim.commit(event)

    def set_speed(self, speed: Any) -> None:
        speed = _as_int(speed, "speed")
        event = self._event("set_speed", [speed])
        try:
            _range(speed, LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
        except CommandError as exc:
            self._fail(event, exc, self.sim)
            raise core.SimulationError(str(exc)) from None
        self.speed = speed
        self.sim.speed = speed
        self.sim.commit(event)

    # ---------------------------------------------------------------- start
    def takeoff(self) -> None:
        event = self._event("takeoff", [])
        try:
            self.sim.takeoff(event)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            raise

    def land(self) -> None:
        event = self._event("land", [])
        try:
            self.sim.land(event)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            raise
        self.rc_stop()

    def emergency(self) -> None:
        event = self._event("emergency", [])
        self.sim.emergency(event)
        self.rc_stop()

    # ----------------------------------------------------------------- ruch
    def move(self, command: str, direction: str, distance: Any) -> None:
        """Ruch liniowy w układzie drona: forward/back/left/right/up/down."""
        distance = _as_int(distance, "x")
        event = self._event(command, [distance])
        try:
            _range(distance, LIMITS.move_min_cm, LIMITS.move_max_cm, "x", " cm", event.line)
            self.sim.require_airborne(command)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            raise core.SimulationError(str(exc)) from None
        vectors = {
            "forward": (distance, 0.0, 0.0),
            "back": (-distance, 0.0, 0.0),
            "left": (0.0, distance, 0.0),
            "right": (0.0, -distance, 0.0),
            "up": (0.0, 0.0, distance),
            "down": (0.0, 0.0, -distance),
        }
        # tryb realistyczny: dron pokonuje 1 ± move_error odległości (tryb
        # idealny: mnożnik 1.0, więc wynik jest identyczny jak dotąd)
        scale = self._move_scale()
        dx, dy, dz = (value * scale for value in vectors[direction])
        speed = LIMITS.vertical_speed_cm_s if direction in ("up", "down") else self.speed
        self.sim.move_relative(command, [distance], dx, dy, dz, speed, event)

    def rotate(self, command: str, direction: str, degrees: Any) -> None:
        degrees = _as_int(degrees, "x")
        event = self._event(command, [degrees])
        try:
            _range(degrees, LIMITS.rotate_min_deg, LIMITS.rotate_max_deg, "x", " deg", event.line)
            self.sim.require_airborne(command)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            raise core.SimulationError(str(exc)) from None
        delta = degrees if direction == "ccw" else -degrees
        self.sim.rotation(command, [degrees], delta, event)

    def go_xyz_speed(self, x: Any, y: Any, z: Any, speed: Any) -> None:
        command = "go_xyz_speed"
        x, y, z, speed = (_as_int(x, "x"), _as_int(y, "y"), _as_int(z, "z"),
                          _as_int(speed, "speed"))
        event = self._event(command, [x, y, z, speed])
        try:
            for name, value in (("x", x), ("y", y), ("z", z)):
                if abs(value) > LIMITS.move_max_cm:
                    raise ValueError(f"Parametr '{name}' = {value} cm przekracza limit "
                                     f"{LIMITS.move_max_cm} cm (djitellopy rzuca ValueError).")
            _range(speed, LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
            self.sim.require_airborne(command)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        self.sim.move_relative(command, [x, y, z, speed], x, y, z, speed, event)

    def curve_xyz_speed(self, x1: Any, y1: Any, z1: Any, x2: Any, y2: Any, z2: Any,
                        speed: Any) -> None:
        command = "curve_xyz_speed"
        vals = [_as_int(v, n) for v, n in ((x1, "x1"), (y1, "y1"), (z1, "z1"),
                                           (x2, "x2"), (y2, "y2"), (z2, "z2"), (speed, "speed"))]
        event = self._event(command, vals)
        try:
            for name, value in zip(("x1", "y1", "z1", "x2", "y2", "z2"), vals[:6]):
                if abs(value) > LIMITS.move_max_cm:
                    raise ValueError(f"Parametr '{name}' = {value} cm przekracza limit "
                                     f"{LIMITS.move_max_cm} cm (djitellopy rzuca ValueError).")
            _range(vals[6], LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
            self.sim.require_airborne(command)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        self.sim.move_relative(command, vals, vals[3], vals[4], vals[5], vals[6], event,
                               curve_control=(vals[0], vals[1], vals[2]))

    def flip(self, direction: Any) -> None:
        direction = str(direction).lower().strip()
        event = self._event("flip", [direction])
        aliases = {"left": "l", "right": "r", "forward": "f", "front": "f",
                   "back": "b", "backward": "b"}
        try:
            direction = aliases.get(direction, direction)
            if direction not in LIMITS.flip_directions:
                raise ValueError(f"Nieprawidłowy kierunek flip: {direction!r} "
                                 f"(dozwolone: l, r, f, b).")
            self.sim.require_airborne("flip")
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        # założenie: flip trwa 1 s, dron wraca do tej samej pozycji i yaw
        self.sim.advance(1.0)
        self.sim.commit(event)

    # -------------------------------------------------------------------- RC
    def send_rc_control(self, lr: Any, fb: Any, ud: Any, yaw: Any) -> None:
        """Zapamiętaj wejścia RC (ruch wykonuje się podczas ``time.sleep``).

        Znaki jak w djitellopy (``rc a b c d``): ``lr`` dodatnie = **w prawo**,
        ``yaw`` dodatni = obrót **w prawo** (zgodnie z zegarem).
        """
        vals = [_as_int(v, n) for v, n in ((lr, "lr"), (fb, "fb"), (ud, "ud"), (yaw, "yaw"))]
        for name, value in zip(("lr", "fb", "ud", "yaw"), vals):
            _range(value, -LIMITS.rc_range, LIMITS.rc_range, name, "", None)
        if self.sim.realism.enabled and self.sim.realism.rc_delay_s > 0:
            # tryb realistyczny: dron reaguje na RC ze zwłoką - nowe wychylenia
            # wchodzą w życie po ``rc_delay_s``; wcześniej leci jeszcze starymi
            self._rc_queue.append((self.sim.now + self.sim.realism.rc_delay_s,
                                   dict(zip(("lr", "fb", "ud", "yaw"), vals))))
        else:
            self.rc = {"lr": vals[0], "fb": vals[1], "ud": vals[2], "yaw": vals[3]}
        self._dronemoves_rc = None      # nowa komenda RC = koniec trybu biblioteki

    def annotate(self, label: str) -> None:
        """Zaznacz początek/koniec manewru (biblioteka dronemoves) - nie steruje dronem."""
        event = self._event("annotate", [str(label)])
        self.sim.commit(event)

    def rc_active(self) -> bool:
        return any(self.rc.values())

    def set_dronemoves_profile(self, vx: float, vy: float, v_up: float,
                               yaw_rate: float, world: bool = False,
                               yaw: Optional[float] = None) -> None:
        """Zapisz profil ruchu przesłany przez bibliotekę ``dronemoves``.

        Biblioteka wysyła RC zgodnie ze swoim profilem kalibracji i pełną
        trajektorią; przekazanie tych prędkości wprost pozwala symulatorowi
        wykonać ruch 1:1 (bez drugiego przeliczenia wychyleń RC).

        :param vx: przód (``world=True``: globalna X)
        :param vy: lewo (``world=True``: globalna Y)
        :param v_up: pion (cm/s)
        :param yaw_rate: obrót (°/s, dodatni = w lewo - konwencja biblioteki)
        :param world: prędkości poziome w układzie globalnym (tak liczy planer)
        :param yaw: kurs nosa z planu (°, konwencja biblioteki: 0 = +X)
        """
        self._dronemoves_rc = (float(vx), float(vy), float(v_up), float(yaw_rate), bool(world))
        self._dronemoves_yaw = None if yaw is None else float(yaw) % 360.0
        # Ruch z profilu wykonuje tylko wątek, który go ustawił (pętla sterująca
        # biblioteki). Inne wątki (np. nadzór baterii śpiący w ``time.sleep``)
        # tylko przesuwają zegar - inaczej każdy ``sleep`` w dowolnym wątku
        # powtarzał ruch i dron „odjeżdżał” zamiast wracać do domu (KI-5).
        self._dronemoves_rc_thread = threading.get_ident()

    def rc_tick(self, seconds: float) -> None:
        """Upływ ``seconds`` czasu symulacji: ruch RC, jeśli aktywne wejścia RC.

        Wywoływane przez ``time.sleep`` w sandboxie (tak działają przykłady
        djitellopy: ``send_rc_control`` + ``time.sleep``). Ruch jest całkowany
        krokami <= 50 ms w układzie drona obracanym w trakcie.

        W trybie realistycznym nowe wychylenia RC wchodzą w życie po
        ``rc_delay_s`` - do tego czasu dron leci jeszcze poprzednimi.
        """
        self._apply_rc_delay()
        sim = self.sim
        profile = self._dronemoves_rc
        if profile is not None and self._dronemoves_rc_thread != threading.get_ident():
            # ``time.sleep`` z innego wątku (np. nadzór baterii) nie odtwarza
            # ruchu ustawionego przez pętlę sterującą - tylko biegnie zegar.
            sim.advance(seconds)
            return
        if profile is not None:
            if sim.airborne:
                vx, vy, v_up, yaw_rate, world = profile
                event, _f, _l = sim.begin("send_rc_control", [
                    round(vx, 1), round(vy, 1), round(v_up, 1), round(yaw_rate, 1),
                    round(seconds, 3),
                ])
                sim.rc_profile_motion(event, vx, vy, v_up, yaw_rate, seconds, world=world,
                                      yaw=self._dronemoves_yaw)
            else:
                sim.advance(seconds)
            return
        if self.rc_active():
            if sim.airborne:
                event, _f, _l = sim.begin("send_rc_control", [self.rc["lr"], self.rc["fb"],
                                                             self.rc["ud"], self.rc["yaw"],
                                                             round(seconds, 3)])
                sim.rc_motion(event, self.rc["lr"], self.rc["fb"], self.rc["ud"],
                              self.rc["yaw"], seconds)
                return
            sim.warn("Polecenia RC zignorowane - dron nie jest w powietrzu.", command="send_rc_control")
        sim.advance(seconds)

    def _apply_rc_delay(self) -> None:
        """Tryb realistyczny: włącz wychylenia RC, których opóźnienie już minęło."""
        if not self._rc_queue:
            return
        now = self.sim.now
        due = [item for item in self._rc_queue if item[0] <= now]
        if not due:
            return
        self._rc_queue = [item for item in self._rc_queue if item[0] > now]
        self.rc = due[-1][1]

    def rc_stop(self) -> None:
        """Zatrzymaj ruch RC (wywoływane na land/emergency)."""
        self.rc = {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}
        self._rc_queue = []
        self._dronemoves_rc = None
        self._dronemoves_rc_thread = None

    # --------------------------------------------------------------- mission pady
    def _pads(self):
        """Maty ze sceny w symulacji (pusta lista, gdy brak sceny)."""
        from ...features.obstacles import mission_pads

        return mission_pads.scene_pads(self.sim.settings.scene)

    def _visible_pad(self) -> Optional[Dict[str, Any]]:
        """Mata widziana w bieżącym położeniu (albo ``None``)."""
        from ...features.obstacles import mission_pads

        if not self.mission_pads or not self.sim.airborne:
            return None
        return mission_pads.visible_pad(self.sim.position, self._pads(),
                                        self.mission_pad_direction)

    def enable_mission_pads(self) -> None:
        event = self._event("enable_mission_pads", [])
        self.mission_pads = True
        self.sim.commit(event)

    def disable_mission_pads(self) -> None:
        event = self._event("disable_mission_pads", [])
        self.mission_pads = False
        self.sim.commit(event)

    def set_mission_pad_direction(self, direction: Any) -> None:
        """Kierunek wykrywania mat (0 = dół, 1 = przód, 2 = oba)."""
        direction = _as_int(direction, "x")
        event = self._event("set_mission_pad_detection_direction", [direction])
        if direction not in (0, 1, 2):
            exc = ValueError(f"Kierunek wykrywania mat musi być 0, 1 lub 2 "
                             f"(jest {direction}).")
            self._fail(event, exc, self.sim)
            raise exc
        self.mission_pad_direction = direction
        self.sim.commit(event)

    def get_mission_pad_id(self) -> int:
        pad = self._visible_pad()
        return self._read("get_mission_pad_id", -1 if pad is None else int(pad["pad_id"]))

    def mission_pad_distance(self, axis: int) -> int:
        """Odległość od widzianej maty w układzie maty (``0`` = x, ``1`` = y, ``2`` = z).

        Gdy mata nie jest widziana, SDK zwraca ``0`` dla wszystkich osi
        (``get_mission_pad_id()`` daje wtedy ``-1``).
        """
        from ...features.obstacles import mission_pads

        name = ("get_mission_pad_distance_x", "get_mission_pad_distance_y",
                "get_mission_pad_distance_z")[axis]
        pad = self._visible_pad()
        if pad is None:
            return self._read(name, 0)
        offset = mission_pads.pad_offset(self.sim.position, -self.sim.yaw, pad)
        return self._read(name, int(round(offset[axis])))

    def _require_visible_pad(self, mid: int) -> Dict[str, Any]:
        """Mata ``mid`` musi być widziana - inaczej błąd jak na prawdziwym Tello."""
        from ...features.obstacles import mission_pads

        if not self.mission_pads:
            raise mission_pads.PadError(
                "Wykrywanie mat nie jest włączone - najpierw enable_mission_pads().")
        pad = mission_pads.find_pad(self._pads(), mid)
        if pad is None:
            raise mission_pads.PadError(f"W scenie nie ma maty o numerze m{mid}.")
        visible = self._visible_pad()
        if visible is None or int(visible.get("pad_id") or 0) != int(mid):
            seen = -1 if visible is None else int(visible.get("pad_id") or -1)
            raise mission_pads.PadError(
                f"Mata m{mid} nie jest widziana (widziana: {seen}) - "
                "dron musi być nad matą w zasięgu kamery.")
        return pad

    def go_xyz_speed_mid(self, x: Any, y: Any, z: Any, speed: Any, mid: Any) -> None:
        """Lot do punktu w układzie maty ``mid`` (``go x y z speed mID``)."""
        from ...features.obstacles import mission_pads

        command = "go_xyz_speed_mid"
        mid = _as_int(mid, "mid")
        x, y, z, speed = (_as_int(x, "x"), _as_int(y, "y"), _as_int(z, "z"),
                          _as_int(speed, "speed"))
        event = self._event(command, [x, y, z, speed, mid])
        try:
            for name, value in (("x", x), ("y", y), ("z", z)):
                if abs(value) > LIMITS.move_max_cm:
                    raise ValueError(f"Parametr '{name}' = {value} cm przekracza limit "
                                     f"{LIMITS.move_max_cm} cm (djitellopy rzuca ValueError).")
            _range(speed, LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
            if mid not in mission_pads.PAD_IDS:
                raise mission_pads.PadError(f"Numer maty musi być 1-8 (jest {mid}).")
            self.sim.require_airborne(command)
            pad = self._require_visible_pad(mid)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        self._fly_to_pad_point(command, pad, (x, y, z), speed, event,
                              [x, y, z, speed, mid])

    def _fly_to_pad_point(self, command: str, pad: Dict[str, Any], point: Sequence[float],
                          speed: int, event: Event, args: Sequence[Any]) -> None:
        """Przelot do ``point`` w układzie maty ``pad`` (wspólne dla ``*_mid``)."""
        from ...features.obstacles import mission_pads

        target = mission_pads.pad_target_world(pad, point)
        dx = target[0] - self.sim.position[0]
        dy = target[1] - self.sim.position[1]
        dz = target[2] - self.sim.position[2]
        self.sim.move_relative(command, args, dx, dy, dz, speed, event)

    def curve_xyz_speed_mid(self, x1: Any, y1: Any, z1: Any, x2: Any, y2: Any,
                            z2: Any, speed: Any, mid: Any) -> None:
        """Lot łukiem do ``(x2, y2, z2)`` w układzie maty ``mid`` (przez punkt 1)."""
        from ...features.obstacles import mission_pads

        command = "curve_xyz_speed_mid"
        mid = _as_int(mid, "mid")
        vals = [_as_int(v, n) for v, n in ((x1, "x1"), (y1, "y1"), (z1, "z1"),
                                           (x2, "x2"), (y2, "y2"), (z2, "z2"),
                                           (speed, "speed"))]
        event = self._event(command, vals + [mid])
        try:
            for name, value in zip(("x1", "y1", "z1", "x2", "y2", "z2"), vals[:6]):
                if abs(value) > LIMITS.move_max_cm:
                    raise ValueError(f"Parametr '{name}' = {value} cm przekracza limit "
                                     f"{LIMITS.move_max_cm} cm (djitellopy rzuca ValueError).")
            _range(vals[6], LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
            if mid not in mission_pads.PAD_IDS:
                raise mission_pads.PadError(f"Numer maty musi być 1-8 (jest {mid}).")
            self.sim.require_airborne(command)
            pad = self._require_visible_pad(mid)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        self._fly_to_pad_point(command, pad, vals[3:6], vals[6], event, vals + [mid])

    def go_xyz_speed_yaw_mid(self, x: Any, y: Any, z: Any, speed: Any, yaw: Any,
                             mid1: Any, mid2: Any) -> None:
        """Przelot nad ``mid2`` i obrót do kursu ``yaw`` względem ``mid2``.

        Model (``jump x y z speed yaw m1 m2`` z SDK 2.0): dron leci do
        ``(x, y, z)`` w układzie ``mid1``, potem nad ``mid2`` na wysokości ``z``
        i obraca się. Symulator wykonuje **drugi etap** jako ruch - telemetria
        pokazuje przelot do punktu nad ``mid2``; obrót jest tylko sprawdzany
        (wynikowy kurs nie jest zmieniany, bo ruch i obrót to w silniku osobne
        operacje).
        """
        from ...features.obstacles import mission_pads

        command = "go_xyz_speed_yaw_mid"
        mid1, mid2 = _as_int(mid1, "mid1"), _as_int(mid2, "mid2")
        x, y, z, speed = (_as_int(x, "x"), _as_int(y, "y"), _as_int(z, "z"),
                          _as_int(speed, "speed"))
        yaw = _as_int(yaw, "yaw")
        event = self._event(command, [x, y, z, speed, yaw, mid1, mid2])
        try:
            for name, value in (("x", x), ("y", y), ("z", z)):
                if abs(value) > LIMITS.move_max_cm:
                    raise ValueError(f"Parametr '{name}' = {value} cm przekracza limit "
                                     f"{LIMITS.move_max_cm} cm (djitellopy rzuca ValueError).")
            _range(speed, LIMITS.speed_min, LIMITS.speed_max, "speed", " cm/s", event.line)
            _range(yaw, -360, 360, "yaw", " deg", event.line)
            for name, mid in (("mid1", mid1), ("mid2", mid2)):
                if mid not in mission_pads.PAD_IDS:
                    raise mission_pads.PadError(f"Numer maty ({name}) musi być 1-8 "
                                                f"(jest {mid}).")
            self.sim.require_airborne(command)
            self._require_visible_pad(mid1)
            pad2 = self._require_visible_pad(mid2)
        except core.SimulationError as exc:
            self._fail(event, exc, self.sim)
            if isinstance(exc, ValueError):
                raise
            raise core.SimulationError(str(exc)) from None
        self._fly_to_pad_point(command, pad2, (0, 0, z), speed, event,
                               [x, y, z, speed, yaw, mid1, mid2])

    # ---------------------------------------------------------------- odczyt
    def _read(self, command: str, value: Any) -> Any:
        event = self._event(command, [])
        self.sim.commit(event)
        return value

    def _move_scale(self) -> float:
        """Mnożnik odległości ``move_*`` (tryb realistyczny: 1 ± ``move_error``)."""
        if not self.sim.realism.enabled:
            return 1.0
        return realism.move_scale(self.sim.realism, self.sim._rng)

    def _noisy(self, value: float, sigma: float) -> float:
        """Odczyt z szumem w trybie realistycznym (tryb idealny: bez zmian)."""
        if not self.sim.realism.enabled or sigma <= 0:
            return value
        return realism.noisy(value, sigma, self.sim._rng)

    def get_battery(self) -> int:
        return self._read("get_battery", int(round(self.sim.battery)))

    def get_height(self) -> int:
        return self._read("get_height", int(round(self._noisy(
            self.sim.position[2], self.sim.realism.height_noise_cm))))

    def get_distance_tof(self) -> int:
        return self._read("get_distance_tof", int(round(self._noisy(
            self.sim.position[2], self.sim.realism.height_noise_cm))))

    def get_speed_x(self) -> int:
        return self._read("get_speed_x", int(round(self.sim.velocity[0])))

    def get_speed_y(self) -> int:
        return self._read("get_speed_y", int(round(self.sim.velocity[1])))

    def get_speed_z(self) -> int:
        return self._read("get_speed_z", int(round(self.sim.velocity[2])))

    def get_yaw(self) -> int:
        """Kurs w konwencji ``djitellopy.get_yaw()``: dodatni = obrót w prawo (CW).

        Wewnętrzny kurs silnika (``sim.yaw``) jest matematyczny - dodatni = w lewo
        (CCW) - bo tak liczą ruch ``physics`` i planer. Tutaj, na granicy API,
        zamieniamy znak na konwencję Tello.
        """
        yaw = (-self.sim.yaw) % 360.0
        yaw = self._noisy(yaw, self.sim.realism.yaw_noise_deg) % 360.0
        return self._read("get_yaw", int(round(yaw - 360 if yaw > 180 else yaw)))

    def get_flight_time(self) -> int:
        return self._read("get_flight_time", int(round(self.sim.flight_time)))

    def get_temperature(self) -> int:
        return self._read("get_temperature", int(round(self.sim_temperature())))

    def get_highest_temperature(self) -> int:
        """Najwyższa temperatura (``temph``) - z ustawień symulatora."""
        return self._read("get_highest_temperature", int(round(self.sim_temperature())))

    def get_lowest_temperature(self) -> int:
        return self._read("get_lowest_temperature",
                          max(int(round(self.sim_temperature())) - 4, 0))

    def query_wifi_signal_noise_ratio(self) -> int:
        """SNR Wi-Fi [dB] - z ustawień symulatora (do testów preflight)."""
        return self._read("query_wifi_signal_noise_ratio",
                          int(self.sim.settings.wifi_snr_db))

    def query_sdk_version(self) -> str:
        return self._read("query_sdk_version", "30")

    def sim_temperature(self) -> float:
        """Temperatura ustawiona w symulatorze [°C]."""
        return float(self.sim.settings.start_temperature_c)

    def get_frame_read(self) -> "FrameReader":
        self._read("get_frame_read", None)
        return FrameReader()

    def query(self, command: str) -> str:
        """Odczyt stanu (np. ``query_battery``) - w symulacji brak danych."""
        self._unsupported(command, [])
        return ""

    def query_speed(self) -> int:
        return self._read("query_speed", self.speed)

    def unknown(self, command: str, args: Sequence[Any]) -> None:
        self._unsupported(command, args)


class FrameReader:
    """Minimalny odpowiednik ``Tello.get_frame_read()`` (pusta klatka)."""

    class _Frame:
        def __init__(self) -> None:
            self.frame = None

    def __init__(self) -> None:
        self.frame = self._Frame()

    def stop(self) -> None:
        return None


@register_adapter
class TelloAdapter(DroneAdapter):
    """Adapter DJI Tello (biblioteka djitellopy, podstawiona mock)."""

    id = "tello"
    name = "DJI Tello (djitellopy)"
    description = ("Symulacja DJI Tello sterowanego biblioteką djitellopy. "
                   "Mock biblioteki jest wstrzykiwany do sandboxu.")
    module_names = ("djitellopy",)

    def limits(self) -> Dict[str, Any]:
        return LIMITS.as_dict()

    def mock_root(self) -> Path:
        return ADAPTERS_DIR / "tello"

    def runtime_hooks(self) -> Sequence[str]:
        return ("app.adapters.tello.runtime",)

    #: funkcja zwracająca aktywny kontroler RC (dla ``time.sleep``)
    rc_provider = "app.adapters.tello.runtime:controller"

    def settings(self) -> Dict[str, Any]:
        """Parametry silnika wynikające z modelu Tello."""
        return {
            "takeoff_height": float(LIMITS.takeoff_height_cm),
            "land_height": 0.0,
            "vertical_speed": float(LIMITS.vertical_speed_cm_s),
            "battery_drain_flight": LIMITS.battery_drain_flight_pct_per_s,
            "battery_drain_idle": LIMITS.battery_drain_idle_pct_per_s,
            "default_speed": LIMITS.default_speed,
            "max_height_cm": float(LIMITS.max_height_cm),
        }
