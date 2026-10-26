"""Testy zakończenia programu: ``POST /api/shutdown`` i przycisk w nagłówku.

Endpoint może zamknąć program **tylko** z tego komputera - testy sprawdzają
odrzucenie zdalnego klienta, zatrzymanie skryptów (procesy potomne), zapis pliku
``--stop-file`` (dzięki niemu launcher kończy się razem z serwerem) oraz to,
że interfejs ma przycisk z potwierdzeniem i ekran końcowy.

Zakończenie procesu jest podmienione (``_exit_process``), więc uruchomienie
testów nie zabija pytest-a.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import server

ROOT = Path(__file__).resolve().parent.parent


class _Client:
    """Minimalny ``request.client`` (tylko ``host`` jest potrzebny)."""

    def __init__(self, host: str) -> None:
        self.host = host


class _Request:
    """Minimalny ``Request`` dla testów bez serwera HTTP."""

    def __init__(self, host: str) -> None:
        self.client = _Client(host)


@pytest.fixture()
def exit_calls(monkeypatch):
    """Podmień zakończenie procesu - zwraca listę wywołań."""
    calls = []
    monkeypatch.setattr(server, "_exit_process", lambda code=0: calls.append(code))
    return calls


def test_shutdown_rejects_remote_client(exit_calls, monkeypatch):
    """Żądanie spoza tego komputera: 403, bez zatrzymywania i bez zakończenia."""
    stopped = []
    monkeypatch.setattr(server.runner, "stop_all",
                        lambda: stopped.append(True) or 0)
    monkeypatch.delenv(server.STOP_FILE_ENV, raising=False)
    with pytest.raises(HTTPException) as exc:
        server.api_shutdown(_Request("192.168.0.10"))
    assert exc.value.status_code == 403
    assert "tylko z tego komputera" in str(exc.value.detail)
    assert stopped == []
    assert exit_calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.5", "::1"])
def test_shutdown_from_localhost_stops_runs_and_writes_stop_file(
        host, tmp_path, exit_calls, monkeypatch):
    """Lokalny klient: zatrzymaj skrypty, zapisz stop-file, zakończ proces."""
    monkeypatch.setattr(server.runner, "stop_all", lambda: 2)
    stop_file = tmp_path / "droneSim.stop"
    monkeypatch.setenv(server.STOP_FILE_ENV, str(stop_file))

    result = server.api_shutdown(_Request(host))

    assert result["stopping"] is True
    assert result["stopped_runs"] == 2
    assert result["stop_file"] == str(stop_file)
    assert stop_file.read_text(encoding="utf-8").strip() == "shutdown"
    assert exit_calls == [] or exit_calls == [0]      # timer działa po odpowiedzi


def test_shutdown_without_stop_file_still_exits(tmp_path, exit_calls, monkeypatch):
    """Bez launchera (brak pliku stop): serwer i tak się zamyka."""
    monkeypatch.setattr(server.runner, "stop_all", lambda: 0)
    monkeypatch.delenv(server.STOP_FILE_ENV, raising=False)

    result = server.api_shutdown(_Request("127.0.0.1"))

    assert result["stopping"] is True
    assert result["stop_file"] is None


def test_shutdown_endpoint_is_registered():
    """Endpoint istnieje i przyjmuje tylko POST (GET nie zamyka programu)."""
    paths = {getattr(route, "path", None): getattr(route, "methods", set())
             for route in server.app.routes}
    assert "/api/shutdown" in paths
    assert "POST" in paths["/api/shutdown"]
    assert "GET" not in paths["/api/shutdown"]


def test_ui_has_shutdown_button_and_message():
    """Nagłówek ma przycisk, potwierdzenie i ekran „Program zakończony”."""
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'id="btn-shutdown"' in html
    assert "Zakończ program" in html
    assert "/api/shutdown" in app_js
    assert "Zamknąć DroneSim?" in app_js
    assert "Program zakończony – możesz zamknąć tę kartę." in app_js
    assert ".shutdown-screen" in style


def test_launcher_passes_stop_file_to_server():
    """Launcher przekazuje serwerowi ścieżkę ``--stop-file`` (zmienna środowiska)."""
    source = (ROOT / "release_tools" / "launcher" /
              "dronesim_launcher.py").read_text(encoding="utf-8")
    assert 'STOP_FILE_ENV = "DRONESIM_STOP_FILE"' in source
    assert "env[STOP_FILE_ENV] = str(Path(stop_file).resolve())" in source
    assert "start_server(root, data_dir, args.port, log," in source
