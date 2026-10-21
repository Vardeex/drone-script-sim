"""Funkcja „Przeszkody 3D” - edytor scen, kolizje, przeloty przez bramki.

Moduł jest całkowicie samodzielny: nie importuje rdzenia aplikacji poza
``app.paths`` (ścieżki projektu). Rdzeń łączy się z nim tylko przez punkty
rozszerzeń opisane w README (sekcja „Punkty rozszerzeń”):

1. ``feature.json`` + ``router.router`` - montowanie API przez rejestr funkcji,
2. ``hooks.on_flight_saved`` - analiza lotu po jego zapisaniu,
3. ``static/js/features/obstacles/*`` - panel UI i warstwa sceny 3D.
"""
