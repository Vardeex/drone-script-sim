# Drone Script Simulator

> **Status: prototyp / wersja rozwojowa.** Model 3D drona jest w trakcie dopracowania,
> biblioteka `dronemoves` była testowana tylko w symulacji, a parametry sterowania RC
> to założenia, nie pomiary z prawdziwego drona.

Lokalna aplikacja do **testowania skryptów sterujących dronem bez drona**.
Wgrywasz skrypt Pythona (na razie dla DJI Tello przez `djitellopy`), aplikacja
uruchamia go w sandboxie (symulacja, bez łączenia z siecią) i pokazuje w 3D
lot, trasę, telemetrię, komendy, błędy i ostrzeżenia.

![Zrzut ekranu aplikacji](docs/screenshot.png)

## Funkcje

* wgrywanie skryptów `.py` (plik, edytor w przeglądarce, przykłady),
* uruchamianie w **osobnym procesie** z podstawionym **mockiem `djitellopy`**,
  blokadą sieci, wirtualnym zegarem i limitem czasu (60 s),
* model 3D quadcoptera (korpus, 4 ramiona, wirniki), podłoże z siatką 1 m,
  osie X/Y/Z, punkt startu,
* trasa kolorowana wysokością + legenda, pionowe linie wysokości,
  znaczniki każdej komendy z numerem i dymkiem (komenda, argumenty, pozycja,
  wysokość, yaw, bateria, czas, linia skryptu),
* odtwarzanie: play/pauza, suwak czasu, prędkość 0.25x–8x,
  poprzednia/następna komenda, kamery: swobodna / śledząca / z góry,
* panel boczny: tabela komend (klik = skok w czasie), telemetria na żywo,
  konsola stdout/stderr, lista błędów i ostrzeżeń z numerem linii,
  statystyki lotu (czas, dystans, maks. wysokość, zużycie baterii),
* podgląd skryptu z podświetleniem aktualnie wykonywanej linii,
* zapis/wczytanie lotu (JSON), eksport telemetrii do CSV, historia lotów,
* interfejs w języku polskim, działa offline (three.js jest lokalnie),
* **przeszkody 3D** (funkcja dodatkowa, wyłączalna): edytor scen, kolizje
  i zbliżenia liczone na całej telemetrii, przeloty przez bramki - patrz
  „Przeszkody 3D” niżej.

## Przeszkody 3D

Funkcja pokazuje, czy skrypt **rozbiłby drona**: rysuje przeszkody w scenie,
sprawdza cały lot i oznacza kolizje, zbliżenia poniżej marginesu oraz
zaliczone przeloty przez bramki. Przeszkody **nie zmieniają przebiegu
symulacji** - dron się nie odbija i nie zatrzymuje; symulator ma pokazać, że
skrypt by się rozbił, a nie poprawiać lot.

![Przeszkody w symulatorze](docs/obstacles.png)

### Jak używać edytora

Zakładka **Przeszkody** w panelu po prawej (jest tylko wtedy, gdy funkcja jest
włączona):

1. Wybierz scenę z listy (przykładowe z `scenes/` albo własne z `scenes/user/`),
   albo „✚ Nowa” (pusta scena 4 × 4 × 2,5 m).
2. Dodaj przeszkody: **▭ Ściana** (prostopadłościan), **◍ Słup** (walec),
   **⌸ Bramka** (rama do przelotu), **▬ Sufit** (płaszczyzna - tylko widok).
3. Zaznacz przeszkodę na liście lub kliknij ją w scenie 3D i ustaw nazwę,
   pozycję X/Y/Z, wymiary, obrót (wokół osi pionowej) oraz - dla bramki -
   otwór. Obok pól widać wymiary i **odległość od punktu startu**.
4. Tryb **edycja (przeciąganie)** pozwala przesuwać przeszkody myszą po
   podłożu; „⧉ Duplikuj” / „🗑 Usuń” działają na zaznaczonej przeszkodzie.
