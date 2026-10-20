"""Abstrakcyjny interfejs adaptera drona + rejestr adapterów.

Adapter łączy *bibliotekę API drona* (np. ``djitellopy``) z *silnikiem
symulacji* (:class:`app.sim.core.Simulation`). Adapter:
  * zna nazwy modułów, które podstawia w sandboxie (``module_names``),
  * zna limity parametrów (``limits``),
  * przygotowuje środowisko podprocesu (``sandbox_paths``, ``patch_module``),
  * dostarcza szablony/mocki do wstrzyknięcia na ``sys.path``.

Silnik symulacji nie wie nic o marce drona - dostaje tylko tłumaczone
operacje (ruch, obrót, start, lądowanie...).
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Type

from ..paths import ADAPTERS_DIR
from ..sim.core import FlightData, Simulation


@dataclass
class AdapterInfo:
    """Dane adaptera do zaprezentowania w UI."""

    id: str
    name: str
    description: str
    modules: List[str] = field(default_factory=list)
    limits: Dict[str, Any] = field(default_factory=dict)
    available: bool = True


class DroneAdapter(ABC):
    """Interfejs adaptera drona.

    Nowy adapter tworzy się przez podklasę, ustawienie ``id``/``name``/
    ``module_names`` i implementację metod poniżej, a następnie rejestrację
    przez :func:`register_adapter`.
    """

    #: unikalny identyfikator (np. ``"tello"``)
    id: str = ""
    #: nazwa wyświetlana w UI
    name: str = ""

    description: str = ""

    #: nazwy modułów biblioteki, które adapter podstawia w sandboxie
    module_names: Sequence[str] = ()

    @abstractmethod
    def limits(self) -> Dict[str, Any]:
        """Słownik limitów parametrów (do walidacji i wyświetlenia w UI)."""

    @abstractmethod
    def mock_root(self) -> Path:
        """Katalog, który ma trafić na początek ``sys.path`` sandboxu."""

    def runtime_modules(self) -> Sequence[str]:
        """Moduły posortowane wg kolejności uruchamiania w podprocesie."""
        return tuple(m for m in self.runtime_hooks() if m)

    def runtime_hooks(self) -> Sequence[str]:
        """Dodatkowe moduły (np. stan i mock konkretnej biblioteki)."""
        return ()

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            id=self.id, name=self.name, description=self.description,
            modules=list(self.module_names), limits=self.limits(),
        )

    def detect(self, source: str) -> int:
        """Ile punktów „pewności” daje ten adapter dla treści skryptu.

        Domyślnie: +10 za każdy import modułu z ``module_names``.
        """
        score = 0
        for module in self.module_names:
            if f"import {module}" in source or f"from {module}" in source:
                score += 10
        return score

    def prepare_sandbox(self, flight: FlightData, sim: Simulation,
                        config: Dict[str, Any]) -> Dict[str, Any]:
        """Przygotuj konfigurację sandboxu (ścieżki, hooki, mock).

        Zwraca słownik przekazywany do runnera; domyślnie: ``sys.path``
        z katalogiem mocka i listą hooków runtime.
        """
        return {
            "sandbox_paths": [str(self.mock_root())],
            "runtime_modules": list(self.runtime_modules()),
            "config": config,
        }


# ---------------------------------------------------------------- rejestr
_REGISTRY: Dict[str, Type[DroneAdapter]] = {}
_INSTANCES: Dict[str, DroneAdapter] = {}


def register_adapter(cls: Type[DroneAdapter]) -> Type[DroneAdapter]:
    """Dekorator rejestrujący klasę adaptera."""
    if not cls.id:
        raise ValueError("Adapter musi mieć niepuste pole 'id'.")
    _REGISTRY[cls.id] = cls
    return cls


def _import_builtin_adapters() -> None:
    """Zaimportuj wbudowane adaptery (rejestracja przez dekorator)."""
    importlib.import_module("app.adapters.tello.adapter")


def get_adapter(adapter_id: str) -> DroneAdapter:
    """Zwróć instancję adaptera o danym id (z cache)."""
    _import_builtin_adapters()
    if adapter_id not in _REGISTRY:
        raise KeyError(f"Nieznany adapter drona: {adapter_id!r}. "
                       f"Dostępne: {', '.join(sorted(_REGISTRY))}")
    if adapter_id not in _INSTANCES:
        _INSTANCES[adapter_id] = _REGISTRY[adapter_id]()
    return _INSTANCES[adapter_id]


def list_adapters() -> List[AdapterInfo]:
    """Lista wszystkich zarejestrowanych adapterów (dla UI)."""
    _import_builtin_adapters()
    return [get_adapter(aid).describe() for aid in sorted(_REGISTRY)]


def detect_adapter(source: str) -> DroneAdapter:
    """Wykryj adapter na podstawie importów w skrypcie (fallback: pierwszy)."""
    _import_builtin_adapters()
    best_id: Optional[str] = None
    best_score = 0
    for aid in sorted(_REGISTRY):
        score = get_adapter(aid).detect(source)
        if score > best_score:
            best_id, best_score = aid, score
    if best_id is None:
        best_id = sorted(_REGISTRY)[0]
    return get_adapter(best_id)
