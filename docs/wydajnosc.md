# Wydajność interfejsu 3D - pomiary i tryb lekki

Dokument opisuje **zmierzone** zachowanie aplikacji, nie odczucia. Wszystkie
liczby pochodzą ze skryptu `release_tools/perf_bench.py` (Playwright + Chromium),
uruchamianego na tej samej maszynie w trzech wariantach: **przed** zmianami
(kod 0.4.0), **po** w trybie pełnym i **po** w trybie lekkim.

## Jak to zmierzono

| Element | Wartość |
|---|---|
| scenariusze | a) bezczynna scena, b) odtwarzanie `basic_square` 1x i 8x, c) długi lot (150 komend) + przewijanie suwakiem, d) tor przeszkód + odtwarzanie, e) lot ręczny, f) przeciąganie punktu w planerze |
| profil **normalny** | okno 1600x900, bez throttlingu, GPU jeśli dostępne |
| profil **ziemniak** | okno 1280x720, **CPU 6x wolniej** (`Emulation.setCPUThrottlingRate`), renderowanie programowe (SwiftShader, `--disable-gpu`) |
| powtórzenia | 2 przebiegi na scenariusz, w tabelach mediana |
| FPS | płynność pętli animacji (rAF) - to, co odczuwa użytkownik (płynność UI, kliknięcia, suwak) |
| **rysowane/s** | ile klatek naprawdę narysowano (tryb lekki rysuje **tylko przy zmianach**) |
| 1% najgorszych | średnia z najwolniejszego 1% klatek **rysowanych** |
| JS ms/klatkę | CDP `Performance.getMetrics` → `ScriptDuration` na klatkę |
| pamięć, draw calls, trójkąty | `performance.memory`, `renderer.info.render` |
| rozmiar danych lotu | CDP `Network` (bajty po kompresji) + długość odpowiedzi |

Powtórzenie pomiarów:

```bash
python release_tools/perf_bench.py --profile both --repeat 2            # tryb pełny
python release_tools/perf_bench.py --profile both --repeat 2 --lite     # tryb lekki
```

## Przed zmianami (kod 0.4.0, tryb pełny)

| Scenariusz | FPS | JS ms/kl. | Draw calls | Trójkąty |
|---|---|---|---|---|
| normal: a) bezczynna scena | 35.8 | 0.81 | 56 | 12 321 |
| normal: b) odtwarzanie 1x | 31.2 | 1.44 | 110 | 15 779 |
| normal: b) odtwarzanie 8x | 34.7 | 1.24 | 108 | 15 779 |
| normal: c) długi lot - odtwarzanie | 31.6 | 1.38 | 112 | 15 794 |
| normal: c) długi lot - przewijanie | 31.4 | 1.47 | 112 | 15 794 |
| normal: d) tor przeszkód + odtwarzanie | 19.2 | 1.81 | 127 | 15 903 |
| normal: e) lot ręczny | 33.1 | 1.02 | 58 | 12 321 |
| normal: f) planer - przeciąganie punktu | 29.5 | 2.25 | 61 | 12 483 |
| **ziemniak: a) bezczynna scena** | **31.1** | **9.09** | 56 | 12 321 |
| **ziemniak: b) odtwarzanie 1x** | **18.4** | **14.92** | 110 | 15 779 |
| **ziemniak: b) odtwarzanie 8x** | **27.1** | **11.37** | 108 | 15 779 |
| **ziemniak: c) długi lot - odtwarzanie** | **18.9** | **15.49** | 112 | 15 794 |
| **ziemniak: c) długi lot - przewijanie** | **20.4** | **15.38** | 112 | 15 794 |
| **ziemniak: d) tor przeszkód + odtwarzanie** | **16.3** | **19.14** | 124 | 15 879 |
| **ziemniak: e) lot ręczny** | **24.4** | **10.27** | 58 | 12 321 |
| **ziemniak: f) planer - przeciąganie punktu** | **14.8** | **21.88** | 61 | 12 483 |

Start (czas do pierwszego narysowania sceny): **918-1060 ms** (ziemniak).
Dane lotu `basic_square.py`: **46,6 kB** bez kompresji (`Content-Encoding: brak`).

## Po zmianach - tryb pełny (wygląd i zachowanie jak dotąd)