5. Widok przeszkód: **półprzezroczyste / pełne / ukryte** + etykiety nazw.
6. **Margines** (domyślnie 20 cm) i „zatrzymaj odtwarzanie przy kolizji”
   są zapamiętywane w przeglądarce.
7. „💾 Zapisz” zapisuje scenę do `scenes/user/<nazwa>.json` (katalog poza
   repozytorium); „💾 Zapisz jako” tworzy nową scenę.

Wybrana scena jest **zapisywana razem z lotem**, więc po wczytaniu lotu
z historii wracają te same przeszkody, znaczniki i lista problemów.

### Wykrywanie kolizji

* dron to prostopadłościan **10 × 10 × 5 cm** obracany kursem,
* do każdej przeszkody dodawany jest **margines bezpieczeństwa** (domyślnie 20 cm),
* sprawdzana jest cała telemetria; między próbkami trasa jest próbkowana
  co 1 cm, żeby szybki przelot nie „przeskoczył” cienkiej ściany,
* **kolizja** - dron dotyka przeszkody: czerwony znacznik na trasie i wpis
  na liście problemów (czas, przeszkoda, komenda i linia skryptu),
* **zbliżenie** - odstęp mniejszy niż margines: żółty znacznik i wpis,
* **odległość od bramki** mierzona jest do **belek ramy** (nie do płaszczyzny
  bramki): przelot przez środek otworu 90 × 90 cm to 40 cm luzu (do krawędzi
  otworu), dron 140 cm przed bramką ma ~139 cm do ramy (najbliższy wierzchołek
  górnej belki), a 10 cm nad ramą dokładnie 7,5 cm. Samo przejście przez
  płaszczyznę ramy nie jest kolizją ani zbliżeniem - liczy się dotknięcie belki,
* **bramka** - zaliczona, gdy dron przeleciał przez płaszczyznę ramy w całości
  w otworze (z 2 cm zapasu od ramy); zahaczenie o ramę to kolizja,
* statystyki lotu: liczba kolizji, ostrzeżeń, zaliczonych bramek i minimalny
  odstęp od przeszkody (dla bramki - od belek ramy).

### Format JSON sceny (`scenes/*.json`)

```json
{
  "format": "dronesim-scene",
  "version": 1,
  "name": "Slalom z bramkami",
  "description": "Trzy bramki 90 x 90 cm",
  "room": [600, 400, 250],
  "obstacles": [
    {
      "id": "gate-1",
      "kind": "gate",
      "name": "Bramka 1 (środek)",
      "position": [150, 0, 80],
      "size": [120, 5, 120],
      "opening": [90, 90],
      "thickness": 5,
      "yaw_deg": 0
    }
  ]
}
```

| Pole | Znaczenie |
|---|---|
| `kind` | `box` (prostopadłościan), `cylinder` (walec), `gate` (bramka), `plane` (płaszczyzna - tylko widok) |
| `position` | środek bryły `[x, y, z]` w cm (dla bramki płaszczyzna ramy jest w `x, y`) |
| `size` | wymiary `[x, y, z]` w cm; dla walca `size[0]` = średnica, `size[2]` = wysokość |
| `opening` | otwór bramki `[szerokość, wysokość]` w cm |
| `thickness` | grubość ramy bramki / płaszczyzny w cm |
| `yaw_deg` | obrót wokół osi pionowej, **dodatni = w prawo** (konwencja Tello) |
| `room` | opcjonalne wymiary pomieszczenia `[x, y, z]` w cm (informacyjnie) |

Przykładowe sceny w repozytorium: `room_with_furniture` (pokój 4 × 4 × 2,5 m
z meblami), `gate_slalom` (slalom z bramkami), `obstacle_course` (tor przeszkód).

### Przykłady

| Plik | Co pokazuje | Wynik |
|---|---|---|
| `examples/obstacles_demo.py` | slalom przez 3 bramki (scena `gate_slalom`) | 3/3 bramki, 0 kolizji, 0 ostrzeżeń |
| `examples/obstacles_crash.py` | za mały zjazd w bok przed bramką 2 | kolizja z ramą bramki 2 |

