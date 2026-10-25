"""Podpowiedzi dla edytora generowane **z kodu**, nie z ręcznej listy.

Dwa źródła prawdy:

* ``app.adapters.tello.djitellopy.tello.Tello`` - mock ``djitellopy`` (dokładnie
  te metody, które zobaczy skrypt w sandboxie),
* ``dronemoves`` - ``Pilot``, ``safe_start``/``preflight`` i pozostałe funkcje
  publiczne biblioteki.

Dla każdej pozycji bierzemy **sygnaturę** (``inspect.signature``) i pierwszy
akapit docstringa. Dzięki temu zmiana API biblioteki automatycznie zmienia
podpowiedzi - nie ma drugiej, ręcznie utrzymywanej listy.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional


def _first_paragraph(doc: Optional[str]) -> str:
    """Pierwszy akapit docstringa (bez wielokrotnych spacji i nowych linii)."""
    if not doc:
        return ""
    paragraph = doc.strip().split("\n\n")[0]
    return " ".join(line.strip() for line in paragraph.splitlines()).strip()


def _item(name: str, target: Any, kind: str) -> Dict[str, Any]:
    """Opis jednej pozycji podpowiedzi (etykieta, typ, sygnatura, opis)."""
    try:
        signature = str(inspect.signature(target))
    except (TypeError, ValueError):        # pragma: no cover - obiekty C
        signature = "(...)"
    detail = f"{name}{signature}"
    return {"label": name, "type": kind, "detail": detail,
            "info": _first_paragraph(getattr(target, "__doc__", None))}


def _members(cls: Any, kind: str = "method") -> List[Dict[str, Any]]:
    """Publiczne metody klasy (bez ``__dunderów`` i bez właściwości)."""
    items = []
    for name, member in inspect.getmembers(cls):
        if name.startswith("_") or not callable(member):
            continue
        items.append(_item(name, member, kind))
    return items


def _module_functions(module: Any) -> List[Dict[str, Any]]:
    """Publiczne funkcje z modułu (np. ``safe_start`` z ``dronemoves``)."""
    items = []
    for name, member in inspect.getmembers(module):
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        if getattr(member, "__module__", "").split(".")[0] != module.__name__.split(".")[0]:
            continue                      # pomijamy zaimportowane z innych pakietów
        items.append(_item(name, member, "function"))
    return items


def build() -> Dict[str, List[Dict[str, Any]]]:
    """Zbuduj listy podpowiedzi: ``tello``, ``pilot``, ``all``.

    ``tello`` - metody mocka ``djitellopy`` (po ``tello.``),
    ``pilot`` - API biblioteki ``dronemoves`` (po ``pilot.``),
    ``all``   - wszystko razem + klasy (podpowiedzi bez kropki).
    """
    tello_items: List[Dict[str, Any]] = []
    try:
        from .adapters.tello.djitellopy.tello import Tello

        tello_items = _members(Tello)
    except Exception:                     # noqa: BLE001 - brak adaptera = brak podpowiedzi
        tello_items = []

    pilot_items: List[Dict[str, Any]] = []
    module_items: List[Dict[str, Any]] = []
    try:
        import dronemoves
        from dronemoves import Pilot

        pilot_items = _members(Pilot)
        module_items = _module_functions(dronemoves)
        for name in ("Pilot",):
            member: Callable[..., Any] = getattr(dronemoves, name, None)
            if member is not None:
                module_items.append(_item(name, member, "class"))
    except Exception:                     # noqa: BLE001 - biblioteka opcjonalna
        pilot_items = []

    def sort_key(item: Dict[str, Any]) -> str:
        return item["label"].lower()

    tello_items.sort(key=sort_key)
    pilot_items.sort(key=sort_key)
    everything = sorted(tello_items + pilot_items + module_items, key=sort_key)
    # usuń duplikaty etykiet w „all" (ta sama nazwa w Tello i Pilot)
    seen: set = set()
    unique = []
    for item in everything:
        if item["label"] in seen:
            continue
        seen.add(item["label"])
        unique.append(item)
    return {"tello": tello_items, "pilot": pilot_items, "all": unique}