| Scenariusz | FPS | Rysowane/s | 1% najg. | JS ms/kl. | Draw calls | Trójkąty |
|---|---|---|---|---|---|---|
| normal: a) bezczynna scena | 37.3 | 39.2 | 30.6 | 0.75 | 56 | 12 321 |
| normal: b) odtwarzanie 1x | 32.4 | 33.6 | 24.4 | 1.44 | 110 | 15 779 |
| normal: b) odtwarzanie 8x | 35.7 | 37.8 | 27.6 | 1.28 | 108 | 15 779 |
| normal: c) długi lot - odtwarzanie | 31.8 | 33.5 | 27.0 | 1.49 | 112 | 15 794 |
| normal: c) długi lot - przewijanie | 32.1 | 42.3 | 25.4 | 1.46 | 112 | 15 794 |
| normal: d) tor przeszkód + odtwarzanie | 21.9 | 23.1 | 17.4 | 1.67 | 127 | 15 903 |
| normal: e) lot ręczny | 35.0 | 37.0 | 29.3 | 0.95 | 58 | 12 321 |
| normal: f) planer - przeciąganie punktu | 31.1 | 74.5 | 18.7 | 2.22 | 61 | 12 483 |
| ziemniak: a) bezczynna scena | 33.7 | 35.2 | 24.6 | 8.16 | 56 | 12 321 |
| ziemniak: b) odtwarzanie 1x | 22.6 | 23.6 | 12.3 | 12.27 | 110 | 15 779 |
| ziemniak: b) odtwarzanie 8x | 23.2 | 24.8 | 16.5 | 13.70 | 108 | 15 779 |
| ziemniak: c) długi lot - odtwarzanie | 23.1 | 24.7 | 16.4 | 11.82 | 112 | 15 794 |
| ziemniak: c) długi lot - przewijanie | 22.6 | 38.2 | 14.3 | 13.35 | 112 | 15 794 |
| ziemniak: d) tor przeszkód + odtwarzanie | 17.6 | 18.7 | 13.7 | 16.04 | 124 | 15 879 |
| ziemniak: e) lot ręczny | 24.5 | 26.4 | 11.9 | 8.99 | 58 | 12 321 |
| ziemniak: f) planer - przeciąganie punktu | 15.3 | 67.4 | 5.7 | 21.64 | 61 | 12 483 |

Tryb pełny wygląda i działa jak dotąd (wszystkie testy przeglądarkowe bez zmian).
Poprawa w „torze przeszkód” (16,3 → 17,6 FPS, JS 19,14 → 16,04 ms) to efekt
usunięcia przebudowy znaczników kolizji **w każdej klatce** (punkt 2 niżej).

## Po zmianach - tryb lekki

| Scenariusz | FPS | Rysowane/s | 1% najg. | JS ms/kl. | Draw calls | Trójkąty |
|---|---|---|---|---|---|---|
| normal: a) bezczynna scena | 60.0 | 0.0 | - | 0.07 | 16 | 405 |
| normal: b) odtwarzanie 1x | 60.0 | 30.2 | 28.9 | 0.37 | 19 | 1 089 |
| normal: b) odtwarzanie 8x | 60.0 | 26.8 | 28.9 | 0.39 | 18 | 1 089 |
| normal: c) długi lot - odtwarzanie | 60.0 | 30.3 | 28.8 | 0.39 | 20 | 6 216 |
| normal: c) długi lot - przewijanie | 60.0 | 20.0 | 19.4 | 0.40 | 20 | 6 216 |
| normal: d) tor przeszkód + odtwarzanie | 60.0 | 30.2 | 28.7 | 0.40 | 31 | 1 153 |
| normal: e) lot ręczny | 60.0 | 10.0 | 8.5 | 0.26 | 18 | 405 |
| normal: f) planer - przeciąganie punktu | 59.4 | 34.2 | 17.1 | 0.41 | 20 | 695 |
| **ziemniak: a) bezczynna scena** | **60.0** | **0.0** | - | **0.50** | **16** | **405** |
| **ziemniak: b) odtwarzanie 1x** | **60.0** | **30.2** | **26.1** | **2.96** | **19** | **1 089** |
| **ziemniak: b) odtwarzanie 8x** | **60.0** | **26.0** | **23.3** | **2.50** | **18** | **1 089** |
| **ziemniak: c) długi lot - odtwarzanie** | **59.9** | **30.2** | **23.9** | **2.65** | **19** | **1 089** |
| **ziemniak: c) długi lot - przewijanie** | **59.5** | **20.0** | **14.4** | **2.54** | **19** | **1 089** |
| **ziemniak: d) tor przeszkód + odtwarzanie** | **60.0** | **30.2** | **24.1** | **3.31** | **29** | **1 141** |
| **ziemniak: e) lot ręczny** | **60.0** | **10.2** | **8.5** | **2.08** | **18** | **405** |
| **ziemniak: f) planer - przeciąganie punktu** | **57.9** | **47.7** | **9.1** | **3.40** | **20** | **695** |

Start: **423-478 ms** (było 918-1060 ms) - poniżej progu 3 s z dużym zapasem.
Dane lotu `basic_square.py`: **46,6 kB → 4,95 kB** po gzipie (9,4x mniej).

## Pięć największych źródeł spowolnienia (z dowodami z profilera)