## Planer trasy

Zakładka **Planer** (funkcja `route_planner`, włączana w `config.json`) pozwala
zbudować trasę z punktów i wygenerować gotowy skrypt.

* **Dodawanie punktów** - przycisk „✚ Dodaj punkt” (kolejny punkt 100 cm dalej)
  albo tryb „Klik na podłożu” (klik w scenie 3D). Wysokość nowego punktu
  dziedziczy poprzedni punkt, startowo 100 cm.
* **Lista punktów** - edycja X/Y/Z w cm, kurs nosa w punkcie (`po torze`,
  `stały kurs`, `na punkt`, `na start`), zmiana kolejności (↑/↓), wstawianie
  (✚), usuwanie (✕), zaznaczanie i przeciąganie w scenie 3D
  (Shift + przeciąganie = wysokość).
* **Podgląd na żywo** - po każdej zmianie panel pokazuje dystans, czas lotu
  (`eta_s`), zużycie baterii i listę problemów (limity Tello, kolizje z
  przeszkodami z aktywnej sceny).
* **Generowanie** - „▶ Wygeneruj i uruchom” (kod trafia do edytora i startuje
  symulację), „⌨ Pokaż kod”, „📋 Kopiuj kod”, „💾 Pobierz .py”,
  „📥 Wczytaj ze skryptu” (trasa zapisana w bloku `dronesim-route`).

### Tryby generowania

| Tryb | Biblioteka | Charakterystyka |
|---|---|---|
| **Prosta** (domyślny) | `djitellopy` | `go_xyz_speed` + `rotate_*`; dokładny, przewidywalny |
| **Płynna** (eksperymentalny) | `dronemoves` | `pilot.path(smooth=True)`; gładkie łuki, ale może odstawać od punktów |

Tryb „płynna” jest oznaczony w UI jako **eksperymentalny**. Zmierzone
odchylenie od punktów: kwadrat 3,6 cm, wokół przeszkody 13,7 cm,
obroty 10,3 cm, „za plecami” 120 cm (znany problem KI-1 w `KNOWN_ISSUES.md`).
Gdy odchylenie przekracza 15 cm, panel pokazuje ostrzeżenie
„tryb płynny: odchylenie do X cm od punktów” - generowanie nie jest blokowane.

### Przykład: trasa w trybie „prosta”

```python
from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()

tello.go_xyz_speed(100, 0, 20, 50)      # punkt 1: 100 cm przód, 20 cm wyżej
tello.rotate_clockwise(90)
tello.go_xyz_speed(100, 0, 0, 50)       # punkt 2: 100 cm po nowym kursie
tello.land()
```

### Przykład: ta sama trasa w trybie „płynna”

```python
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()                          # dron na 80 cm

with Pilot(tello, speed=50, max_height_cm=500, max_radius_cm=500) as pilot:
    # punkty WZGLĘDNE wobec pozycji drona (0, 0, 0 = tu, gdzie jestem)
    pilot.path([(100, 0, 20), (100, 100, 20)], smooth=True)
tello.land()
```

### Ograniczenia trybu „płynna”

* jedna prędkość na całą trasę (bez prędkości indywidualnych),
* brak „Wróć do startu” (obsługuje tylko tryb „prosta”),
* punkt w innym kierunku niż nos drona na starcie nie jest realizowany
  poprawnie (KI-1) - wstaw obrót albo użyj trybu „prosta”.

## Punkty rozszerzeń

Funkcje dodatkowe (wtyczki) nie są wkompilowane w rdzeń - rdzeń łączy się
z nimi **tylko w tych punktach**:

