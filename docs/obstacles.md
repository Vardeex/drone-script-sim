# Przeszkody 3D - notatki techniczne

Dokument dla osób rozwijających funkcję. Instrukcja użytkownika i format JSON
scen są w głównym `README.md` (sekcja „Przeszkody 3D”).

## Gdzie co leży

| Warstwa | Pliki |
|---|---|
| model danych (walidacja, geometria brył, JSON) | `app/features/obstacles/model.py` |
| wykrywanie kolizji / zbliżeń / bramek | `app/features/obstacles/collisions.py` |
| zapis i odczyt scen | `app/features/obstacles/store.py` |
| endpointy `GET/POST/DELETE /api/obstacles/...` | `app/features/obstacles/router.py` |
| hook „po symulacji” | `app/features/obstacles/hooks.py` |
| manifest (włączanie, pliki UI) | `app/features/obstacles/feature.json` |
| rejestr funkcji w rdzeniu | `app/features/registry.py` |
| panel edytora (UI) | `app/static/js/features/obstacles/panel.js` |
| warstwa sceny 3D | `app/static/js/features/obstacles/scene_layer.js` |
| style panelu | `app/static/css/features/obstacles.css` |
| przykładowe sceny | `scenes/*.json` |
| testy | `tests/test_obstacles_*.py`, `tests/obstacles_scene_layer.mjs` |

## Algorytm kolizji (skrót)

1. Trasa: próbki telemetrii + punkty pośrednie co 1 cm (`_interpolate`), więc
   szybki przelot nie przeskakuje cienkiej ściany.
2. Dron = prostopadłościan 10 × 10 × 5 cm obracany kursem (`_box_footprint`).
3. Rzut drona vs rzut bryły: walec - odległość punktu od wielokąta minus
   promień; prostopadłościan/rama - test SAT (`_overlap_distance`) i odległość
   między krawędziami (`_box_center_distance`).
4. Odległość 3D = `hypot(odległość w poziomie, odległość w pionie)`; wynik
   pomniejszony o margines. `< 0` = kolizja, `0..margines` = zbliżenie.
5. **Bramka**: odległość liczona jest do **czterech belek ramy** (nie do
   płaszczyzny bramki), w układzie ramy: `u` wzdłuż ramy i `v = z - gate.position[2]`
   w pionie (środek ramy jest punktem zerowym - **nigdy** wysokość bezwzględna).
   Sprawdzana jest cała bryła drona (wierzchołki + krawędzie co 0,5 cm):
   * dron w otworze: luz najbliższej krawędzi, `min(45 - |u|, 45 - |v|)`
     (środek otworu 90 × 90 → 40 cm),
   * dron dotyka ramy: 0, liczbowo z odległości punktów bryły do belek,
   * poza płaszczyzną ramy: `hypot(odległość w płaszczyźnie, przesunięcie)`.
   Płaszczyzna ramy nie jest przeszkodą: samo jej przecięcie nie daje kolizji
   ani zbliżenia.
6. Jeden wpis kolizji na jedno wejście w bryłę (stan `was_inside` zerowany
   po wyjściu z marginesu), wpisy zbliżeń scalane w czasie (`_group`); dla
   bramki występ przed ramą i za nią to dwa wpisy (strona ramy jest częścią klucza).
7. Bramki: szukamy przecięć płaszczyzny ramy (`_scan_gate`), ocena liczona
   w punkcie przecięcia z kierunkiem lotu z małego okna (`_assess_passage`,
   `_gate_pass_at`). Przelot zaliczony, gdy cały rzut drona mieści się w otworze
   z zapasem `GATE_CENTER_TOLERANCE`.

## Uproszczenia (świadome)

* kinematyka bez fizyki - tak jak cały symulator; kolizja jest tylko raportowana,
* dron to jedna bryła (bez śmigieł i przechyłów),
* bramka to cienka rama prostopadłościenna; „środek otworu” to środek ramy,
* przeloty liczone wzdłuż płaszczyzny ramy - lot ukośny jest oceniany przez rzut
  drona na tę płaszczyznę,
* minimalny odstęp w statystykach liczony jest bez marginesu (rzeczywisty
  odstęp powierzchni drona od przeszkody).

## Test warstwy 3D w Node

Warstwa korzysta z three.js tak samo jak UI. Test ładuje prawdziwy
`three.module.js` (loader `tests/three_loader.mjs`) i sprawdza API warstwy:

```bat
node tests\\obstacles_scene_layer.mjs
```
