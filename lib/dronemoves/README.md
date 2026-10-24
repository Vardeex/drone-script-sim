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

### Instalacja ze źródeł (w tym repozytorium)

Symulator instaluje bibliotekę sam: `requirements.txt` w katalogu głównym repo
ma `-e ./lib/dronemoves` (bez `[tello]`). Ręcznie:

```bash
# z katalogu głównego repozytorium (ścieżka w requirements.txt jest względna)
pip install -r requirements.txt

# albo wprost - instalacja edytowalna, zmiany w kodzie widoczne od razu
pip install -e ./lib/dronemoves          # rdzeń
pip install -e "./lib/dronemoves[tello]" # + djitellopy (tylko prawdziwy dron)
```

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
        p.turn(90, radius=80)     # łuk w PRAWO (dodatni kąt = w prawo, jak w Tello)
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
      land_on_exit=True, sim_exact=False)
```

| Metoda | Opis |
|---|---|
| `forward(distance_cm)` | prosty płynny ruch do przodu |
| `turn(angle_deg, radius=80)` | łuk z nosem po torze (**dodatni kąt = w prawo**, jak w Tello) |
| `arc(angle_deg, radius=100, direction=None)` | łuk (**dodatni kąt = w prawo**; `direction` wymusza stronę) |
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

## Kierunek kątów (konwencja Tello)

**Dodatni kąt = skręt w PRAWO** (zgodnie z zegarem), ujemny = w lewo — tak samo
jak `rotate_clockwise` i rosnący `get_yaw()` w Tello. Dotyczy `turn`, `arc`,
`Pilot.yaw` oraz `yaw` w `preview_trajectory`:

```python
pilot.turn(90, radius=60)     # w PRAWO: Pilot.yaw == 90, dron kończy na −y
pilot.turn(-90, radius=60)    # w LEWO:  Pilot.yaw == 270, dron kończy na +y
pilot.arc(180, radius=100)    # półkole w prawo
```

Parametry tekstowe są jednoznaczne i niezależne od znaku kąta:
`direction="right"` = po prawej stronie kursu startowego (dla `circle`, `orbit`
i `arc` z wymuszoną stroną), `"left"` = po lewej.

Wewnętrznie (planer, trajektorie, symulator) kurs jest matematyczny — dodatni =
w lewo (CCW). Konwersja jest w **jednym miejscu**:
`dronemoves.pilot.api_angle_to_internal()` / `internal_angle_to_api()`.

> **Uwaga do wersji 0.1.3**: wydanie 0.1.3 miało odwrócony kierunek
> `turn`/`arc` (dodatni kąt = w lewo). Wersja 0.1.4 przywraca konwencję Tello
> z 0.1.0–0.1.2. Jeśli piszesz kod pod 0.1.3, zmień znaki kątów.

## Symulator: ścieżka jak na prawdziwym dronie

Domyślnie biblioteka steruje **wyłącznie przez `send_rc_control`** — również
w symulatorze. Symulator przelicza wychylenia RC na prędkości **tym samym
profilem kalibracji** (`CalibrationProfile`), którego używa planer, więc test
w symulatorze sprawdza dokładnie tę drogę, którą pójdzie prawdziwe Tello
(z wychyleniami zaokrąglonymi do liczb całkowitych).

Dla diagnostyki (porównanie z idealną trajektorią, bez kwantyzacji RC) można
włączyć kanał dokładnych prędkości — działa tylko z mockiem symulatora
(`send_dronemoves_profile`); prawdziwe `djitellopy` go nie ma:

```python
pilot = Pilot(tello, speed=35, sim_exact=True)   # tylko diagnostyka!
```

## Bezpieczeństwo (0.2.0)

Biblioteka nie każe startować „w ciemno”. Przed lotem sprawdź drona, a potem
użyj `safe_start`, który **nie wystartuje**, jeśli preflight znajdzie błąd:

```python
from djitellopy import Tello
from dronemoves import Pilot, PreflightError, preflight, safe_start

tello = Tello()
tello.connect()

print(preflight(tello, plan_eta_s=120))     # raport OK / OSTRZEŻENIE / BŁĄD

pilot = Pilot(tello, speed=40)
try:
    safe_start(tello, pilot=pilot, confirm=True, countdown_s=3)
except PreflightError as exc:
    print("Start wstrzymany:", exc)
```

### Progi preflight (założenia)

| Test | Błąd (nie startuj) | Ostrzeżenie |
|---|---|---|
| Bateria | < 50 % | < 60 % |
| Temperatura (`get_highest_temperature`, °C) | >= 80 | >= 70 |
| Wi-Fi (`query_wifi_signal_noise_ratio`, dB) | - | < 10 dB; brak odczytu też tylko ostrzeżenie |
| Dron odpowiada (`query_sdk_version`) | - | brak odpowiedzi |
| Dron na ziemi (`get_height`) | > 20 cm | - |
| Czas trasy vs bateria (opcjonalnie) | - | plan > `(bateria-10)*10 s - 60 s` |

Temperatura: Tello raportuje `temph` (najwyższa) z telemetrii; 80 °C to górna
granica pracy bez ryzyka przegrzania, 70 °C - sygnał, żeby dać dronowi
ostygnąć. Po `safe_start` sprawdzamy `get_height()` - brak wzniesienia daje
ostrzeżenie w raporcie.

### Pozostałe narzędzia

```python
pil.set_geofence(max_height_cm=250, max_radius_cm=300,
                 box_cm=(-200, 200, -200, 200))   # każdy manewr sprawdzany z góry
pil.watch_battery(min_pct=25, action="return_home")  # nadzór w tle
pil.return_home()                                   # powrót po szacowanej pozycji
pil.safe_land()                                     # stop, zawis, lądowanie
```

* **Geofence** - przed każdym manewrem sprawdzana jest cała zaplanowana
  trajektoria (wysokość nad ziemią, odległość od startu, opcjonalny prostokąt
  X/Y). Naruszenie = `SafetyError`, manewr się nie wykonuje.
* **`watch_battery`** - wątek w tle; po spadku poniżej progu przerywa lot,
  wraca do startu (albo tylko ląduje) i kończy pracę.
* **`return_home`** - lot do `(0, 0)` po szacowanej pozycji pilota; w
  symulatorze wraca w granicach kilku centymetrów.

### `circle(face=...)`

```python
pil.circle(radius=100, direction="right", face="center")  # nos w środek okręgu
pil.circle(radius=100, direction="right", face="fixed")   # nos bez zmian
```

`tangent` (domyślnie) prowadzi nos po torze, `center` obraca go w stronę
środka okręgu, a `fixed` zostawia kurs startowy. Wcześniej oba działały jak
`tangent`.

### Symulator: ustawienia do testów preflight

```python
tello.set_sim_settings(battery=30, start_temperature_c=85, wifi_snr_db=5)
```

Działa tylko w symulatorze (mock) - na prawdziwym Tello metoda nie istnieje.

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

MIT — patrz
[LICENSE](https://github.com/Vardeex/drone-script-sim/blob/main/lib/dronemoves/LICENSE).
