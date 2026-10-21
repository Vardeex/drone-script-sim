# Zmiany w dronemoves

Forma zgodna z [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie zgodne z [SemVer](https://semver.org/lang/pl/).

## [0.1.3] - 2026-10-21

Spójność układu współrzędnych: obrót w prawo i ruch w prawo idą teraz na tę
samą stronę. Ustalono **jeden układ dla całego projektu** (opis w README,
sekcja „Układ współrzędnych”):

* osie świata: **x = przód, y = lewo, z = góra** (prawo drona = −y),
* kurs wewnętrzny (silnik, planer, `physics`): **CCW+** (dodatni = obrót w lewo),
* `get_yaw()` i `yaw` w `send_rc_control` (API Tello): **CW+** (dodatni = w prawo),
* zmiana znaku tylko na granicy API (adapter, `rc_motion`, `Executor`).

### Naprawione

- **Obrót i przesunięcie boczne w RC miały odwrotne znaki.** `send_rc_control(0, 30, 0, 30)`
  obracało drona w prawo (`get_yaw()` rósł), ale tor szedł na **+y** (w lewo) -
  fizycznie niespójnie z `send_rc_control(30, 0, 0, 0)`, które szło na −y.
  Przyczyna: `rc_motion` przeliczał `yaw` RC (CW+) bez zmiany znaku, a
  `integrate_rc` traktuje kurs matematycznie (CCW+). Teraz `rc_motion` neguje
  `yaw_rate`, a `Executor._rc_for_sample` neguje `yaw_rate` planu (CCW+ -> CW+),
  więc obie ścieżki dają tę samą stronę.
- **`get_yaw()` zwracał kurs w konwencji wewnętrznej**, nie Tello. Teraz, na
  granicy API, znak jest odwracany: `rotate_clockwise(90)` -> `+90`,
  `rotate_counter_clockwise(90)` -> `-90`, a skręt w prawo (`yaw > 0` w RC)
  zwiększa `get_yaw()` - zgodnie z opisem w README.

### Dodane

- Sekcja **„Układ współrzędnych”** w README - jedno źródło prawdy dla osi,
  znaków RC/`get_yaw()` i transformacji widoku 3D.
- `tests/test_coordinate_system.py` - testy **fizyczne**, niezależne od
  biblioteki: ruch w prawo = −y, skręt w prawo = ta sama strona, `rotate_*` +
  `move_forward`, zgodność `move_*` / `go_xyz_speed` z układem, spójność
  strony ruchu i skrętu.
- `tests/test_scene_coordinates.mjs` - test transformacji sceny: punkt po prawej
  stronie drona (−y) jest rysowany po prawej stronie ekranu, gdy kamera patrzy
  od tyłu wzdłuż +X (uruchamiany też z pytest).
- Testy w `test_dronemoves_integration.py`: `turn(+90)` = w lewo (+y),
  `circle(direction="right")` w całości po prawej stronie kursu startowego.

### Sprawdzone liczbowo (symulator, czysty djitellopy)

| Operacja | Wynik |
|---|---|
| `send_rc_control(+30, 0, 0, 0)` 2 s | `(0, −30)` - prawo = −y |
| `send_rc_control(0, +30, 0, +30)` 3 s | `(31.4, −26.9)`, `get_yaw() = 81` - skręt i tor w prawo |
| `rotate_clockwise(90)` + `move_forward(100)` | `(0, −100)`, `get_yaw() = +90` |
| `rotate_counter_clockwise(90)` + `move_forward(100)` | `(0, +100)`, `get_yaw() = −90` |
| `dronemoves.turn(90)` | `(+60, +60)` - w lewo (zgodnie z planerem) |
| `dronemoves.circle(direction="right")` | `y ∈ [−120, 0]` - całość po prawej |

## [0.1.2] - 2026-10-21

Symulator testuje teraz **dokładnie tę ścieżkę sterowania, co prawdziwy dron**.

### Zmienione

- **Domyślnie tylko `send_rc_control`.** `Executor` wysyła wychylenia RC zawsze;
  diagnostyczny kanał dokładnych prędkości (`send_dronemoves_profile`, dostępny
  tylko w mocku symulatora) jest **wyłączony domyślnie** i włącza się go
  świadomie przez `Pilot(..., sim_exact=True)`. Wcześniej symulator omijał
  `send_rc_control`, więc ścieżka używana na prawdziwym Tello nie była testowana.
- **Profil kalibracji importowany z biblioteki.** Symulator nie ma już własnej
  kopii wzorów - silnik (`app/sim/core.py`) bierze `dronemoves.calibration.
  CalibrationProfile` (jedno źródło prawdy, import jednokierunkowy `app` ->
  `dronemoves`; biblioteka nie wie nic o symulatorze).

### Naprawione

- **Obrót prędkości do układu drona.** Prędkości w trajektorii są globalne
  (`vx`, `vy` liczone jako różnice pozycji), więc `Executor` rzutuje je na osie
  drona bieżącym kursem (`przód = vx·cos + vy·sin`, `prawo = vx·sin − vy·cos`)
  i dopiero potem zamienia na RC. Wcześniej do `send_rc_control` trafiały
  **wychylenia RC** zamiast prędkości, bez obrotu - manewry łukowe wypadały
  poza trasę (np. `turn(90)` kończył 120 cm od celu).
- **Znaki zgodne z djitellopy.** `lr > 0` = w prawo, `yaw > 0` = obrót w prawo
  (zgodnie z zegarem); `rotate_counter_clockwise` zwiększa `get_yaw()`.
- **Czas kroku RC wymuszony.** `integrate_rc` ustawia `duration_override =
  seconds`; wcześniej czas liczono z `długość / prędkość`, więc przy małych
  prędkościach (kwantyzacja RC) symulacja rozjeżdżała się z zegarem i pętla
  wykonawcza manewru nie kończyła się (manewr `orbit` przekraczał limit 60 s).
- **`orbit` startuje z bieżącego kursu.** Nowy `TrajectoryBuilder.rotate()`
  dodaje obrót w miejscu przed łukiem; wcześniej pierwsza próbka planu miała
  już kurs „nos w środek”, którego dron nie miał jak wykonać (90° błędu).
- **Zrzuty stanu do JSONL ograniczone czasem** (`SNAPSHOT_EVERY_S`). Zapis
  całej telemetrii po każdej komendzie dawał narzut O(n²): `orbit` (252 komendy
  RC) zapisywał setki megabajtów JSON.
- **`Pilot.path()` startuje z `(0, 0, z)`**, a nie z pierwszego punktu listy -
  dron nie „teleportuje się” o odległość do pierwszego punktu.

### Zgodność symulator <-> biblioteka (ścieżka RC, speed=35)

Końcowa pozycja z telemetrii vs `pilot.position()`; tolerancja testu
**15 cm / 8°** (kwantyzacja wychyleń do liczb całkowitych):

| Manewr | Odchylenie pozycji | Odchylenie kursu |
|---|---|---|
| `forward(100)` | 0,1 cm | 0,0° |
| `turn(±90, r=60)` | 1,5 cm | 0,4° |
| `arc(180, r=100)` | 7,4 cm | 2,3° |
| `arc(-120, r=80)` | 1,4 cm | 0,5° |
| `circle(60, left/right)` | 1,3 cm | 1,3° |
| `orbit(60, 1)` | 1,3 cm | 2,2° |
| `slalom(3, 70, 40)` | 11,3 cm | 0,6° |
| `figure_eight(60)` | 2,9 cm | 4,8° |
| `spiral(50, 60, 3)` | 0,4 cm | 0,5° |
| `path(3D)` | 5,7 cm | 1,5° |

### Dodane

- `Pilot(..., sim_exact=True)` - diagnostyczny kanał prędkości (opis w README).
- `TrajectoryBuilder.rotate(angle_deg)` - obrót w miejscu w planie.
- Testy: 12 manewrów przez ścieżkę RC, test „tylko `send_rc_control`” oraz
  test wykrywający odwróconą oś boczną / brak obrotu prędkości do układu drona.

## [0.1.1] - 2026-10-21

Poprawki zgodności z symulatorem i z rzeczywistym `djitellopy` (znaki RC).

### Naprawione

- **Znaki RC zgodne z djitellopy/Tello.** `send_rc_control(left_right, ...,
  yaw)` przyjmuje `left_right > 0` = **w prawo** i `yaw > 0` = obrót **w prawo**
  (zgodnie z zegarem, tak rośnie `get_yaw()`) - potwierdzone w oficjalnym
  przykładzie `examples/manual-control-pygame.py` (`K_RIGHT -> +S`,
  `K_d -> +S`). `TelloBackend` odwraca teraz obie osie boczne: wewnętrzna
  konwencja biblioteki (`vy > 0` = w lewo, `yaw_rate > 0` = CCW) jest
  tłumaczona na konwencję djitellopy.
- **Executor używa zegara z chwili wywołania.** Domyślne argumenty `time_fn` /
  `sleep_fn` były wiązane przy imporcie, więc w symulatorze (gdzie `time.sleep`
  i `time.monotonic` są podmieniane na zegar wirtualny) pętla RC mijała się
  z czasem symulacji: biblioteka „przeskakiwała” po trajektorii, a dron
  pokonywał tylko ułamek manewru. Teraz `Executor` woła `time.sleep` /
  `time.monotonic` leniwie, więc oba zegary są wspólne (1:1).
- **Ruch RC wykonywany według profilu kalibracji.** `Executor` przekazuje do
  symulatora dokładne prędkości próbki (cm/s, °/s) przez opcjonalne
  `send_profile` (mock ma `send_dronemoves_profile`; prawdziwe `djitellopy`
  nie - tam sterowanie idzie wychyleniami RC). Symulator nie przelicza
  wychyleń drugi raz i całkuje ruch krokami <= 50 ms w układzie drona
  obracanym w trakcie, więc łuki są zgodne z planem.
- **`path()` startuje z miejsca, gdzie dron jest.** Lista punktów jest
  „względna od startu manewru”, ale pierwszy punkt bywał oddalony (np.
  `(80, 0, 0)`) - planer zaczynał trajektorię skokiem o tę odległość, więc dron
  „teleportował się” w pierwszych 50 ms, a reszta manewru wypadała poza trasą.
  `Pilot.path()` dokłada punkt `(0, 0, z)` na początku trasy.
- **`Pilot.yaw` normalizowany do `0..360`** po manewrze - wcześniej `orbit`
  zostawiał `270.0` tam, gdzie `get_yaw()` zwracałby `-90`.
- **`trajectory.with_rc()`** uzupełnia wychylenia w kolejności
  `(fb, lr, ud, yaw)` zgodnej z `Executor` (wcześniej dwie pierwsze wartości
  były zamienione, co dla `mode="native"` dawało błędne RC).

### Dodane

- `MotionBackend.send_profile()` (domyślnie `False`) - opcjonalny kanał
  dokładnych prędkości dla symulatora.
- `TelloBackend.send_profile()` - przekazuje profil, jeśli dron go udostępnia.

### Zgodność ruchu symulator <-> biblioteka

Po poprawkach końcowa pozycja manewru (runner symulatora vs `pilot.position()`)
zgadza się w granicach **0,2 cm** i **0,1°** dla `forward`, `turn` (±),
`arc` (±), `circle` (left/right), `orbit`, `slalom`, `figure_eight`, `spiral`
i `path` (3D).

## [0.1.0] - 2026-10-20

Pierwsze wydanie.

### Dodane

- `Pilot` - wysokopoziomowe API manewrów z blokiem `with` (bezpieczne
  zatrzymanie i lądowanie przy wyjątku).
- Manewry: `forward`, `turn`, `arc`, `circle`, `orbit`, `slalom`,
  `figure_eight`, `spiral`, `path`, `hover`, `sequence`.
- `MotionBackend` + `TelloBackend` (djitellopy jako opcjonalne rozszerzenie
  `dronemoves[tello]`).
- `CalibrationProfile` - przelicznik RC na cm/s i °/s, zapis/odczyt JSON.
- Planer trajektorii z profilem trapezowym i wygładzaniem kąta nosa.
- Executor 20 Hz z korektą czasu rzeczywistego (bez dryfu).
- Walidacja parametrów przed startem manewru (czytelne `PathError`).
- Limity bezpieczeństwa: wysokość, promień od startu, bateria.
- `preview()` - zaplanowany tor bez lotu.
- Integracja z symulatorem przez opcjonalne `annotate()`.
- Testy oparte na `FakeDrone` (bez djitellopy i symulatora).
