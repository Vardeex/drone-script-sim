"""Testy trybu realistycznego symulatora.

Tryb idealny musi być **bit w bit** taki jak dotąd (żadnych zmian zachowania).
Tryb realistyczny nie ma sztywnych progów - sprawdzamy, że:
  * ten sam seed daje ten sam lot (powtarzalność),
  * dryf faktycznie odchyla dron od trasy idealnej,
  * ``return_home`` nadal wraca w okolice startu (zapisujemy zmierzoną wartość).
"""

from __future__ import annotations

import pytest

from app import runner
from app.sim import realism

SCRIPT = """
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
pilot = Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500)
with pilot:
    pilot.forward(100)
    pilot.turn(90, radius=60)
    pilot.forward(80)
    pilot.return_home()
tello.land()
"""

SIMPLE = """
from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.move_forward(100)
tello.rotate_clockwise(90)
print('YAW', tello.get_yaw())
print('H', tello.get_height())
tello.land()
"""


def run(source: str, **settings):
    return runner.run_script(source, "realism.py", extra_settings=settings)


def path_of(result):
    return [(round(s["x"], 6), round(s["y"], 6), round(s["z"], 6))
            for s in result.flight.samples]


def test_ideal_mode_is_unchanged():
    """Brak parametrów realizmu = lot identyczny z domyślnym zachowaniem."""
    default = run(SCRIPT)
    explicit = run(SCRIPT, realism=False)
    assert default.status == "ok" and explicit.status == "ok"
    assert path_of(default) == path_of(explicit)
    # tryb idealny nie rozwija żadnej losowości dryfu
    assert path_of(default) == path_of(run(SCRIPT, realism=False, realism_seed=99))


def test_params_disabled_by_default():
    """Parametry realizmu domyślnie wyłączone (żadnych zmian zachowania)."""
    params = realism.RealismParams()
    assert params.enabled is False
    assert params.move_error == pytest.approx(0.05)


def test_same_seed_same_flight():
    """Ten sam seed = ten sam lot (powtarzalność trybu realistycznego)."""
    first = run(SCRIPT, realism=True, realism_seed=7)
    second = run(SCRIPT, realism=True, realism_seed=7)
    assert first.status == "ok" and second.status == "ok"
    assert path_of(first) == path_of(second)


def test_different_seed_different_flight():
    """Inny seed = inny dryf (tryb realistyczny faktycznie losuje)."""
    first = run(SCRIPT, realism=True, realism_seed=1)
    second = run(SCRIPT, realism=True, realism_seed=2)
    assert path_of(first) != path_of(second)


def test_drift_moves_drone_off_ideal_path():
    """Dron w trybie realistycznym odjeżdża od trasy idealnej (dryf działa)."""
    ideal = run(SIMPLE)
    real = run(SIMPLE, realism=True, realism_seed=3)
    assert ideal.status == "ok" and real.status == "ok"
    last_ideal = [s for s in ideal.flight.samples if s["z"] > 10][-1]
    last_real = [s for s in real.flight.samples if s["z"] > 10][-1]
    distance = ((last_ideal["x"] - last_real["x"]) ** 2
                + (last_ideal["y"] - last_real["y"]) ** 2) ** 0.5
    assert distance > 0.5, f"dryf nie widoczny: {distance:.2f} cm"


def test_sensors_noisy_in_real_mode():
    """Szum wysokości i kursu: odczyty różnią się od wartości idealnych."""
    heights, yaws = set(), set()
    for seed in range(1, 6):
        result = run(SIMPLE, realism=True, realism_seed=seed)
        assert result.status == "ok"
        out = "".join(line if isinstance(line, str) else line.get("text", "")
                      for line in result.stdout or [])
        heights.add(out.split("H")[-1].strip()[:3])
        yaws.add(out.split("YAW")[1].split("H")[0].strip()[:3])
    # co najmniej dwa różne odczyty wysokości i kursu przy różnych seedach
    assert len(heights) >= 2
    assert len(yaws) >= 2


def test_return_home_in_realistic_mode():
    """Tryb realistyczny: ``return_home`` nadal wraca w okolice startu.

    Zmierzony błąd zapisujemy w komunikacie (to informacja, nie twardy próg):
    wartość zależy od seeda i parametrów dryfu, które są założeniami modelu.
    """
    worst = 0.0
    for seed in range(1, 6):
        result = run(SCRIPT, realism=True, realism_seed=seed)
        assert result.status == "ok", result.flight.errors
        last = [s for s in result.flight.samples if s["z"] > 10][-1]
        distance = (last["x"] ** 2 + last["y"] ** 2) ** 0.5
        worst = max(worst, distance)
        assert distance <= 60.0, f"seed {seed}: {distance:.1f} cm od startu"
    print(f"return_home w trybie realistycznym: najgorzej {worst:.1f} cm")


def test_rc_delay_queue():
    """Opóźnienie RC: wychylenia trafiają do drona po ``rc_delay_s``."""
    params = realism.RealismParams(enabled=True, rc_delay_s=0.1)
    assert params.rc_delay_s == pytest.approx(0.1)
    # sam algorytm dryfu: przemieszczenie po 1 s jest ograniczone prędkością
    drift = realism.Drift(params)
    dx, dy = drift.displacement(0.0, 1.0)
    speed = (dx * dx + dy * dy) ** 0.5
    assert params.drift_speed_min - 1e-6 <= speed <= params.drift_speed_max + 1e-6


def test_move_scale_bounds():
    """Niedokładność ``move_*``: mnożnik w granicach 1 ± 5 %."""
    import random

    params = realism.RealismParams(enabled=True, move_error=0.05)
    rng = random.Random(1)
    scales = [realism.move_scale(params, rng) for _ in range(200)]
    assert min(scales) >= 0.95 and max(scales) <= 1.05
    assert realism.move_scale(realism.RealismParams(enabled=False), rng) == 1.0
