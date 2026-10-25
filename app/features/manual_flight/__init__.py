"""Funkcja „Lot ręczny” - sterowanie klawiaturą, nagrywanie lotu i generator skryptu.

Wtyczka jest samodzielna: rdzeń łączy się z nią tylko przez punkty rozszerzeń
(API pod ``/api/manual_flight``, panel UI, warstwa sceny 3D, style). Fizykę
bierze z ``app.sim.core`` (ta sama, której używa symulacja skryptów), więc
nagranie odtwarza się w symulatorze 1:1.

Wyłączenie w ``config.json`` (``{"features": {"manual_flight": {"enabled": false}}}``)
usuwa endpointy i panel - reszta aplikacji działa bez zmian.
"""

from __future__ import annotations
