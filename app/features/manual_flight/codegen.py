"""Generowanie skryptu Pythona z nagrania „Lotu ręcznego” - dwa warianty.

Wariant **(a) „wierne odtworzenie”**: ``send_rc_control`` + ``time.sleep``
z czasami z nagrania. Kolejne odcinki o identycznych wychyleniach są złączone
w jeden (symulator całkuje RC niezależnie od długości kroku, więc wynik jest
ten sam, a skrypt krótszy i czytelniejszy).

Wariant **(b) „uproszczony”**: nagranie zamienione na ``move_*``/``rotate_*``
z limitami Tello (20-500 cm, 1-360°). Ruch po skosie jest rozkładany na osie
(Tello nie ma komendy „skos”), a odcinki krótsze niż 20 cm są **pomijane** -
dlatego tor jest przybliżony i test dopuszcza 20 cm odchyłki w punktach
zatrzymań.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ...sim.core import default_rc_profile

#: limity komend ``move_*`` i ``rotate_*`` w Tello
MOVE_MIN_CM, MOVE_MAX_CM = 20, 500
ROTATE_MIN_DEG, ROTATE_MAX_DEG = 1, 360


def _num(value: float) -> str:
    """Liczba w tekście skryptu: bez zbędnych zer (``40``, nie ``40.0``)."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _merge_runs(recording: Sequence[Dict[str, Any]]
                ) -> List[Tuple[Tuple[int, int, int, int], float]]:
    """Złącz kolejne odcinki o identycznych wychyleniach w ``(rc, suma_dt)``."""
    runs: List[Tuple[Tuple[int, int, int, int], float]] = []
    for segment in recording:
        rc = (int(segment["lr"]), int(segment["fb"]), int(segment["ud"]),
              int(segment["yaw"]))
        seconds = float(segment["dt"])
        if runs and runs[-1][0] == rc:
            runs[-1] = (rc, runs[-1][1] + seconds)
        else:
            runs.append((rc, seconds))
    return runs


def _header(title: str, note: str, segments: int, duration: float) -> List[str]:
    return [
        f'"""Lot ręczny - {title}.',
        "",
        note,
        "",
        f"Nagranie: {segments} odcinków RC, {duration:.1f} s lotu.",
        "Wygenerowane przez DroneSim - Lot ręczny.",
        '"""',
        "",
        "import time",
        "",
        "from djitellopy import Tello",
        "",
        "",
        "def main() -> None:",
        "    tello = Tello()",
        "    tello.connect()",
    ]


def generate_rc_script(recording: Sequence[Dict[str, Any]], speed: int = 50) -> str:
    """Wariant (a): ``send_rc_control`` + ``time.sleep`` (wierne odtworzenie)."""
    runs = _merge_runs(recording)
    duration = sum(seconds for _rc, seconds in runs)
    lines = _header("odtworzenie RC (1:1)", (
        "Wierne odtworzenie nagrania: te same wychylenia RC i te same czasy.\n"
        "Konwencja Tello: lr+ = prawo, fb+ = przód, ud+ = góra, yaw+ = obrót w prawo."
    ), len(recording), duration)
    lines += [
        f"    tello.set_speed({int(speed)})",
        "    tello.takeoff()",
        "    try:",
    ]
    for (lr, fb, ud, yaw), seconds in runs:
        if not any((lr, fb, ud, yaw)):
            # WAŻNE: samo ``time.sleep`` nie zatrzymuje drona - Tello leci dalej
            # z ostatnim wychyleniem, więc przed postojem trzeba wyzerować RC.
            lines.append("        tello.send_rc_control(0, 0, 0, 0)")
            lines.append(f"        time.sleep({_num(round(seconds, 3))})"
                         f"   # postój {seconds:.2f} s")
            continue
        lines.append(f"        tello.send_rc_control({lr}, {fb}, {ud}, {yaw})")
        lines.append(f"        time.sleep({_num(round(seconds, 3))})")
    lines += [
        "    finally:",
        "        tello.send_rc_control(0, 0, 0, 0)",
        "        tello.land()",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ]
    return "\n".join(lines)


