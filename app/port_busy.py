"""Sprawdz, czy port lokalny jest juz zajety (uzywane przez start.bat).

Kod wyjscia: 0 = port zajety (serwer juz dziala), 1 = port wolny.

Dwa procesy uvicorn na tym samym porcie potrafia serwowac rozne wersje plikow
statycznych, dlatego start.bat nie uruchamia drugiego serwera.

Uruchomienie: python app/port_busy.py 8765
"""

from __future__ import annotations

import socket
import sys

DEFAULT_PORT = 8765


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    """True, jesli na host:port ktos nasluchuje."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main(argv: list[str]) -> int:
    port = int(argv[1]) if len(argv) > 1 else DEFAULT_PORT
    busy = port_busy(port)
    print(f"port {port}: {'zajety' if busy else 'wolny'}")
    return 0 if busy else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
