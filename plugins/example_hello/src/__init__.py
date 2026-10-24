"""Przykładowa wtyczka zewnętrzna: panel z tekstem + endpoint API.

Struktura katalogu (wzór dla własnych wtyczek)::

    plugins/example_hello/
      plugin.json          # manifest: id, wersja, zależności, punkty rozszerzeń
      src/__init__.py      # pakiet Pythona wtyczki
      src/router.py        # APIRouter - endpointy pod api_prefix
      static/panel.js      # panel UI (registerPanel)
      static/panel.css     # style doładowywane przy starcie

Wtyczka nie importuje rdzenia aplikacji - dostaje od niego tylko to, co
przekazuje publiczne API (patrz ``docs/plugins.md``).
"""
