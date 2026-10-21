# Zmiany w dronemoves

Forma zgodna z [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie zgodne z [SemVer](https://semver.org/lang/pl/).

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
