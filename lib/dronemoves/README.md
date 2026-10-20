# dronemoves

Płynne, wysokopoziomowe manewry dla dronów sterowanych z Pythona.
Działa z [DJI Tello](https://www.ryzerobotics.com/tello) (`djitellopy`), a ten sam
skrypt uruchomisz w symulatorze — biblioteka używa **wyłącznie publicznego API**
drona, więc nie zna ani symulatora, ani żadnego konkretnego SDK.

Instalacja prosto z GitHuba:

```
pip install "dronemoves[tello] @ git+https://github.com/Vardeex/drone-script-sim.git#subdirectory=lib/dronemoves"
```

```python
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()

with Pilot(tello, speed=40) as p:
    p.forward(100)
    p.turn(90, radius=80)
    p.circle(radius=100, direction="right")
    p.slalom(gates=4, spacing=100, width=60)

tello.land()
```

## Instalacja

```bash
pip install dronemoves            # rdzeń (bez djitellopy)
pip install dronemoves[tello]     # + backend dla DJI Tello (djitellopy)
```

Rdzeń biblioteki **nie wymaga** `djitellopy`. Import backendu Tello bez tej
biblioteki daje czytelny komunikat z poleceniem, co doinstalować.

Wymagania: Python 3.9+, zależności zewnętrzne: **brak**.

## Szybki start na prawdziwym Tello

```python
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
print("bateria:", tello.get_battery(), "%")
tello.takeoff()
tello.move_up(50)                 # start manewrów na bezpiecznej wysokości

try:
    with Pilot(tello, speed=40, max_height_cm=200, max_radius_cm=300,
               min_battery=30) as p:
        p.forward(100)            # płynnie: rozpędzanie, jazda, hamowanie
        p.turn(90, radius=80)     # łuk, nos podąża za torem
        p.hover(2)
finally:
    tello.land()
```

### Zasady bezpieczeństwa (prawdziwy dron)

1. **Zawsze** trzymaj `Pilot` w bloku `with` — przy wyjątku lub `Ctrl+C`
   biblioteka wysyła `rc(0,0,0,0)`, a przy `land_on_exit=True` (domyślnie)
   dodatkowo ląduje.
2. Ustaw **`max_height_cm`** i **`max_radius_cm`** — biblioteka sprawdza je
   **przed** każdym manewrem (manewr poza limitem nie startuje).
3. Ustaw **`min_battery`** (np. 30) — manewr przy niższej baterii rzuci
   `SafetyError`.
4. Zaczynaj na otwartej przestrzeni, bez ludzi w promieniu manewru; zapas
   `speed` (20–40 cm/s) na pierwsze testy.
5. RC jest wysyłane co 50 ms (20 Hz) — dron nie wyląduje z braku komend.
6. Na prawdziwym dronie **tory są przybliżone**: Tello nie ma GPS, więc
   występuje dryf i luz sterowania. Plan z `preview()` pokazuje tor idealny;
   faktyczny lot odchyli się od niego (typowo 5–20 cm na 100 cm drogi).

## API

```python
Pilot(drone=None, *, backend=None, speed=40, profile=TELLO_PROFILE,
      max_height_cm=300, max_radius_cm=500, min_battery=20,
      land_on_exit=True)
```

| Metoda | Opis |
|---|---|
| `forward(distance_cm)` | prosty płynny ruch do przodu |
| `turn(angle_deg, radius=80)` | łuk z nosem po torze (ujemny kąt = w prawo) |
| `arc(angle_deg, radius=100, direction=None)` | łuk o zadanym kącie |
| `circle(radius=100, direction="right", face="tangent")` | pełne okrążenie |
| `orbit(radius=120, turns=1)` | krążenie z nosem do środka |
| `slalom(gates=4, spacing=100, width=60)` | slalom przez środki bramek |
| `figure_eight(radius=80)` | ósemka (dwa okręgi styczne) |
| `spiral(radius=100, height=100, turns=2)` | wznoszenie po spirali |
| `path([(x, y, z), ...], smooth=True)` | spline przez punkty względne |
| `hover(seconds)` | zawis z komendami RC 20 Hz |
| `sequence([...])` | kilka manewrów jako jeden płynny ruch |
| `preview(maneuver)` | zaplanowany tor `[(x, y, z), ...]` **bez lotu** |
| `position()`, `yaw` | szacowana pozycja i kierunek w układzie startu |

Każdy manewr przyjmuje `mode="rc"` (domyślnie) lub `mode="native"`.
Manewr `sequence` działa na liście obiektów `Maneuver` (np. z `p._line_planner`).

## Tryb `rc` vs `native`

* **`rc`** (domyślnie) — biblioteka wysyła `send_rc_control` 20 Hz według
  zaplanowanej trajektorii. Ruch jest płynny, z obrotem nosa po torze,
  niezależny od ograniczeń komend Tello. Działa na każdym Tello.
* **`native`** — używa `curve_xyz_speed` / `go_xyz_speed` (dokładniejsze trasy,
  nos się nie obraca). Wymaga backendu wspierającego te komendy; jeśli backend
  ich nie ma, polecenie rzuci `NotImplementedError`.

## Walidacja i błędy

Parametry są sprawdzane **przed** startem manewru:

```python
p.turn(90, radius=20)
# PathError: Zakręt r=20 cm przy v=40 cm/s wymaga obrotu 115°/s - limit to 60°/s.
#            Zwiększ promień do min. 39 cm lub zmniejsz prędkość do 21 cm/s.
```

`PathError` — manewr niewykonalny (promień, prędkość, limit zasięgu/wysokości);
`SafetyError` — zbyt niska bateria lub zbyt niski pułap lotu.

## Kalibracja na prawdziwym dronie

`CalibrationProfile` przelicza wychylenie RC (`-100..100`) na cm/s i °/s oraz
opisuje opóźnienie reakcji. Domyślny profil odpowiada Tellowi (50 cm/s, 90 °/s,
opóźnienie 0,15 s).

```python
from dronemoves import CalibrationProfile, save_profile

profil = CalibrationProfile().with_measurements("forward", distance_cm=98.0,
                                                duration_s=2.0)
save_profile(profil, "moj_profil.json")
```

Pomiar wykonaj skryptem `examples/calibrate.py`: dron leci przez 2 s z `rc=100`,
mierzesz taśmą dystans (lub kąt) i zapisujesz profil — w symulatorze użyj
`Pilot(profile_path="moj_profil.json")`.

Profil jest **współdzielony z symulatorem** — ten sam model RC liczy trajektorię
i ruch drona w 3D, więc wyniki odpowiadają temu, co zakłada biblioteka.

## Własny dron / SDK

Zaimplementuj `MotionBackend` (`rc`, `stop`, opcjonalnie `go`, `curve`)
i przekaż go do `Pilot(backend=...)`. Manewry i trajektorie pozostają bez zmian.

## Testy

```bash
pip install -e ".[dev]"
pytest
```

Testy używają `FakeDrone` (prosty zamiennik drona), więc nie potrzebują
`djitellopy` ani symulatora. Testy integracyjne z symulatorem są w repozytorium
symulatora (`tests/`).

## Współpraca z symulatorem

Jeśli obiekt drona udostępnia metodę `annotate(label)` (ma ją tylko mock
symulatora), biblioteka oznacza nią początek i koniec manewru. Symulator zbiera
setki komend RC w jeden wiersz tabeli („circle r=100”) i rysuje zaplanowany tor
obok rzeczywistego. Na prawdziwym dronie `annotate` nie istnieje i nie jest
wywoływane.

## Licencja

MIT — patrz [LICENSE](LICENSE).
