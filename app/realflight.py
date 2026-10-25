"""Import i porównanie lotu **rzeczywistego** z symulowanym.

Lot rzeczywisty pochodzi z ``dronemoves.flightlog`` (flaga ``"source": "real"``).
Porównanie odpowiada na pytanie „jak bardzo symulacja odbiega od drona":

* pozycje obu lotów są próbkowane w tych samych chwilach (interpolacja liniowa),
* błąd rozkładamy na **wzdłuż toru** (skala prędkości), **w bok** (kurs/obrót)
  i **w pionie** (wysokość) - każda składowa wskazuje inny parametr profilu,
* na końcu powstają konkretne podpowiedzi kalibracyjne z liczbami.

Wszystko liczone z geometrii (odległości euklidesowe w cm), bez „magicznych"
współczynników.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: minimalna liczba próbek, żeby porównanie miało sens
MIN_SAMPLES = 5
#: progi, od których uznajemy składową błędu za istotną [cm]
BIAS_THRESHOLD_CM = 3.0
#: ile punktów trafia do wykresu (reszta jest uśredniana)
PLOT_POINTS = 300


def validate_real(payload: Any) -> Dict[str, Any]:
    """Sprawdź, czy wgrany plik jest lotem rzeczywistym. Zwraca payload.

    :raises ValueError: gdy plik nie jest lotem ``source: real`` albo nie ma próbek.
    """
    if not isinstance(payload, dict):
        raise ValueError("Plik nie jest lotem (oczekiwano obiektu JSON).")
    if payload.get("source") != "real":
        raise ValueError("To nie jest lot rzeczywisty - brak flagi \"source\": \"real\". "
                         "Użyj „Wczytaj lot (JSON)” dla lotów symulatora.")
    samples = payload.get("samples")
    if not isinstance(samples, list) or len(samples) < MIN_SAMPLES:
        raise ValueError(f"Lot rzeczywisty ma za mało próbek "
                         f"(jest {0 if not isinstance(samples, list) else len(samples)}, "
                         f"minimum {MIN_SAMPLES}).")
    for index, sample in enumerate(samples[:5]):
        for key in ("t", "x", "y", "z"):
            if key not in sample:
                raise ValueError(f"Próbka {index} nie ma pola '{key}' - plik jest "
                                 "uszkodzony albo z nieznanej wersji rejestratora.")
    return payload


def _positions(payload: Dict[str, Any]) -> List[Tuple[float, float, float, float]]:
    """Lista ``(t, x, y, z)`` posortowana po czasie."""
    points = [(float(s["t"]), float(s["x"]), float(s["y"]), float(s["z"]))
              for s in payload.get("samples") or []]
    points.sort(key=lambda item: item[0])
    return points


def _interpolate(points: Sequence[Tuple[float, float, float, float]],
                 moment: float) -> Optional[Tuple[float, float, float]]:
    """Pozycja w chwili ``moment`` (liniowo); ``None`` poza zakresem lotu."""
    if not points or moment < points[0][0] or moment > points[-1][0]:
        return None
    times = [point[0] for point in points]
    index = bisect.bisect_left(times, moment)
    if index == 0:
        return points[0][1:]
    if index >= len(points):
        return points[-1][1:]
    t0, x0, y0, z0 = points[index - 1]
    t1, x1, y1, z1 = points[index]
    span = t1 - t0
    if span <= 1e-9:
        return (x1, y1, z1)
    ratio = (moment - t0) / span
    return (x0 + (x1 - x0) * ratio, y0 + (y1 - y0) * ratio, z0 + (z1 - z0) * ratio)


def _path_length(points: Sequence[Tuple[float, float, float, float]]) -> float:
    """Długość toru [cm]."""
    return sum(math.dist(points[i - 1][1:], points[i][1:])
               for i in range(1, len(points)))


def _downsample(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Zmniejsz liczbę punktów wykresu (zachowując pierwszy i ostatni)."""
    if len(rows) <= PLOT_POINTS:
        return rows
    step = len(rows) / PLOT_POINTS
    picked = [rows[int(index * step)] for index in range(PLOT_POINTS)]
    picked[-1] = rows[-1]
    return picked