| # | Punkt | Miejsce w kodzie |
|---|---|---|
| 1 | **Rejestr funkcji**: manifest `app/features/<id>/feature.json` + `router.py` (APIRouter) i `hooks.py`; rdzeń odkrywa funkcje, montuje router pod `api_prefix`, statyki pod `/static/features/<id>` i rejestruje hook | `app/features/registry.py`, wywołanie `_install_features()` w `app/server.py` |
| 2 | **„Po symulacji przeanalizuj lot”**: jeden hook `register_post_save_hook(fn)`; rdzeń woła go po zapisaniu lotu, dostając zapis lotu i opcje uruchomienia | `app/features/<id>/hooks.py` → `app/storage.py` |
| 3 | **Opcje uruchomienia**: pole `options` w `POST /api/run` (i formularz `options` w `/api/upload`) trafia do `storage.save(..., options=...)` i do hooków | `app/server.py` |
| 4 | **UI**: `GET /api/features` zwraca manifesty włączonych funkcji; `boot.js` doładowuje panel (`ui.panel`, rejestracja przez `panels.registerFeaturePanel`), warstwę sceny 3D (`ui.scene_layer`, `scene.addOverlayLayer`) i style (`ui.styles`) | `app/static/js/boot.js`, `app/static/js/panels.js`, `app/static/js/scene.js` |
| 5 | **Kamera na trasę**: `scene.frameFlight()` (kadr na całą trasę bez zmiany kierunku patrzenia) i `scene.topDownFlight()` (widok z góry); przycisk „Dopasuj” używa ich, gdy kamera jest swobodna | `app/static/js/scene.js`, `app/static/js/app.js` |

Rdzeń nie importuje niczego z `app/features/*` poza rejestrem. Funkcję można
**wyłączyć jednym ustawieniem** w `config.json`:

```json
{ "features": { "obstacles": { "enabled": false } } }
```

Wtedy znikają jej endpointy (`/api/obstacles/*` → 404), pliki UI nie są
serwowane, a aplikacja działa normalnie (test: `tests/test_obstacles_feature_off.py`).

## Wymagania

* Windows 10/11
* **Python 3.11 lub nowszy** (aplikacja sama Pythona nie instaluje)
* nowoczesna przeglądarka z WebGL (Edge, Chrome, Opera, Firefox)

## Instalacja

```bat
git clone <adres-repozytorium> DroneSim
cd DroneSim
setup.bat
```

`setup.bat` tworzy środowisko wirtualne `.venv` w katalogu projektu i instaluje
zależności z `requirements.txt` (wersje przypięte). Jeśli `python` nie jest
w `PATH`, wskaż interpreter:

```bat
set PYTHON_EXE=C:\Python311\python.exe
setup.bat
```

Testy:

```bat
.venv\Scripts\python.exe -m pytest
```


## Uruchomienie

```bat
start.bat
```

Skrypt uruchamia serwer `uvicorn` na `http://127.0.0.1:8765` (tylko pętla
lokalna) i otwiera przeglądarkę. Zamknięcie okna konsoli zatrzymuje serwer.

Jeśli port 8765 jest już zajęty (`app/port_busy.py`), `start.bat` **nie
uruchamia drugiego serwera** - tylko otwiera przeglądarkę. Dwa procesy
`uvicorn` na tym samym porcie potrafią serwować różne wersje plików statycznych,
co daje mylące wyniki przy pracy nad modelem 3D.

Ręcznie, z katalogu projektu:

```bat
.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8765
```

`start.bat` działa z katalogu, w którym leży (dowolna lokalizacja), i używa
tylko lokalnego `.venv`. Katalogi `cache`/`tmp` można ustawić zmiennymi
środowiska bieżącej sesji (`PIP_CACHE_DIR`, `TEMP`, `TMP`) - aplikacja niczego
nie zapisuje w konfiguracji systemu.

## Jak używać

