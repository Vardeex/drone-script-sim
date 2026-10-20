@echo off
REM ===========================================================================
REM  Drone Script Simulator - start serwera + przegladarka
REM
REM  Dziala z katalogu projektu (dowolna lokalizacja). Jesli srodowisko
REM  .venv nie istnieje, uruchamia setup.bat.
REM
REM  Opcjonalne zmienne (tylko biezaca sesja, nie zapisywane w systemie):
REM    PIP_CACHE_DIR - katalog cache pip
REM    TEMP / TMP    - katalog plikow tymczasowych
REM    PYTHON_EXE    - interpreter uzyty przez setup.bat
REM ===========================================================================
setlocal

cd /d "%~dp0"
set "PORT=8765"

if exist ".venv\Scripts\python.exe" goto :venv_ok
echo Brak srodowiska .venv - uruchamiam setup.bat ...
call "%~dp0setup.bat"
if errorlevel 1 goto :error

:venv_ok
REM Jeden serwer na raz: jesli port jest juz zajety, tylko otwieramy przegladarke
REM (drugi proces uvicorn serwowalby stara wersje plikow statycznych).
".venv\Scripts\python.exe" "%~dp0app\port_busy.py" %PORT%
if not errorlevel 1 goto :already_running

echo Uruchamiam Drone Script Simulator na http://127.0.0.1:%PORT% ...
echo (zamkniecie tego okna zatrzymuje serwer)
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%/"

".venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port %PORT%
goto :end

:already_running
echo Serwer juz dziala na http://127.0.0.1:%PORT% - otwieram przegladarke.
echo (nie uruchamiam drugiego procesu)
start "" "http://127.0.0.1:%PORT%/"
timeout /t 3 /nobreak >nul
goto :end

:error
echo BLAD: nie udalo sie przygotowac srodowiska.
pause

:end
endlocal

