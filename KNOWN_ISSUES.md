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

## KI-3: warstwa 3D planera trasy nie jest podłączana do sceny (frontend) - NAPRAWIONE w 0.2.1

**Objaw.** Panel „Planer” ładuje się i działa (dodawanie punktów listą, kod,
podgląd), ale **klik na podłożu w scenie 3D nie dodaje punktu** i markery trasy
się nie rysują.

**Przyczyna (potwierdzona).** W `app/static/js/features/route_planner/scene_layer.js`
w funkcji `drawLine()` brakowało zamykającej klamry po
`lines.add(new THREE.Line(...));`. Przez to `redraw`, `rayAt`, `markerAt`,
`groundAt`, `onDown`, `onMove`, `onUp` i `return { ... }` znalazły się
**wewnątrz** `drawLine`, a `createLayer` nic nie zwracało. Nadmiarowa `}` na
końcu pliku (linia 235) maskowała błąd przed sprawdzaniem składni, a różnica
7585/7589 znaków to końce linii CRLF, nie cache.

**Naprawa.** Dodana `}` zamykająca `drawLine()`, usunięta nadmiarowa `}` z końca
pliku; etykiety punktów zmniejszone do ~34 x 13 cm.
**Test regresyjny:** `tests/test_route_planner_browser.py` (Playwright) -
`createLayer` zwraca obiekt z metodami, klik na podłożu dodaje punkt, w scenie
jest grupa `route-planner` z markerami.
