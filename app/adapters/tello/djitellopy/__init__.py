"""Pakiet Tello - mock biblioteki ``djitellopy`` dla symulatora.

Ten katalog (``app/adapters/tello``) jest wstawiany na początek ``sys.path``
podprocesu skryptu, więc ``from djitellopy import Tello`` trafia tutaj, a nie
do prawdziwej biblioteki. Prawdziwe ``djitellopy`` nie jest w ogóle używane.

API odwzorowuje publiczne metody klasy ``djitellopy.Tello`` z takimi samymi
nazwami i sygnaturami; wywołania tłumaczy
:class:`app.adapters.tello.adapter.TelloController` na działania symulacji.
"""

from __future__ import annotations

__version__ = "2.5.0-sim"

from .tello import Tello, TelloException  # noqa: E402  (świadomie po __version__)

__all__ = ["Tello", "TelloException", "__version__"]


def available() -> bool:
    """Marker mocka: prawdziwe djitellopy udostępnia ``Tello`` z prawdziwym SDK."""
    return False
