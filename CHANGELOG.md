# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/); wersjonowanie
zgodne z [SemVer](https://semver.org/lang/pl/).

## [0.3.0] - 2026-10-25

> Wszystkie prace z 22-25.10.2026 (wcześniej trzy sekcje „Niewydane”) są częścią wydania 0.3.0.

### Dodane

* **Paczka „rozpakuj i uruchom” dla Windows** (`release_tools/build_portable.py`):
  buduje `DroneSim-portable-<wersja>-win64.zip` z **oficjalnym Pythonem
  embeddable 3.11.9** (ostatnie 3.11 z plikami binarnymi) pobranym z python.org
  i zweryfikowanym (SHA-256 przypięty + krzyżowo MD5 z python.org), z
  zainstalowanymi zależnościami runtime, `dronemoves`, aplikacją, przykładami,
  scenami, poradnikiem i `start.bat` używającym wbudowanego Pythona (nic nie
  instaluje w systemie). `verify_zip` pilnuje, żeby w paczce nie było `.git`,
  `.venv`, `tmp`, `flights`, `scenes/user`, `.pyc` ani ścieżek z nazwą
  użytkownika. Paczka: 20,8 MB, budowa 24 s,
* **`release_tools/smoke_portable.py`**: test dymny paczki (rozpakowanie, start na
  wolnym porcie, `/api/health`, `basic_square.py`, skrypt `dronemoves`) używany
  lokalnie i w CI,
* **`.github/workflows/release.yml`**: wydanie uruchamiane **tylko** po pushu
  tagu `v*` - buduje paczkę na `windows-latest`, sprawdza zgodność tagu z
  `app/__init__.py`, robi test dymny i tworzy GitHub Release z ZIP-em oraz
  notatkami z `CHANGELOG.md` (`release_tools/changelog_notes.py`),
* **Lot ręczny (wtyczka `manual_flight`, wyłączalna)**: sterowanie klawiaturą na
  żywo (strzałki, W/S, A/D - jak w `manual-control-pygame.py`), ściągawka
  klawiszy, suwak prędkości, ruch w 3D i ostrzeżenia o zbliżeniu do przeszkód.
  Fizyka liczona po stronie serwera tą samą klasą `Simulation`, więc nagranie
  odtwarza się w skrypcie 1:1,
* **Nagrywanie lotu ręcznego → skrypt** w dwóch wariantach: (a) wierne
  odtworzenie `send_rc_control` + `time.sleep` (zgodność ≤ 5 cm w punktach
  kontrolnych), (b) uproszczone `move_*`/`rotate_*` z limitami Tello 20-500 cm
  i 1-360° (≤ 20 cm w punktach zatrzymań). Test: nagranie → skrypt →
  symulator → porównanie torów,
* **Edytor CodeMirror 6** (`app/static/vendor/codemirror`, bundle 402 kB, MIT,
  bez CDN): kolorowanie Pythona, numery linii, podświetlanie wykonywanej linii.
  Ukryta `textarea` pozostaje źródłem wartości, więc cały dotychczasowy kod
  działa bez zmian,
* **Podpowiedzi generowane z kodu** (`GET /api/completions`): 72 metody mocka
  `djitellopy` i 24 metody `dronemoves` z sygnaturami (`inspect.signature`)
  i pierwszym akapitem docstringa - bez ręcznej listy,
* **Statyczna analiza skryptu** (`POST /api/check`, `ast` bez wykonywania kodu):
  błąd składni z linią, stałe poza zakresem Tello, ruch przed `takeoff()` w
  prostym przepływie, brak `land()` - jako ostrzeżenia z podkreśleniem linii
  (nie blokują uruchomienia),
* **Import lotu rzeczywistego i porównanie** (`app/realflight.py`): wgranie
  pliku z `dronemoves.FlightRecorder` w Historii, raport odchyłek
  (maks./średnia/p95/końcowa) z rozkładem na składową wzdłuż toru, w bok i w
  pionie oraz konkretne podpowiedzi kalibracji; oba tory na jednej scenie 3D,
* dokumentacja: sekcje o paczce, edytorze, locie ręcznym i porównaniu w README
  i poradniku (rozdziały 9-11), nowe zrzuty `10-lot-reczny.png`,
  `11-edytor-ostrzezenia.png`, `12-porownanie.png`,
* **Testy losowe lotów** (`tests/test_random_flights.py`): generator z ziarnem
  (`random.Random(seed)`, seed w nazwie przypadku) buduje sekwencje 1-6 manewrów
  `dronemoves` z losowym kursem startowym. Kryteria liczone z geometrii:
  `pilot.position()` vs symulator ≤ 15 cm i kurs ≤ 5°, `return_home` ≤ 10 cm,
  limity zawsze z wyjątkiem `PathError`/`SafetyError`. Wariant szybki (20 lotów
  + 5 tras planera) w zwykłym zestawie, pełny (200 + 100) pod markerem `slow`
  i w osobnym jobie CI uruchamianym z przycisku. Wynik pełnego przebiegu:
  300/300 bez błędu,
* **Maty Tello EDU (Mission Pads)**: nowy typ obiektu `mission_pad` (numer 1-8,
  pozycja, obrót) w edytorze przeszkód i w formacie sceny; wykrywanie w mocku
  (`enable_mission_pads`, `get_mission_pad_id`, `get_mission_pad_distance_x/y/z`,
  `set_mission_pad_detection_direction`) oraz loty względem maty
  (`go_xyz_speed_mid`, `curve_xyz_speed_mid`, `go_xyz_speed_yaw_mid`);
  scena `mission_pads` (4 maty) i `examples/mission_pads_demo.py`. Zasięg
  wykrywania (30 cm od środka, 30-120 cm wysokości) to **założenie modelu**,
  opisane w README i `app/features/obstacles/mission_pads.py`,
* **Tryb realistyczny symulatora** (przełącznik „Realizm: idealny /
  realistyczny” + seed, zapis w `localStorage`): dryf poziomy 2-6 cm/s, szum
  wysokości ±2 cm i kursu ±1,5°, opóźnienie RC 100 ms, niedokładność `move_*`
  ±5 %. Domyślnie **wyłączony** - tryb idealny liczy lot bit w bit jak dotąd
  (`test_ideal_mode_is_unchanged`). Zmierzone: `return_home` 2,9-11,3 cm
  (średnio 7,8 cm) w trybie realistycznym,
* **Kamera „Z drona (FPV)”**: kamera w nosie modelu, pole widzenia 82,6°
  (specyfikacja Tello), działa przy odtwarzaniu i przewijaniu; test
  przeglądarkowy `test_fpv_camera_follows_drone`,
* dokumentacja: sekcje o matach, trybie realistycznym i FPV w README i poradniku,
  nowe zrzuty `07-mission-pady.png`, `08-realizm.png`, `09-fpv.png`.
* **Planer trasy** (funkcja `route_planner`, punkt rozszerzeń nr 1): zakładka
  „Planer” z listą punktów (X/Y/Z, kurs nosa, kolejność, wstawianie, usuwanie),
  podglądem na żywo (dystans, czas, bateria, problemy z limitów i kolizji),
  generowaniem skryptu („prosta” = djitellopy, „płynna” = dronemoves,
  oznaczona jako **eksperymentalna**), kopiowaniem, pobieraniem `.py`
  i wczytywaniem trasy z bloku `dronesim-route`,
* trasa jest zapisywana w locie (`options.route_planner.route`) i może być
  zapisana razem ze sceną (pole `routes`),
* ostrzeżenie „tryb płynny: odchylenie do X cm od punktów”, gdy odchylenie
  przekracza 15 cm (zamiast blokowania generowania),
* `docs/route_planner.png` i sekcja „Planer trasy” w README z przykładami
  kodu w obu trybach.
* **stopka aplikacji** „Development by Vardeex” na samym dole okna (własny,
  24 px pasek pod `#app`, poza sceną 3D, osią czasu i panelami; nie nachodzi
  na żaden z nich także po przełączeniu zakładki - sprawdzone zrzutami
  przy szerokości 1280 i 1920 px),
* słowo „Vardeex” to link `mailto:vardeex.exe@gmail.com` z tematem
  „Drone Script Simulator” i podpowiedzią „Kontakt: vardeex.exe@gmail.com”;
  w spoczynku stopka jest stonowana (kolor `--muted`, 10,5 px), po najechaniu
  „Vardeex” podświetla się kolorem akcentu,
* sekcja **Autor** w `README.md` (Vardeex, e-mail, GitHub),
* odświeżony `docs/screenshot.png` (1600×950) - stopka jest na nim widoczna.

### Zmienione

* **Kamera „Śledząca”** to teraz kamera pościgowa **z tyłu** drona (wcześniej
  trzymała kąt z boku) - dzięki temu prawo drona = prawo ekranu, co jest
  potrzebne do sterowania klawiaturą,
* historia lotów pokazuje źródło lotu (`sim`/`real`) i oznacza loty rzeczywiste.

### Naprawione

* **Zawieszanie testów w CI**: sprzątanie serwera w testach nie zabija już grupy
  procesów pytest (`start_new_session` na POSIX, `kill_tree` z kontrolą grupy),
  `watch_battery` ma ograniczony czas blokady zamiast czekać w nieskończoność,
  a `communicate()` po timeoucie nie wisi; `pytest.ini` ma
  `faulthandler_timeout = 60`, joby CI - `timeout-minutes` i `--durations=20`,
* **Tryb „płynna” dla długich tras (KI-7)**: trasa „dluga 600 cm” z powrotem do
  startu kończyła się `RouteError` już w generatorze. Teraz odcinki dłuższe niż
  400 cm są dzielone na punkty pośrednie w tym samym wywołaniu `path`,
  `max_radius_cm` pilota pokrywa najdalszy punkt, a powrót robi
  `pilot.return_home()`. Zmierzone: punkty 0,1 / 0,7 cm, powrót 0,5 cm.
  Usunięty jedyny celowy `xfail` testu konformacji (krótkie trasy generują
  identyczny kod jak wcześniej - `test_short_route_is_unchanged`).
* testy funkcji przeszkód nie zakładają już stałej listy funkcji
  (`test_obstacles_feature_off`) - sprawdzają tylko, że `obstacles` jest
  wyłączone, a reszta aplikacji działa,
* `Planer.path` (dronemoves 0.1.5) startuje w miejscu drona i realnie się
  wznosi (szczegóły w `lib/dronemoves/CHANGELOG.md`).

## [0.2.2] - 2026-10-21

### Naprawione

* **kolizje z belkami bramek**: `_gate_distance` przekazywał do
  `_gate_bar_distance` **wysokość bezwzględną** (`z`), a funkcja oczekuje
  wartości liczonej od środka ramy (`v = z - gate.position[2]`). Skutki na
  `gate_slalom.json` (bramka 1: środek `z = 80`, rama `z: 20-140`,
  otwór `z: 35-125`): dron w środku górnej belki `(150, 0, 135)` dostawał
  72,5 cm zamiast 0, lot `move_up(55)` + `move_forward(200)` przechodził przez
  belkę bez kolizji, a przelot środkiem otworu dawał 17,5 cm i 6 fałszywych
  ostrzeżeń zamiast luzu 40 cm,
* **brak kolizji przy dotknięciu belki**: kolizja z ramą była rozpoznawana
  tylko przy przelocie „przez płaszczyznę”, a nie przy zetknięciu; teraz
  wejście w belkę to kolizja (jeden wpis na wejście, jak przy bryłach),
* zły nawias przy dronie w połowie wysokości ramy (płaszczyzna ramy wewnątrz
  bryły drona) dawał urojone 0,5 cm zamiast 0,
* dwa wpisy kolizji dla jednego zdarzenia (zetknięcie z belką + „nie zmieścił
  się w otworze”) - teraz jeden,
* `_interpolate` nie interpolował odcinków o zerowym czasie (początek
  lądowania), więc trasa „skakała” przez ramę,
* `examples/obstacles_demo.py`: zjazdy w bok tuż za ramą (20 cm) realnie
  zbliżały bryłę drona do ramki (12,5 cm), a lądowanie wypadało w płaszczyźnie
  bramki 3 (przelot przez belkę dolną). Slalom kończy się teraz 40 cm za ramą
  i 50 cm przed zjazdami - wynik: 3/3 bramki, 0 kolizji, 0 ostrzeżeń.

### Zmienione

* dla drona w otworze bramki odległość to **luz** do najbliższej krawędzi
  (`min(otwór/2 - |u|, otwór/2 - |v|)`), np. 40 cm w środku otworu 90 × 90,
* ostrzeżenia o zbliżeniu do ramy pokazują luz i brakujący zapas,
* testy odległości bramek liczą oczekiwane wartości **ręcznie z geometrii**
  (komentarz przy każdej asercji), m.in. `(150, 0, 80)` → 40 cm,
  `(150, 0, 135)` → 0, `(150, 0, 30)` → 0, `(150, 55, 80)` → 0,
  `(150, 0, 150)` → 7,5 cm, lot przez górną belkę → kolizja,
* `docs/obstacles.png` zaktualizowany (slalom bez fałszywych ostrzeżeń,
  min. odstęp 32,5 cm).

## [0.2.1] - 2026-10-21

### Naprawione

* **odległość od bramki** (`min_distance_cm`, ostrzeżenia): liczona do czterech
  belek ramy zamiast do płaszczyzny bramki. Wcześniej lot 140 cm przed bramką
  i przelot przez środek otworu dawały ok. 2,5 cm oraz fałszywe „zbliżenie”
  / „kolizję” z ramą, przez którą dron tylko przelatywał,
* ostrzeżenia o zbliżeniu do ramy bramki pokazują rzeczywisty odstęp od belek
  („15.0 cm od belek, brakuje 5.0 cm do marginesu…”), a występ przed ramą
  i za nią to dwa osobne wpisy,
* panel „Przeszkody” nie wczytywał się (`Identifier 'layer' has already been
  declared`, brak `getLayer`), przez co zakładka pozostawała ukryta,
* etykiety znaczników („Kolizja”/„Zbliżenie”/„Bramka”) są ukrywane razem
  z etykietami nazw (ustawienie „etykiety”).

### Dodane

* `scene.frameFlight()` / `scene.topDownFlight()` - punkty rozszerzeń kamery;
  przycisk „Dopasuj” w trybie swobodnym kadruje trasę bez zmiany kierunku
  patrzenia (README, „Punkty rozszerzeń”, punkt 5),
* zrzut `docs/obstacles.png` robiony w przeglądarce (Playwright, 1600 × 950):
  scena „Slalom z bramkami”, lot `examples/obstacles_demo.py`, trasa przez
  bramki i otwarty panel „Przeszkody”; obraz sprawdzany programowo (różnorodność
  kolorów), więc nie może być pustym kadrem,
* testy odległości do ramy bramki (140 cm przed bramką, środek otworu,
  przejście obok ramy, przelot „na wylot” przez płaszczyznę) - tolerancja ±3 cm.

## [0.2.0] - 2026-10-21

### Dodane

* **Przeszkody 3D** (funkcja dodatkowa, wyłączalna): edytor scen w UI
  (dodawanie, przesuwanie myszą i polami X/Y/Z, skalowanie, obrót, duplikowanie,
  usuwanie; typy: prostopadłościan, walec, bramka, płaszczyzna),
* tryby widoku przeszkód (półprzezroczyste / pełne / ukryte) + etykiety,
* scena zapisywana w JSON: przykładowe w `scenes/`, użytkownika w `scenes/user/`
  (poza repo); lista scen, zapis, „zapisz jako”, nowa pusta scena, usuwanie,
* trzy przykładowe sceny: pokój 4 × 4 × 2,5 m z meblami, slalom z bramkami,
  tor przeszkód,
* wykrywanie kolizji po całej telemetrii (próbkowanie trasy co 1 cm między
  próbkami), margines bezpieczeństwa (domyślnie 20 cm), zbliżenia, zaliczanie
  przelotów przez bramki; znaczniki na trasie i lista problemów z czasem,
  nazwą przeszkody oraz linią skryptu,
* opcja „zatrzymaj odtwarzanie przy kolizji”, statystyki lotu (kolizje,
  ostrzeżenia, bramki, minimalny odstęp),
* scena zapisywana razem z lotem - wczytanie lotu z historii przywraca
  te same przeszkody i raport,
* przykłady `examples/obstacles_demo.py` i `examples/obstacles_crash.py`,
* **architektura pod wtyczki**: katalog `app/features/` z manifestami, rejestr
  funkcji, hook „po symulacji”, `GET /api/features` i dynamiczne ładowanie
  paneli/warstw sceny w UI (README: „Punkty rozszerzeń”),
* `config.json` - włączanie/wyłączanie funkcji jednym ustawieniem.

### Zmienione

* `POST /api/run` przyjmuje opcjonalne `options` (przekazywane do hooków po
  zapisie lotu); `GET /api/flights/{id}` zwraca dodatkowo `scene` i `obstacles`,
* `app/storage.py`: `save(..., options=...)` i rejestr hooków po zapisie.

## [0.1.x]

Wcześniejsze wersje - patrz `git log`.