1. Wybierz drona (na razie „DJI Tello (djitellopy)”).
2. Wgraj plik `.py` („Wgraj skrypt”), wybierz przykład z listy lub edytuj kod.
3. „▶ Uruchom symulację” (Ctrl+Enter). Skrypt wykonuje się w sandboxie -
   wynik pojawia się po zakończeniu (zwykle ułamki sekund).
   Przycisk „■ Stop” przerwa: proces skryptu jest zabijany, a częściowy lot
   (telemetria do momentu przerwania) zapisuje się ze statusem „przerwany”.
4. Odtwarzanie: spacja (play/pauza), ←/→ (poprzednia/następna komenda),
   suwak czasu, prędkość 0.25x–8x, tryb kamery.
5. Klik w wiersz tabeli komend lub w znacznik w 3D przeskakuje do chwili.
6. Zakładka „Problemy” pokazuje błędy/ostrzeżenia z numerem linii skryptu;
   „Lot” - statystyki i eksport JSON/CSV; „Historia” - poprzednie loty.

### Przykłady (`examples/`)

| Plik | Co pokazuje | Wynik |
|---|---|---|
| `basic_square.py` | start, kwadrat 4 × 100 cm, lądowanie | OK, powrót do startu |
| `climb_and_rotate.py` | wznoszenie, obroty, `go_xyz_speed` | OK |
| `rc_control.py` | `send_rc_control` + `time.sleep` | OK (ruch RC) |
| `error_out_of_range.py` | `move_forward(600)` | błąd zakresu (linia 15) |
| `no_takeoff.py` | ruch bez `takeoff()` | błąd stanu (linia 13) |
| `obstacles_demo.py` | slalom przez 3 bramki (scena `gate_slalom`) | 3/3 bramki, 0 kolizji, 0 ostrzeżeń |
| `obstacles_crash.py` | zbyt mały zjazd w bok przed bramką 2 | kolizja z ramą bramki 2 |

## Ograniczenia symulacji

* To **nie jest fizyka drona** - kinematyka uproszczona (patrz „Założenia”).
* Brak kamery/strumienia wideo (`get_frame_read` zwraca pustą klatkę).
* Brak misji, LED, Throw&Go, palm land i funkcji HD - zgłaszane jako
  „nieobsługiwane w symulacji” (ostrzeżenie, skrypt nie przestaje działać).
* Skrypt nie ma dostępu do sieci (blokada `socket`) - nie może sterować
  prawdziwym dronem.
* Limit 60 s czasu rzeczywistego na skrypt (pętla nieskończona = `timeout`);
  skrypt można też przerwać ręcznie („Stop” → status „przerwany”).
* Limit 3600 s czasu symulacji (ochrona przed nieskończoną pętlą `sleep`).
* Tylko jeden adapter (DJI Tello); inne drony wymagają nowego adaptera.


## Układ współrzędnych

**Jeden układ dla całego projektu** (symulator, biblioteka, widok 3D):

| Pojęcie | Konwencja |
|---|---|
| Osie świata | **x = przód, y = lewo, z = góra** (prawoskrętny, ziemia z = 0) |
| Strona „prawo” drona | **−y** (prawo = ujemne y); „lewo” = +y |
| Kurs wewnętrzny (silnik `sim.yaw`, planer, `physics`) | **matematyczny CCW+**: dodatni = obrót w lewo |
| `get_yaw()` i `yaw` w `send_rc_control` (API Tello) | **CW+**: dodatni = obrót w prawo, rośnie po `rotate_clockwise` |
| `send_rc_control` left_right | dodatni = **w prawo** (= −y) |
| `rotate_clockwise(90)` | w prawo; `get_yaw()` = +90, ruch naprzód idzie na −y |
| `rotate_counter_clockwise(90)` | w lewo; `get_yaw()` = −90, ruch naprzód idzie na +y |
| `yaw` w planerze `dronemoves` | CCW+ wewnętrznie; **publiczne API** (`turn`, `arc`, `Pilot.yaw`, `preview_trajectory`) używa konwencji Tello: **dodatni = w prawo** |

