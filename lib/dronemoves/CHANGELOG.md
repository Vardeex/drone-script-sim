# Zmiany w dronemoves

Forma zgodna z [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie zgodne z [SemVer](https://semver.org/lang/pl/).

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
