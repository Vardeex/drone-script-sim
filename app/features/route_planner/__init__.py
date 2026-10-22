"""Funkcja „Planer trasy” - model trasy, walidacja, generowanie kodu, podgląd.

Moduł jest samodzielny: nie importuje rdzenia aplikacji poza ``app.paths``.
Rdzeń łączy się z nim tylko przez punkty rozszerzeń (README, „Punkty
rozszerzeń”):

1. ``feature.json`` + ``router.router`` - montowanie API przez rejestr funkcji,
2. ``hooks.register(storage)`` - hook po zapisie lotu (zapisuje trasę w locie),
3. ``static/js/features/route_planner/*`` - panel UI i warstwa sceny 3D.

Kontrola kolizji korzysta z funkcji przeszkód **tylko wtedy**, gdy jest ona
włączona; planer działa też bez niej (wtedy bez kontroli kolizji).
"""

#: format bloku-znacznika z trasą w generowanym skrypcie
ROUTE_FORMAT = "dronesim-route"