Zmiana znaku między „kursem wewnętrznym” a API Tello jest robiona **tylko na
granicy** (adapter `get_yaw`, `rc_motion`, `Executor._rc_for_sample`), dzięki
czemu wewnątrz projektu nie ma dwóch konkurencyjnych konwencji.

**Biblioteka `dronemoves`**: publiczne API (`turn`, `arc`, `Pilot.yaw`,
`preview_trajectory`) używa **konwencji Tello** — dodatni kąt/kurs = **w prawo**.
Konwersja na kurs wewnętrzny jest w jednym miejscu:
`dronemoves.pilot.api_angle_to_internal` / `internal_angle_to_api`.

```python
pilot.turn(90, radius=60)    # skręt w PRAWO (get_yaw rośnie), Pilot.yaw == 90
pilot.turn(-90, radius=60)   # skręt w LEWO,  Pilot.yaw == 270
pilot.circle(radius=60, direction="right")   # okrążanie po prawej stronie
```

> **Uwaga do wersji 0.1.3**: miała odwrócony kierunek `turn`/`arc` (dodatni kąt
> = w lewo). Wersja 0.1.4 przywraca konwencję Tello z 0.1.0–0.1.2 —
> jeśli piszesz kod pod 0.1.3, zmień znaki kątów.

**Widok 3D**: telemetria (x, y, z) trafia do sceny three.js jako
`(x, z, −y)`, więc przy kamerze patrzącej od tyłu drona wzdłuż +X **prawa
strona drona jest po prawej stronie ekranu** (test:
`tests/test_scene_coordinates.mjs`).

## Założenia symulacji

Zachowania, których nie da się precyzyjnie odwzorować (lub co do których
wybrano rozsądne wartości):

| Element | Przyjęte założenie |
|---|---|
| Układ współrzędnych | patrz sekcja „Układ współrzędnych” powyżej: osie x przód / y lewo / z góra, kurs wewnętrzny CCW+, `get_yaw()` CW+ |
| `takeoff()` | start pionowy na **80 cm** przy 50 cm/s (Tello faktycznie ok. 0,8–1 m) |
| `land()` | opadanie pionowe do z = 0 przy 50 cm/s |
| Ruch pionowy (`up`/`down`, RC) | 50 cm/s niezależnie od `set_speed` |
| Prędkość domyślna | `set_speed` = 50 cm/s (Tello w pętli używa zwykle 100, 50 jest bezpieczniejsze) |
| Prędkość obrotu | 90°/s (Tello nie publikuje czasu obrotu) |
| Tryb RC (`send_rc_control`) | znaki jak w djitellopy/Tello (`rc a b c d`): **left_right > 0 = w prawo**, **yaw > 0 = obrót w prawo** (zgodnie z zegarem, rośnie `get_yaw()`); ruch trwa tyle, ile `time.sleep`, całkowany krokami ≤ 50 ms w układzie drona obracanym w trakcie; prędkość z profilu kalibracji (50 cm/s przy 100), obrót 90°/s, pion 50 cm/s; zerowe RC = tylko upływ czasu |
| `flip()` | trwa 1 s, dron wraca na tę samą pozycję i yaw |
| `curve_xyz_speed` | łuk Beziera 2. stopnia (punkt kontrolny → punkt docelowy), 24 próbki |
| Bateria | 100% na start, −0,05%/s w locie, −0,002%/s na ziemi |
| Zakresy | ruch 20–500 cm, obrót 1–360°, prędkość 10–100 cm/s, wysokość do 500 cm, RC −100..100 |
| Wysokość > 500 cm | ostrzeżenie (nie błąd) |
| Komenda ruchu przed `takeoff` | błąd, skrypt przerwany (jak odrzucenie przez drona) |
| `get_yaw` | zakres −180..180 |
| `query_*` | „nieobsługiwane w symulacji” (brak pakietów telemetrii z drona) |
| Czas komendy | brak limitu 15 s - komenda kończy się po wyliczonym czasie |
| Telemetria | próbki co 50 ms czasu symulacji |
| Model 3D drona | low-poly z prymitywów three.js: obrys **98,5 × 92,5 × 39 mm** (cel 98 × 92,5 × 41 mm, tolerancja ±3 mm), waga 87 g nie ma wpływu na symulację |
| Korpus modelu | zaokrąglony prostopadłościan **45 × 26 × 20 mm** (r 5 mm), od 8 do 28 mm nad ziemią; kamera ø6 × 2 mm zlicowana z przodem |
| Silniki i ramiona | osie silników w **(±27, ±24) mm**, silnik ø8 mm (6–26 mm) + srebrny pierścień ø8,6 mm, nóżka ø3 mm (0–6 mm); ramiona ø4 mm od korpusu (±16, ±11) do osi |
| Śmigła w modelu | średnica **38 mm**, płaszczyzna 37–38,5 mm na wałku ø2,5 mm - śmigła zachodzą w rzucie nad narożniki korpusu, ale są 9 mm wyżej, więc się nie stykają (przerwa między śmigłami 16 mm w X, 10 mm w Y) |
| Osłony śmigieł | poziomy łuk torusa **R 21 mm**, rurka ø2,5 mm, na wysokości 34 mm, łuk **280°** (przerwa 80° skierowana do środka drona) + 2 szprychy ø2 mm pod płaszczyzną śmigła; włączane przełącznikiem „Osłony” |
| Wysokość modelu | dno na `y = 0` (nóżki 6 mm), góra śmigieł 38,5 mm nad ziemią; środek obrotu = środek geometryczny |
| Skala modelu | przełącznik „Rozmiar”: **Prawdziwy (×1)** / ×3 / ×5 / ×10; domyślnie ×5, bo trasy mają kilka metrów. Skalowanie dotyczy tylko modelu - trasa, telemetria i statystyki pozostają w rzeczywistej skali |
| Kierunek przodu | kamera z przodu + subtelny akcent (kolor) na przednich osłonach; opcjonalna strzałka na cieniu drona („Cień”) |

