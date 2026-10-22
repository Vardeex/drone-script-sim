# Znane problemy (KNOWN ISSUES)

Problemy zdiagnozowane w tej sesji, których **nie naprawiamy dalej** (reguła:
po 3 próbach naprawy opisujemy problem i przechodzimy dalej). Testy ich
dotykające są oznaczone `pytest.mark.xfail(reason=...)` z odnośnikiem tutaj —
**nigdy** nie zmieniamy oczekiwanych wartości pod wynik programu.

---

## KI-1: `Pilot.path` ignoruje kurs zaplanowany na starcie manewru (dronemoves 0.1.5)

**Objaw.** Trasa, której pierwszy odcinek nie zaczyna się w kierunku, w którym
patrzy dron, jest realizowana „prosto przed siebie”.

**Pomiary** (`pilot.path(point)` po `takeoff`, kurs startowy 0°):

| Wywołanie | Kurs startowy drona | Koniec w symulatorze | Oczekiwane (geometria) |
|---|---|---|---|
| `path([(0, -120, 0)])` | 0° | **(119.9, 0.0)** | (0, −120) — 120 cm w prawo |
| `path([(0, 120, 0)])` | 0° | **(119.9, 0.0)** | (0, +120) — 120 cm w lewo |
| `path([(120, 0, 0)])` | 0° | (119.9, 0.0) ✅ | (120, 0) |
| `rotate_clockwise(90)` + `path([(0, -120, 0)])` | 90° w prawo | (0, **−119.9**) ✅ | (0, −120) |
| `rotate_clockwise(180)` + `path([(0, -120, 0)])` | 180° | (**−119.9**, 0) ✅ | (−120, 0) |

Gdy dron **fizycznie** jest obrócony (`rotate_*`), ruch idzie poprawnie. Błąd
występuje tylko wtedy, gdy plan zakłada kurs **niezgodny z kursem startowym**,
a sterowanie ma to zrealizować w trakcie manewru (samo z siebie).

Skutek w planerze trasy (tryb „płynna”): trasa „za plecami” ma **120 cm**
odchylenia od punktów (punkt nigdy nie odwiedzony) — patrz
`tests/test_route_conformance.py` (xfail) i KNOWN_ISSUES w RAPORT_SESJI.

**Co sprawdziłem (bez efektu):**
1. **Plan biblioteki jest poprawny.** `plan_path([(0,0,0), (0,-120,0)])` ma
   `yaw = 270.0` i `vy = -40` we wszystkich 67 próbkach; `Pilot.preview()`
   i `Pilot.path()` zwracają koniec `(0.0, -120.0)`.
2. **Przeliczenie na RC jest poprawne.** Sonda w symulatorze na
   `Executor._rc_for_sample`: `(t=0.4, yaw=270, vx=0, vy=-40)` → `(0, 80, 0, 0)`
   = „przód 80”. Zgodnie z geometrią: yaw 270° (CCW) → oś nosa `(cos270, sin270)`
   = `(0, -1)` = −Y, więc przód = −Y. Wysyłane RC **nie zawiera** obrotu
   (`yaw` kanału = 0 przez cały przelot).
3. **Symulator jest poprawny** (sondy bez biblioteki, `send_rc_control` przez
   1 s): kurs 0° `fb=+60` → `(30, 0)`; kurs 0° `lr=+60` → `(0, -30)`;
   kurs 90° (`rotate_clockwise(90)`) `fb=+60` → `(0, -30)`, `lr=+60` → `(-30, 0)`.
   Symulator zachowuje kurs również po serii RC.

**Podejrzana przyczyna (nieweryfikowana).** Wartości RC są poprawne przy
założeniu, że dron **już** patrzy w `yaw` z planu, ale plan nie zawiera żadnej
komendy ustawiającej kurs (kanał `yaw` RC = 0). Symulator startuje z kursem 0°,
więc „przód” idzie w +X. Brakuje jednego z dwóch elementów: (a) obrotu w
miejscu o różnicę kursu przed `path`/na początku `path`, albo (b) niezerowego
`yaw` w kanale RC na początku manewru. Miejsce do sprawdzenia:
`TrajectoryBuilder.curve` / `plan_path` (czy `yaw` próbki 0 powinien być
wpisany jako kurs startowy pilota) oraz `Executor.execute` (czy pierwsza próbka
nie powinna ustawić kursu).

**Czego NIE robiłem.** Nie zmieniałem symulatora (jest sprawdzony pomiarami)
ani teorii sterowania biblioteki — to wymaga decyzji o architekturze
(obrót w miejscu vs. sterowanie kursem w RC), a nie kolejnej poprawki.

---

## KI-3: warstwa 3D planera trasy nie jest podłączana do sceny (frontend)

