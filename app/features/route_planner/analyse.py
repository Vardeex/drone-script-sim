"""Most do funkcji „Przeszkody 3D” - jedyny punkt łączenia obu funkcji.

Planer **nie importuje** modułów funkcji przeszkód na sztywno. Rdzeń podaje
(przez rejestr funkcji) manifest włączonych funkcji; ten moduł sprawdza, czy
funkcja ``obstacles`` jest na liście, i dopiero wtedy importuje jej moduł
``collisions``. Gdy funkcja przeszkód jest wyłączona (albo nie istnieje),
kontrola kolizji jest pomijana, a reszta planera działa normalnie.

Publiczny kontrakt funkcji przeszkód użyty tutaj: ``analyse_flight(samples,
events, scene_dict, margin) -> dict`` oraz ``DEFAULT_MARGIN``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _obstacles_enabled(features: Optional[list]) -> bool:
    """Czy na liście włączonych funkcji (``GET /api/features``) są przeszkody?"""
    if not features:
        return False
    return any((item or {}).get("id") == "obstacles" for item in features)


def analyse_flight(samples: Any, events: Any, scene: Dict[str, Any],
                   margin_cm: Optional[float] = None) -> Dict[str, Any]:
    """Analiza lotu przez funkcję przeszkód (import leniwy, opcjonalny).

    :raises ImportError: gdy funkcja przeszkód nie jest dostępna w aplikacji
    """
    from ..obstacles import collisions  # import tylko tego modułu funkcji

    margin = collisions.DEFAULT_MARGIN if margin_cm is None else float(margin_cm)
    return collisions.analyse_flight(samples, events, scene, margin=margin)


def available(features: Optional[list] = None) -> bool:
    """Czy kontrola kolizji jest dostępna (wtyczka przeszkód włączona i działa).

    Gdy ``features`` nie podano, pytamy rejestr wtyczek o stan ``obstacles``:
    wtyczka wyłączona albo z błędem = brak kontroli kolizji (planer działa dalej).
    """
    if features is None:
        from app.features import registry

        state = registry.resolve_state("obstacles")
        if state != registry.STATE_ENABLED:
            return False
    elif not _obstacles_enabled(features):
        return False
    try:
        import importlib

        importlib.import_module("app.features.obstacles.collisions")
    except Exception:
        return False
    return True