Model jest w osobnym module `app/static/js/drone_model.js` (adaptery w `DRONE_MODELS`),
więc dodanie innego drona = nowa funkcja tworząca model, bez zmian w scenie.
Zdjęcia referencyjne (tylko lokalnie, w `docs/ref/` - katalog jest w `.gitignore`,
bo materiały pochodzą z internetu i nie są publikowane): `tello1.jpg`, `tello2.jpg`.


## Struktura projektu

```
DroneSim/
  app/
    server.py             # FastAPI: upload, uruchamianie, loty, CSV/JSON
    runner.py             # sandbox: podproces, mock djitellopy, blokada sieci, timeout
    sandbox_runtime.py    # stan symulacji w podprocesie, wirtualny zegar, zapis JSONL
    storage.py            # zapis/odczyt lotów i historii
    paths.py              # ścieżki liczone od katalogu projektu
    sim/
      core.py             # silnik: stan drona, zegar, telemetria, zdarzenia
      physics.py          # kinematyka: ruch liniowy/łuk, rampa przyspieszenia
    adapters/
      base.py             # DroneAdapter + rejestr adapterów
      tello/
        adapter.py        # API djitellopy -> silnik, walidacja limitów
        runtime.py        # wspólny kontroler dla mocka
        limits.py         # limity Tello
        djitellopy/       # MOCK pakietu djitellopy (podstawiany w sandboxie)
    static/               # index.html, css, js, three.js lokalnie (vendor/)
  features/               # funkcje dodatkowe (wtyczki): registry.py + <id>/
    obstacles/            # model, sceny, kolizje, endpointy, hooks, feature.json
  scenes/                 # przykładowe sceny przeszkód (JSON)
  scenes/user/            # sceny użytkownika (poza repo)
  examples/               # przykładowe skrypty
  tests/                  # pytest (silnik, adapter, sandbox, API, przeszkody)
  docs/                   # zrzuty ekranu
  config.json             # opcjonalna konfiguracja (włączanie/wyłączanie funkcji)
  flights/                # zapisane loty (JSON; poza repo)
  setup.bat               # tworzenie .venv + requirements.txt
  start.bat               # uruchomienie serwera + przeglądarka
  requirements.txt        # przypięte wersje pakietów
  LICENSE                 # MIT (+ licencja three.js)
```

