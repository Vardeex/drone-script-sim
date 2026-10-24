"""Generator trybu „płynna” - biblioteka ``dronemoves``.

Kod korzysta wyłącznie z publicznego API:

* ``Pilot.path(points, smooth=True)`` - spline przez punkty (nos po torze),
* ``Pilot.hover(sekundy)`` - zawis,
* ``tello.rotate_clockwise()/rotate_counter_clockwise()`` - obrót nosa w miejscu
  (tylko punkty ze stałym kursem / kursem na punkt: ``Pilot.path`` prowadzi nos
  po torze i nie da się go ustawić innym kątem).

Dwie właściwości ``dronemoves`` kształtują generowany kod:

1. ``Pilot.path`` obraca punkty o **aktualny kurs pilota** (``_transform``),
   więc podajemy je w układzie „dron patrzy na +X” (obrócone o ``-kurs``),
2. przy zakręcie pilot liczy obciążenie boczne i wygładza skręt; przy dużych
   obciążeniach odcina narożniki (spline wypukły). Dlatego pierwszy punkt
   trasy (po ``takeoff`` nie ma jeszcze kursu) dostaje kurs osiowy, a reszta
   trafia do ``path`` z prędkością trasy - patrz ``speed_hint``.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from .codegen_common import battery_check, header, num
from .model import (MAX_RADIUS_CM, TAKEOFF_HEIGHT_CM, Route, RouteError)

#: opisy trybu nosa do komentarzy
HEADING_LABELS = {
    "track": "nos po torze",
    "fixed": "stały kurs",
    "point": "nos w stronę punktu",
    "start": "nos w stronę startu",
}


def heading_after(route: Route, index: int) -> float:
    """Kurs nosa po dojeździe do punktu ``index`` (konwencja Tello, + = prawo).

    Dla ``track`` kąt wynika z kierunku ostatniego odcinka (informacyjnie).
    """
    point = route.points[index]
    start, end = route.legs()[index]
    if point.heading == "fixed":
        return point.yaw_deg % 360.0
    if point.heading == "point" and point.look_at is not None:
        lx, ly = point.look_at
        return math.degrees(math.atan2(-(ly - end[1]), lx - end[0])) % 360.0
    if point.heading == "start":
        return math.degrees(math.atan2(end[1], -end[0])) % 360.0
    dx, dy = end[0] - start[0], end[1] - start[1]
    return math.degrees(math.atan2(-dy, dx)) % 360.0


def turn_delta(yaw: float, target: float) -> float:
    """Najkrótszy obrót z ``yaw`` do ``target`` (zakres -180..180, + = w prawo)."""
    return (target - yaw + 180.0) % 360.0 - 180.0


def turn_lines(yaw: float, target: float, indent: str,
               comment: str) -> Tuple[List[str], float]:
    """Linie obrotu nosa w miejscu (pomija korekty mniejsze niż 1°).

    ``yaw``/``target`` są w konwencji API (+ = w prawo). Kąt do ``rotate_*``
    musi być dodatni: kierunek wynika z nazwy metody, a ``rotate_counter_clockwise``
    z ujemnym argumentem obraca w przeciwną stronę (podwójna negacja).
    """
    delta = turn_delta(yaw, target)
    if abs(delta) < 1.0:
        return [], yaw
    method = "rotate_clockwise" if delta > 0 else "rotate_counter_clockwise"
    return ([f"{indent}tello.{method}({num(abs(delta))})   # {comment}"],
            (yaw + delta) % 360.0)


def _track_yaw(route: Route, segment: List[int]) -> float:
    """Kurs nosa po przeleceniu ``segment`` (konwencja API, + = w prawo).

    ``Pilot.path`` ustawia nos zgodnie z kierunkiem **ostatniego odcinka**
    segmentu (niezależnie od ``heading`` punktu). Dla segmentu jednopunktowego
    nos się nie zmienia, więc bierzemy kierunek odcinka poprzedzającego.
    """
    if len(segment) >= 2:
        start = route.points[segment[-2]].position
        end = route.points[segment[-1]].position
        return math.degrees(math.atan2(-(end[1] - start[1]), end[0] - start[0])) % 360.0
    # jeden punkt: kurs nieznany z samego segmentu - zostaje ostatni znany
    return 0.0


def _path_segments(route: Route) -> List[List[int]]:
    """Podziel punkty na wywołania ``path``.

    Granice wywołań:

    * przed punktem ze stałym kursem / kursem na punkt / na start (obrót
      ustawiamy w miejscu po doleceniu),
    * gdy odcinek między punktami trasy jest dłuższy niż :data:`MAX_PATH_LEG_CM`
      (``Pilot.path`` sprawdza ``max_radius_cm`` względem bieżącej pozycji
      drona, nie względem startu).
    """
    segments: List[List[int]] = []
    current: List[int] = []
    previous = (0.0, 0.0, TAKEOFF_HEIGHT_CM)
    for index, point in enumerate(route.points):
        if current and math.dist(previous, point.position) > MAX_PATH_LEG_CM:
            segments.append(current)
            current = []
        current.append(index)
        if point.heading in ("fixed", "point", "start"):
            segments.append(current)
            current = []
        previous = point.position
    if current:
        segments.append(current)
    return segments


def _pairs(points) -> str:
    """Lista punktów jako tekst Pythona: ``[(x, y, z), ...]``."""
    return "[" + ", ".join(f"({num(x)}, {num(y)}, {num(z)})" for x, y, z in points) + "]"


def _to_pilot_frame(points: List[Tuple[float, float, float]],
                    offset: Tuple[float, float, float],
                    yaw: float) -> List[Tuple[float, float, float]]:
    """Punkty lotu -> układ, który ``Pilot.path`` obróci z powrotem o ``yaw``.

    ``_transform`` w dronemoves mnoży punkty przez obrót o kurs pilota, więc
    podajemy je przesunięte o aktualną pozycję i obrócone o ``-yaw``.
    """
    cos_a, sin_a = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    result = []
    for x, y, z in points:
        dx, dy = x - offset[0], y - offset[1]
        result.append((dx * cos_a + dy * sin_a, -dx * sin_a + dy * cos_a, z - offset[2]))
    return result


#: maksymalna długość jednego ``pilot.path`` (cm). Limit ``max_radius_cm`` = 500 cm
#: dotyczy odległości WZGLĘDNEJ punktów od pozycji drona w chwili wywołania,
#: więc jeden odcinek może mieć najwyżej ~500 cm; bierzemy zapas 400 cm.
MAX_PATH_LEG_CM = 400.0


def split_long_legs(route: Route,
                    limit: float = MAX_PATH_LEG_CM) -> List[Tuple[float, float, float]]:
    """Rozbij trasę na punkty pośrednie, żeby każdy odcinek był ≤ ``limit``.

    ``Pilot.path`` dostaje punkty **względne** i sprawdza ich odległość od
    aktualnej pozycji drona (``max_radius_cm``). Dłuższy odcinek trasy
    (:math:`L > limit`) dzielimy na :math:`n = \\lceil L / limit \\rceil` równych
    części - wszystkie punkty pośrednie leżą na odcinku, więc trasa przechodzi
    przez nie dokładnie (odchyłka spline jest taka sama jak dla oryginału).

    :return: lista punktów ``(x, y, z)`` w układzie świata (z wysokością trasy)
    """
    if not route.points:
        return []
    result: List[Tuple[float, float, float]] = []
    previous = (0.0, 0.0, TAKEOFF_HEIGHT_CM)
    for point in route.points:
        start, end = previous, point.position
        length = math.dist(start, end)
        steps = max(1, int(math.ceil(length / limit - 1e-9)))
        for step in range(1, steps + 1):
            fraction = step / steps
            result.append((start[0] + (end[0] - start[0]) * fraction,
                           start[1] + (end[1] - start[1]) * fraction,
                           start[2] + (end[2] - start[2]) * fraction))
        previous = end
    return result


def _split_legs(points: List[Tuple[float, float, float]],
                start: Tuple[float, float, float],
                limit: float = MAX_PATH_LEG_CM) -> List[List[Tuple[float, float, float]]]:
    """Podziel wywołanie ``path`` na kawałki, w których każdy odcinek jest ≤ ``limit``.

    Punkt z trasy (cel użytkownika) zawsze zamyka kawałek - punkty pośrednie
    leżą na odcinkach trasy, więc spline przechodzi dokładnie tak samo jak
    przy jednym wywołaniu ``path``.

    :param points: punkty trasy w układzie świata (wysokość bezwzględna)
    :param start: pozycja drona (świat) przed pierwszym wywołaniem
    :return: lista kawałków; każdy to lista punktów w układzie świata
    """
    pieces: List[List[Tuple[float, float, float]]] = []
    current: List[Tuple[float, float, float]] = []
    previous = start
    for point in points:
        length = math.dist((previous[0], previous[1]), (point[0], point[1]))
        if length <= limit:
            # krótki odcinek: zostaje w bieżącym wywołaniu `path`
            current.append(point)
            previous = point
            continue
        # długi odcinek: dolatujemy punktami pośrednimi, ale w tym samym `path`
        # (oryginał przechodzi przez punkt końcowy - kolejne łuki interpolują
        # to samo, więc trasa się nie zmienia), a wywołanie kończy się na punkcie
        steps = int(math.ceil(length / limit - 1e-9))
        for step in range(1, steps + 1):
            fraction = step / steps
            current.append((previous[0] + (point[0] - previous[0]) * fraction,
                            previous[1] + (point[1] - previous[1]) * fraction,
                            previous[2] + (point[2] - previous[2]) * fraction))
        pieces.append(current)
        current = []
        previous = point
    if current:
        pieces.append(current)
    return pieces


def generate(route: Route) -> str:
    """Wygeneruj skrypt trybu „płynna” (dronemoves) dla trasy.

    :raises RouteError: gdy trasa jest pusta, ma różne prędkości odcinków
        albo przekracza limit zasięgu dronemoves
    """
    if not route.points:
        raise RouteError("Trasa jest pusta - dodaj przynajmniej jeden punkt.")
    speeds = {route.speed_for(i) for i in range(len(route.points))}
    if len(speeds) > 1:
        raise RouteError("Tryb „płynna” ma jedną prędkość na całą trasę - usuń "
                         "prędkości indywidualne albo wybierz tryb „prosta”.")
    speed = speeds.pop()
    # Uwaga: ``radius`` (> MAX_RADIUS_CM) nie jest błędem - długie odcinki
    # rozbija ``_split_legs`` na kawałki po MAX_PATH_LEG_CM (< 500 cm), więc każde
    # wywołanie ``Pilot.path`` mieści się w ``max_radius_cm`` licząc od pozycji
    # drona, a nie od startu.

    # ``max_radius_cm`` pilota to zasięg liczony **od startu** - musi pokryć
    # najdalszy punkt trasy (z 10 % zapasu), inaczej ``Pilot.path`` rzuci
    # ``PathError``. Limit Tello (100 m) i tak pilnuje walidator trasy.
    radius = max((math.hypot(p.x, p.y) for p in route.points), default=0.0)
    pilot_radius = max(MAX_RADIUS_CM, math.ceil(radius * 1.1))
    lines: List[str] = header(route, "smooth",
                              "Trasa drona - tryb płynny (biblioteka dronemoves).")
    lines.extend([
        "def main() -> None:",
        "    tello = Tello()",
        "    tello.connect()",
    ])
    lines.extend(battery_check())
    lines.extend([
        f"    pilot = Pilot(tello, speed={num(speed)}, max_height_cm=500,"
        f" max_radius_cm={num(pilot_radius)})",
        "    yaw = 0.0   # kurs nosa w konwencji Tello (+ = w prawo)",
        "    try:",
    ])

    yaw = 0.0                                  # kurs nosa (po takeoff, + = prawo)
    offset = (0.0, 0.0, TAKEOFF_HEIGHT_CM)     # dokąd trafił dotychczasowy lot
    for segment in _path_segments(route):
        first, last = segment[0] + 1, segment[-1] + 1
        label = f"punkty {first}-{last}" if first != last else f"punkt {first}"
        lines.append(f"        # {label}")
        for i in segment:
            point = route.points[i]
            lines.append(f"        #   punkt {i + 1}: ({num(point.x)}, {num(point.y)}, "
                         f"{num(point.z)}) - {HEADING_LABELS[point.heading]}")
        # ``Pilot.path`` przyjmuje punkty WZGLĘDNE (w układzie drona po starcie):
        # biblioteka przesuwa je o aktualną pozycję i obraca o kurs pilota.
        # Przesuwamy więc punkty o pozycję po poprzednim manewrze i obracamy o -kurs,
        # a wysokość - o wysokość po ``takeoff`` (dron jest już na 80 cm,
        # więc z trasy jest bezwzględne i trzeba je przeliczyć na różnicę).
        # Długi odcinek dzielimy na kawałki <= MAX_PATH_LEG_CM, ale ostateczny
        # cel (punkt z trasy) musi pozostać dokładnie ostatnim punktem wywołania.
        flight = [route.points[i].position for i in segment]
        pieces = _split_legs(flight, offset)
        for piece in pieces:
            points = _to_pilot_frame(piece, offset, yaw)
            lines.append(f"        pilot.path({_pairs(points)}, smooth=True)")
            offset = piece[-1]      # pozycja po tym wywołaniu (do następnego)
        # ``Pilot.path`` obraca nos do kursu ostatniego odcinka (sprawdzone:
        # segment 90° -> 180° kończy na 176°), więc kurs po torze to kierunek
        # ostatniego odcinka w konwencji API (get_yaw: + = w prawo).
        track_yaw = _track_yaw(route, segment)
        offset = route.points[segment[-1]].position
        for i in segment:
            point = route.points[i]
            if point.hover_s > 0:
                lines.append(f"        pilot.hover({num(point.hover_s)})"
                             f"   # punkt {i + 1}: zawis {num(point.hover_s)} s")
        # kurs „stały”/„na punkt”/„jak na starcie” ustawiamy obrotem w miejscu
        last_point = route.points[segment[-1]]
        if last_point.heading in ("fixed", "point", "start"):
            target = heading_after(route, segment[-1])
            turn, track_yaw = turn_lines(
                track_yaw, target, "        ",
                f"punkt {segment[-1] + 1}: {HEADING_LABELS[last_point.heading]}"
                f" {num(target)}°")
            lines.extend(turn)
        yaw = track_yaw

    if route.return_home:
        # ``Pilot.return_home()`` wraca do miejsca utworzenia pilota (po takeoff)
        # - to samo, co robi tryb „prosta” przez ``go_xyz_speed`` do (0, 0, 80).
        lines.append("        # powrót do miejsca startu (Pilot.return_home)")
        lines.append("        pilot.return_home()")

    lines.extend([
        "    finally:",
        "        # bezpieczne lądowanie także przy błędzie lub Ctrl+C",
        "        tello.land()",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ])
    return "\n".join(lines)

