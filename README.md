# Drone Script Simulator

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
* interfejs w języku polskim, działa offline (three.js jest lokalnie).

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


## Założenia symulacji

Zachowania, których nie da się precyzyjnie odwzorować (lub co do których
wybrano rozsądne wartości):

| Element | Przyjęte założenie |
|---|---|
| Układ współrzędnych | X do przodu, Y w lewo, Z w górę; yaw 0° = przód w +X, obrót dodatni = w lewo (jak Tello) |
| `takeoff()` | start pionowy na **80 cm** przy 50 cm/s (Tello faktycznie ok. 0,8–1 m) |
| `land()` | opadanie pionowe do z = 0 przy 50 cm/s |
| Ruch pionowy (`up`/`down`, RC) | 50 cm/s niezależnie od `set_speed` |
| Prędkość domyślna | `set_speed` = 50 cm/s (Tello w pętli używa zwykle 100, 50 jest bezpieczniejsze) |
| Prędkość obrotu | 90°/s (Tello nie publikuje czasu obrotu) |
| Tryb RC (`send_rc_control`) | ruch trwa tyle, ile `time.sleep`; prędkość = wychylenie/100 × `set_speed`; obrót 100 = 90°/s; pion 100 = 50 cm/s; zerowe RC = tylko upływ czasu |
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
  examples/               # przykładowe skrypty
  tests/                  # pytest (silnik, adapter, sandbox, API)
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