## Dodawanie nowego adaptera (np. PX4/ArduPilot, Crazyflie)

Silnik (`app/sim/core.py`) nie zna żadnej biblioteki drona; adapter tłumaczy
API biblioteki na operacje silnika.

1. Utwórz katalog `app/adapters/<nazwa>/`, np. `app/adapters/crazyflie/`.
2. Dodaj `limits.py` (zakresy parametrów, zużycie baterii itp.).
3. Utwórz **mock biblioteki**: katalog trafiający na początek `sys.path`
   podprocesu, np. `app/adapters/crazyflie/cflib/` z tymi samymi nazwami
   i sygnaturami metod co prawdziwa biblioteka, przekazującymi wywołania do
   kontrolera adaptera (wzór: `app/adapters/tello/djitellopy/` oraz
   `app/adapters/tello/adapter.py`).
4. Napisz `controller`, który mapuje wywołania na metody `Simulation`:
   `takeoff`, `land`, `move_relative`, `rotate`, `rc_motion`, `advance`,
   `warn` oraz `begin/commit` (zdarzenia komend).
5. Utwórz `adapter.py` z podklasą `DroneAdapter`:

   ```python
   from app.adapters.base import ADAPTERS_DIR, DroneAdapter, register_adapter

   @register_adapter
   class CrazyflieAdapter(DroneAdapter):
       id = "crazyflie"
       name = "Bitcraze Crazyflie (cflib)"
       module_names = ("cflib",)
       # opcjonalnie: RC wykonywany przy time.sleep
       rc_provider = "app.adapters.crazyflie.runtime:controller"

       def limits(self): return {"move_max_cm": 100, ...}
       def mock_root(self): return ADAPTERS_DIR / "crazyflie"
       def runtime_hooks(self): return ("app.adapters.crazyflie.runtime",)
       def settings(self): return {"takeoff_height": 30.0, ...}
   ```

6. Adapter zarejestruje się automatycznie (dekorator `@register_adapter`),
   pojawi się w `/api/adapters` i w UI. Autodetekcja wybiera adapter po
   importach w skrypcie (`module_names`).
7. Dodaj testy (limity, mock, integracja przez `runner.run_script`) i wpis
   w tabeli założeń.

## Bezpieczeństwo

* Serwer nasłuchuje wyłącznie na `127.0.0.1`.
* Skrypt działa w osobnym procesie; prawdziwe `djitellopy` nie jest
  instalowane w `.venv` - `sys.path` sandboxu wskazuje mock.
* W podprocesie `socket.socket`, `create_connection` i `getaddrinfo` rzucają
  `NetworkDisabled` - skrypt nie może wysłać komend do drona.
* Limit 512 KB na skrypt, 60 s czasu wykonania, walidacja identyfikatorów
  lotów (ochrona przed path traversal).
* „Stop” oraz zamknięcie serwera zabijają proces skryptu wraz z potomnymi
  (`taskkill /T`). Każdy skrypt ma też watchdog: gdy proces serwera zniknie
  (np. zabity z Menedżera zadań), skrypt kończy się sam - bez osieroconych
  procesów `python.exe`.

## Licencja

MIT - patrz [LICENSE](LICENSE). three.js (`app/static/vendor/`) - MIT,
Copyright 2010-2023 Three.js Authors.

## Autor

**Vardeex**

* e-mail: [vardeex.exe@gmail.com](mailto:vardeex.exe@gmail.com?subject=Drone%20Script%20Simulator)
* GitHub: [github.com/Vardeex](https://github.com/Vardeex)