def _split_move(distance: float, command: str, opposite: str) -> List[str]:
    """Podziel odległość na komendy ``move_*`` w limitach 20-500 cm."""
    lines: List[str] = []
    remaining = abs(distance)
    if remaining < MOVE_MIN_CM:
        return lines                       # za krótko - Tello tego nie wykona
    name = command if distance > 0 else opposite
    while remaining >= MOVE_MIN_CM:
        step = min(remaining, float(MOVE_MAX_CM))
        if remaining - step < MOVE_MIN_CM:
            step = remaining               # ostatni kawałek wchłania resztę
        lines.append(f"        tello.{name}({int(round(step))})")
        remaining -= step
    return lines


def _split_rotate(degrees: float) -> List[str]:
    """Podziel obrót na komendy ``rotate_*`` w limitach 1-360°."""
    lines: List[str] = []
    remaining = abs(degrees)
    if remaining < ROTATE_MIN_DEG:
        return lines
    name = "rotate_clockwise" if degrees > 0 else "rotate_counter_clockwise"
    while remaining >= ROTATE_MIN_DEG:
        step = min(remaining, float(ROTATE_MAX_DEG))
        if remaining - step < ROTATE_MIN_DEG:
            step = remaining
        lines.append(f"        tello.{name}({int(round(step))})")
        remaining -= step
    return lines


def generate_simple_script(recording: Sequence[Dict[str, Any]], speed: int = 50) -> str:
    """Wariant (b): złączone ``move_*`` / ``rotate_*`` (przybliżony, czytelny)."""
    profile = default_rc_profile()
    runs = _merge_runs(recording)
    duration = sum(seconds for _rc, seconds in runs)

    # 1) zamień odcinki RC na ruchy/obroty w układzie drona i połącz podobne
    blocks: List[Tuple[str, Tuple[int, int, int, int], Tuple[float, float, float, float]]] = []
    for (lr, fb, ud, yaw), seconds in runs:
        if abs(yaw) > 0 and not any((lr, fb, ud)):
            kind = "rotate"
            values = (0.0, 0.0, 0.0, profile.rc_to_yaw_rate(yaw) * seconds)
        elif any((lr, fb, ud)):
            kind = "move"
            values = (profile.rc_to_speed(fb) * seconds,
                      profile.rc_to_speed(lr) * seconds,
                      profile.rc_to_vertical(ud) * seconds, 0.0)
        else:
            kind, values = "idle", (0.0, 0.0, 0.0, 0.0)
        key = tuple(1 if value > 1e-9 else (-1 if value < -1e-9 else 0)
                    for value in values)
        if blocks and blocks[-1][0] == kind and blocks[-1][1] == key:
            previous = blocks[-1][2]
            blocks[-1] = (kind, key, tuple(a + b for a, b in zip(previous, values)))
        else:
            blocks.append((kind, key, values))

    lines = _header("wersja uproszczona (move_*/rotate_*)", (
        "Uproszczone odtworzenie: ruchy po skosie rozłożone na osie, odcinki\n"
        f"krótsze niż {MOVE_MIN_CM} cm pominięte (limit Tello). Tor jest przybliżony\n"
        "- do wiernego odtworzenia użyj wariantu z send_rc_control."
    ), len(recording), duration)
    lines += [
        f"    tello.set_speed({int(speed)})",
        "    tello.takeoff()",
        "    try:",
    ]
    emitted = False
    for kind, _key, values in blocks:
        forward, right, up, dyaw = values
        if kind == "rotate":
            commands = _split_rotate(dyaw)
        elif kind == "move":
            commands = (_split_move(up, "move_up", "move_down")
                        + _split_move(forward, "move_forward", "move_back")
                        + _split_move(right, "move_right", "move_left"))
        else:
            commands = []
        if commands:
            lines.extend(commands)
            emitted = True
    if not emitted:
        lines.append("        # nagranie nie zawiera ruchów mieszczących się w limitach Tello")
    lines += [
        "    finally:",
        "        tello.land()",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ]
    return "\n".join(lines)


VARIANTS = {
    "rc": ("Wierne odtworzenie (send_rc_control)", generate_rc_script),
    "simple": ("Uproszczony (move_*/rotate_*)", generate_simple_script),
}


def generate(recording: Sequence[Dict[str, Any]], variant: str = "rc",
             speed: int = 50) -> str:
    """Wygeneruj skrypt w wybranym wariancie (``rc`` albo ``simple``)."""
    if variant not in VARIANTS:
        raise ValueError(f"Nieznany wariant skryptu: {variant!r} "
                         f"(dozwolone: {', '.join(VARIANTS)})")
    return VARIANTS[variant][1](recording, speed=speed)