def _hints(along: float, cross: float, vertical: float, max_error: float,
           real_length: float, sim_length: float, duration: float) -> List[str]:
    """Konkretne podpowiedzi kalibracyjne (co zmienić i o ile)."""
    hints: List[str] = []
    if real_length > 20.0 and sim_length > 20.0:
        ratio = sim_length / real_length
        if abs(ratio - 1.0) > 0.05:
            direction = "mniejszą" if ratio > 1.0 else "większą"
            percent = abs(ratio - 1.0) * 100.0
            factor = real_length / sim_length
            hints.append(
                f"Symulacja pokonuje {percent:.0f}% {direction} drogę niż dron "
                f"({sim_length:.0f} cm vs {real_length:.0f} cm). W profilu kalibracji "
                f"ustaw `max_speed_cm_s` (i `max_vertical_cm_s`) razy {factor:.2f}.")
    if abs(along) > BIAS_THRESHOLD_CM:
        hints.append(
            f"Wzdłuż toru symulacja wyprzedza drona o {along:+.0f} cm - to głównie "
            f"skala prędkości (`max_speed_cm_s`), nie geometria manewrów.")
    if abs(cross) > BIAS_THRESHOLD_CM:
        hints.append(
            f"Tor jest przesunięty w bok o {cross:+.0f} cm - sprawdź "
            f"`max_yaw_rate_dps` (realny Tello skręca inaczej) oraz znak osi obrotu "
            f"w profilu (dodatni = w lewo).")
    if abs(vertical) > BIAS_THRESHOLD_CM:
        hints.append(
            f"Różnica wysokości {vertical:+.0f} cm - popraw `max_vertical_cm_s` "
            f"i wysokość startu (Tello wznosi się na ~80 cm, egzemplarze się różnią).")
    if duration > 20.0 and max_error > 20.0:
        hints.append(
            "Odchyłka rośnie z czasem: pozycja lotu rzeczywistego jest **szacowana "
            "z prędkości** (dryf), więc do kalibracji porównuj odcinki do ~20-30 s "
            "albo loty z matami Mission Pad (dają pozycję odniesienia).")
    if not hints:
        hints.append("Brak istotnych odchyłek powyżej progu 3 cm - profil wygląda dobrze.")
    return hints


def compare(real: Dict[str, Any], sim: Dict[str, Any],
            step_s: float = 0.1) -> Dict[str, Any]:
    """Porównaj lot rzeczywisty z symulowanym (te same chwile, interpolacja).

    :param step_s: krok próbkowania porównania (mniejszy = więcej punktów).
    :returns: statystyki odchyłek, seria punktów do wykresu i podpowiedzi.
    """
    real_points = _positions(real)
    sim_points = _positions(sim)
    if len(real_points) < MIN_SAMPLES or len(sim_points) < MIN_SAMPLES:
        raise ValueError("Za mało próbek do porównania (minimum 5 w każdym locie).")

    start = max(real_points[0][0], sim_points[0][0])
    end = min(real_points[-1][0], sim_points[-1][0])
    if end - start < step_s:
        raise ValueError("Loty nie pokrywają się w czasie - nie ma czego porównywać.")

    rows: List[Dict[str, Any]] = []
    errors: List[float] = []
    along_total = cross_total = vertical_total = 0.0
    moment = start
    while moment <= end + 1e-9:
        real_position = _interpolate(real_points, moment)
        sim_position = _interpolate(sim_points, moment)
        if real_position and sim_position:
            dx = sim_position[0] - real_position[0]
            dy = sim_position[1] - real_position[1]
            dz = sim_position[2] - real_position[2]
            error = math.dist(sim_position, real_position)
            # kierunek ruchu drona w tej chwili (do rozkładu błędu na składowe)
            ahead = _interpolate(real_points, min(moment + step_s, end))
            heading = (0.0, 0.0)
            if ahead:
                hx, hy = ahead[0] - real_position[0], ahead[1] - real_position[1]
                norm = math.hypot(hx, hy)
                if norm > 1e-6:
                    heading = (hx / norm, hy / norm)
            along = dx * heading[0] + dy * heading[1]
            cross = -dx * heading[1] + dy * heading[0]
            errors.append(error)
            along_total += along
            cross_total += cross
            vertical_total += dz
            rows.append({
                "t": round(moment, 2),
                "real": [round(value, 1) for value in real_position],
                "sim": [round(value, 1) for value in sim_position],
                "error_cm": round(error, 1),
            })
        moment += step_s

    if not errors:
        raise ValueError("Nie udało się porównać lotów (brak wspólnych próbek).")
    count = len(errors)
    sorted_errors = sorted(errors)
    duration = end - start
    real_slice = [point for point in real_points if start <= point[0] <= end]
    sim_slice = [point for point in sim_points if start <= point[0] <= end]
    real_length = _path_length(real_slice)
    sim_length = _path_length(sim_slice)
    report = {
        "duration_s": round(duration, 2),
        "points": count,
        "max_error_cm": round(sorted_errors[-1], 1),
        "mean_error_cm": round(sum(errors) / count, 1),
        "p95_error_cm": round(sorted_errors[min(count - 1, int(count * 0.95))], 1),
        "final_error_cm": round(errors[-1], 1),
        "real_path_cm": round(real_length, 1),
        "sim_path_cm": round(sim_length, 1),
        "mean_along_cm": round(along_total / count, 1),
        "mean_cross_cm": round(cross_total / count, 1),
        "mean_vertical_cm": round(vertical_total / count, 1),
    }
    report["hints"] = _hints(along_total / count, cross_total / count,
                             vertical_total / count, report["max_error_cm"],
                             real_length, sim_length, duration)
    return {"report": report, "series": _downsample(rows),
            "real": {"id": real.get("id"), "name": real.get("script_name")},
            "sim": {"id": sim.get("id"), "name": sim.get("script_name")}}