**Objaw.** Panel „Planer” ładuje się i działa (dodawanie punktów listą, kod,
podgląd), ale **klik na podłożu w scenie 3D nie dodaje punktu** i markery trasy
się nie rysują.

**Pomiary (Playwright, Chromium):**
- `window.__featureErrors` = `{obstacles: [], route_planner: []}` (brak błędów),
- `boot.sceneLayers` = `['obstacles', 'route_planner']` (fabryki zarejestrowane),
- log dodany tymczasowo w `attachSceneLayers`:
  `obstacles: instance = object true` / **`route_planner: instance = undefined false`**,
- `featureState.layers` = `{}` (pusta), `sceneLayers` rośnie do 4 wpisów przy
  kolejnym wywołaniu (aplikacja inicjalizuje funkcje dwa razy),
- moduł `scene_layer.js` importuje się bez błędu i eksportuje `createLayer`,
- ten sam moduł wywołany z atrapą sceny zwraca `undefined` (bez wyjątku),
- plik jest serwowany poprawnie (`200`, 8891 znaków), a `node` potwierdza
  poprawną składnię po podmianie importu `three`.

**Co sprawdziłem:**
1. Rdzeń (`boot.js`, `app.js`) przekazuje `scene` do fabryki
   (`layer.factory({ scene, ...context })`) i ma `try/catch` z
   `console.error` — konsola nie pokazuje żadnego błędu.
2. Kolejność: `registerFeatures` (panele) biegnie **przed**
   `attachSceneLayers` (warstwy) — panel dostaje `getLayer` zwracające `null`
   w chwili rejestracji; dodałem `waitForLayer()` z ponawianiem.
3. Przeszkody (ta sama ścieżka rdzenia) działają poprawnie — więc to nie jest
   ogólna regresja rdzenia.

**Podejrzana przyczyna.** `createLayer` w `scene_layer.js` kończy się w taki
sposób, że przeglądarka nie widzi `return` (zwraca `undefined` bez wyjątku),
mimo że `node` przyjmuje składnię. Plik był składany w kilku krokach
(wstawki edytora) i `return { ... }` (linia 216) może znajdować się w innym
zasięgu niż się wydaje — dokładna analiza zasięgów: **do zrobienia**.

**Obejście:** punkty dodaje się przyciskiem „✚ Dodaj punkt” w panelu (działa),
a współrzędne edytuje w liście. Zaznaczanie punktów klikiem i rysowanie
markerów w 3D będą dostępne po naprawie KI-3.

**Naprawa (plan).** Zamiast pliku składanego wstawkami: napisać
`scene_layer.js` od zera jednym zapisem (< 6000 znaków) i sprawdzić zwrot
`createLayer` testem Playwright (`instance = object`). Wersja robocza tego
pliku jest zapisana w gałęzi `backup-przed-sesja` (tam też jest punkt wyjścia).

**Aktualizacja po przepisaniu pliku.** `scene_layer.js` został przepisany od
zera (236 linii, `node` potwierdza poprawną składnię, struktura klamer
domyka się do `depth=0`), a mimo to `createLayer` nadal zwraca `undefined`
bez wyjątku w przeglądarce. Dodatkowy trop: serwer oddaje plik o długości
**7585 znaków**, gdy na dysku jest **7589** (i `tail` pokazuje o jedną `}`
więcej) — wygląda na to, że przeglądarka/serwer widzi inną wersję niż
zapisana (cache `?v=25` albo bufor `StaticFiles`). Sprawdziłem: `?q=<timestamp>`
nie pomógł; zrzut treści przez `fetch(..., {cache:'no-store'})` pokazał treść
z nadmiarową `}`, której w pliku już nie ma. **Kolejny krok:** zrestartować
serwer i wyczyścić cache przeglądarki w teście (`page.route` / nowy kontekst),
albo podbić `ASSET_VERSION` w `app.js`.



---

## KI-2: tryb „płynna” planera — odchylenie > 15 cm na 1 z 4 tras

Po poprawce 0.1.5 (wysokość startowa `(0, 0, 0)`) odchylenia w symulatorze:

| Trasa | Odchylenie od punktów | Limit 15 cm |
|---|---|---|
| kwadrat | 3.6 cm | ✅ |
| wokół przeszkody | 13.7 cm | ✅ |
| obroty | 10.3 cm | ✅ |
| za plecami | 120.0 cm | ❌ — przyczyna: **KI-1** |

Trasa „za plecami” zaczyna się punktem w −Y przy kursie 0°, więc wymaga kursu
270° na starcie manewru — dokładnie przypadek KI-1. Test jest `xfail`, a UI
pokazuje ostrzeżenie „tryb płynny: odchylenie do N cm od punktów” (nie blokuje
generowania).
