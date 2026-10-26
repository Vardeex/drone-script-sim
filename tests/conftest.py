"""Wspólna konfiguracja testów - dodaje katalog projektu do ``sys.path``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: ``DRONESIM_TEST_LITE=1`` - cały zestaw przeglądarkowy działa w trybie lekkim
LITE_ENV = "DRONESIM_TEST_LITE"


@pytest.fixture(scope="session", autouse=True)
def force_lite_mode():
    """Uruchom testy przeglądarkowe w trybie lekkim (parametr całego zestawu).

    Tryb lekki włącza się w aplikacji z ``localStorage`` (klucz
    ``dronesim.perf:standard`` - z edycją wydania), więc wystarczy wstrzyknąć tę
    wartość przed wczytaniem strony - bez zmian w adresach URL i w wywołaniach API
    w testach. Dzięki temu **każdy** test przeglądarkowy (także przyszły)
    przechodzi w obu trybach: wystarczy uruchomić pytest drugi raz z
    ``DRONESIM_TEST_LITE=1``.
    """
    if os.environ.get(LITE_ENV) != "1":
        yield
        return
    try:
        from playwright.sync_api import BrowserContext
    except ImportError:                          # brak Playwrighta - nic nie rób
        yield
        return
    with pytest.MonkeyPatch.context() as patch:
        original = BrowserContext.new_page

        def new_page(self, *args, **kwargs):
            page = original(self, *args, **kwargs)
            page.add_init_script(
                "try { localStorage.setItem('dronesim.perf:standard', 'lite'); }"
                " catch (e) { /* brak storage */ }")
            return page

        patch.setattr(BrowserContext, "new_page", new_page)
        yield
