"""Opcjonalne funkcje aplikacji (wtyczki).

Każda funkcja to podkatalog z plikiem ``feature.json`` (manifest) oraz modułem
``router`` (APIRouter). Rdzeń aplikacji (``app.server``) nie importuje ich
bezpośrednio: funkcje są odkrywane i montowane przez
:func:`app.features.registry.enabled_features` i mogą być wyłączone w
konfiguracji (``config.json`` -> ``features``).

Patrz README, sekcja „Punkty rozszerzeń”.
"""
