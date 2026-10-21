# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/); wersjonowanie
zgodne z [SemVer](https://semver.org/lang/pl/).

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
