"""Testy ``Pilot.path`` - dronemoves 0.1.5.

Oczekiwane wartości liczone z geometrii (patrz komentarze), nie z wyniku
programu. Problem „path nie realizuje kursu startowego” to KNOWN_ISSUES.md KI-1
(test oznaczony ``xfail``).
"""

from __future__ import annotations

import math

import pytest

from dronemoves.calibration import TELLO_PROFILE
from dronemoves.pilot import Pilot
from dronemoves.planner import PlanLimits


class FakeDrone:
    """Minimalny dron do planowania (bez lotu): tylko wymagane odczyty."""

    def __init__(self) -> None:
        self.rc: list = []

    def send_rc_control(self, lr, fb, ud, yaw) -> None:  # noqa: D401 - atrapa
        self.rc.append((lr, fb, ud, yaw))

    def get_battery(self) -> int:
        return 90

    def get_height(self) -> int:
        return 0

    def get_distance_tof(self) -> int:
        return 0

    def get_yaw(self) -> int:
        return 0

    def get_pitch(self) -> int:
        return 0

    def get_roll(self) -> int:
        return 0

    def get_speed_x(self) -> int:
        return 0

    def get_speed_y(self) -> int:
        return 0

    def get_speed_z(self) -> int:
        return 0


def plan(points):
    """Zaplanuj ``path`` tak, jak robi to ``Pilot.path``/``ManeuverCollection.path``."""
    pilot = Pilot(FakeDrone(), speed=40)
    maneuver = pilot.maneuvers().path(points)
    return maneuver.planner(limits=PlanLimits(), profile=TELLO_PROFILE, speed=40)


def test_path_startuje_w_miejscu_drona_i_wznosi_sie_do_punktu() -> None:
    """Start planu to (0, 0, 0), a koniec - podany punkt względny.

    Dron po ``takeoff`` jest już na wysokości startowej (względne z = 0), więc
    ``z = 20`` w punkcie oznacza 20 cm wyżej - plan musi zaczynać się na z = 0,
    inaczej nie ma z czego się wznosić (błąd 0.1.4: start_z = z pierwszego punktu).
    """
    traj = plan([(120, 0, 20), (120, 150, 20)])
    first, last = traj.samples[0], traj.samples[-1]
    assert (round(first.x, 6), round(first.y, 6), round(first.z, 6)) == (0.0, 0.0, 0.0)
    assert math.dist((last.x, last.y, last.z), (120, 150, 20)) <= 1.0
    # plan naprawdę się wznosi: maksimum z osiąga 20 cm (a nie 0)
    assert max(s.z for s in traj.samples) == pytest.approx(20.0, abs=0.5)


def test_path_z_jednym_punktem_jest_dozwolony() -> None:
    """Jeden punkt: start (0,0,0) + punkt docelowy = 2 punkty planu."""
    traj = plan([(100, 0, 50)])
    last = traj.samples[-1]
    assert math.dist((last.x, last.y, last.z), (100, 0, 50)) <= 1.0
    assert traj.samples[0].z == pytest.approx(0.0, abs=1e-9)


def test_path_bez_doklejania_gdy_start_jest_w_poczatku() -> None:
    """Trasa zaczynająca się w (0,0,0) ma ten sam tor, co bez punktu startu.

    ``[(0,0,0), (80,0,0)]`` i ``[(80,0,0)]`` opisują ten sam odcinek 80 cm
    w +X; doklejanie drugiego punktu (0,0,0) dawałoby odcinek zerowy i zniekształcony
    spline. Sprawdzamy koniec toru i brak cofnięcia (min x >= 0).
    """
    with_start = plan([(0, 0, 0), (80, 0, 0)])
    without_start = plan([(80, 0, 0)])
    for traj in (with_start, without_start):
        assert math.dist((traj.samples[-1].x, traj.samples[-1].y), (80, 0)) <= 1.0
        assert min(s.x for s in traj.samples) >= -1e-6


def test_path_zanegowane_punkty_planowane_symetrycznie() -> None:
    """Lustrzane trasy (y lub -y) mają lustrzany plan - geometria jest symetryczna."""
    right = plan([(0, -120, 0)])
    left = plan([(0, 120, 0)])
    assert math.dist((right.samples[-1].x, right.samples[-1].y), (0, -120)) <= 1.0
    assert math.dist((left.samples[-1].x, left.samples[-1].y), (0, 120)) <= 1.0


def test_path_w_planie_leci_w_strone_punktu() -> None:
    """Plan ``path`` zawiera obrót w miejscu do kursu odcinka (KI-1).

    Dla punktu w ``-Y`` (prawo od nosa) plan musi mieć na początku próbki
    z obrotem w miejscu (yaw zmienia się, pozycja stoi), a na końcu pozycję
    ``(0, -120)``. Wcześniej plan „przeskakiwał” kurs (yaw 0 od razu).
    """
    traj = plan([(0, -120, 0)])
    first = traj.samples[0]
    # obrót w miejscu: pierwsze próbki mają pozycję (0, 0) i zmieniający się yaw
    rotating = [s for s in traj.samples[:20] if abs(s.x) < 0.5 and abs(s.y) < 0.5]
    assert rotating, "brak odcinka obrotu w miejscu"
    assert abs(first.x) < 0.5 and abs(first.y) < 0.5
    turn = [s.yaw for s in rotating]
    assert max(turn) - min(turn) > 20, turn        # obrót naprawdę się odbywa
    last = traj.samples[-1]
    assert math.dist((last.x, last.y), (0, -120)) <= 2.0