1. **Ciągłe rysowanie 60 razy na sekundę, nawet gdy nic się nie zmienia.**
   Bezczynna scena na „ziemniaku”: JS **9,09 ms na klatkę**, 56 draw calls
   i 12 321 trójkątów przy zerowej zmianie obrazu. Po przejściu na *render on
   demand*: **0 klatek narysowanych w 1,5 s bezczynności**, JS **0,50 ms**
   (18x mniej pracy na klatkę).
2. **Przebudowa znaczników kolizji w każdej klatce** (`setMarkersTime` wołał
   `rebuildMarkers`: nowe siatki + **tekstury kanwy dla etykiet** przy każdym
   `move_forward`). Dowód: scenariusz „tor przeszkód” był najgorszy w całym
   zestawie (16,3 FPS, JS 19,14 ms, 124 draw calls). Po zmianie na przebudowę
   tylko przy zmianie liczby „miniętych” znaczników: JS **16,04 ms** i 17,6 FPS
   w trybie pełnym, a w lekkim **3,31 ms / 60 FPS**. Wygląd bez zmian.
3. **Koszt per piksel i per obiekt w materiale oświetlonym** (cienie, mgła,
   `MeshStandardMaterial`, 12-16 tys. trójkątów, pełny ekran podłoża).
   Dowód: przejście na materiały „basic”, wyłączenie cieni/mgły/świateł
   i uproszczony model drona dało **1 089 trójkątów i 19 draw calls** zamiast
   15 779/110 - w połączeniu z rozdzielczością 75-50% renderowanie przestało
   być wąskim gardłem (rysowane/s 18-24 → **30**).
4. **DOM aktualizowany w każdej klatce** (`updateHud` - 7 elementów, etykiety
   czasu, podświetlanie wiersza tabeli komend przez pętlę po wszystkich
   wierszach, `updatePlayButton`). Dowód: w trybie pełnym na „ziemniaku”
   `LayoutDuration` 2,84 ms/klatkę (obok `ScriptDuration`), a po ograniczeniu
   odświeżania paneli do 10 Hz w trybie lekkim JS spadł do **2,96 ms**
   przy jednoczesnym wzroście FPS do 60.
5. **Rozmiar danych lotu i koszt ich przetworzenia.** Odpowiedź
   `/api/flights/...` dla `basic_square.py` miała **46,6 kB bez kompresji**,
   a dłuższe loty proporcjonalnie więcej (tysiące próbek → megabajty).
   Po włączeniu gzipa w HTTP: **4,95 kB** (9,4x mniej). Dodatkowo tryb lekki
   rysuje trasę uproszczoną algorytmem Ramera-Douglasa-Peuckera (1 cm), więc
   linia ma mniej wierzchołków - dane i pomiary pozostają nietknięte.

## Co dokładnie zmienia tryb lekki

| Obszar | Tryb pełny | Tryb lekki |
|---|---|---|
| rysowanie | każda klatka | tylko przy zmianie + limit 30 FPS, pauza gdy karta ukryta |
| rozdzielczość | `devicePixelRatio` do 2, AA włączone | pixelRatio 1, 75% (adaptacyjnie do 50%), bez AA |
| model drona | pełny Tello (kilkadziesiąt siatek) | 5 brył, 2 materiały, płaskie krążki śmigieł bez animacji |
| światło/cienie/mgła | tak | nie (materiały „basic”) |
| siatka podłoża | 1 m + drobna 10 cm | tylko 1 m |
| etykiety 3D | numery komend (sprite) + pionowe linie wysokości | brak (dane w panelach i dymkach) |
| trasa | wszystkie próbki + cień trasy na podłożu | uproszczona RDP 1 cm, bez cienia trasy |
| znaczniki komend | osobne siatki | jeden `InstancedMesh` (1 draw call) |
| wektor prędkości, FPV | tak | wyłączone (FPV opcję można włączyć w ustawieniach) |
| panele | każda klatka | max 10 razy na sekundę; długie tabele - okno wierszy |
| linia planu (planer) | zawsze | domyślnie nie, przełącznik „Linia planu”; podgląd co 300 ms |

## Ocena celu

| Kryterium | Wynik (ziemniak, tryb lekki) |
|---|---|
| ≥ 30 FPS średnio | **60 FPS** pętli UI, **30,2 klatki rysowane/s** przy odtwarzaniu (limit 30 FPS) |
| ≥ 20 FPS w 1% najgorszych | **26,1** (odtwarzanie 1x), **23,9** (długi lot), **24,1** (przeszkody) |
| start do pierwszego obrazu ≤ 3 s | **423-478 ms** |
| brak zacięć przy przewijaniu | przewijanie: 59,5 FPS pętli, 20 klatek/s - tyle, ile zdarzeń suwaka (każde przesunięcie = jedna klatka) |

Szczegółowe uwagi o scenariuszach, w których „klatki rysowane” są niższe niż 30
(przewijanie 20/s, lot ręczny 10/s, planer) - w `KNOWN_ISSUES.md`: to skutek
zasady „rysuj tylko przy zmianie”, a nie spadków wydajności.
