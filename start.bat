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
echo Uruchamiam Drone Script Simulator na http://127.0.0.1:%PORT% ...
echo (zamkniecie tego okna zatrzymuje serwer)
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%/"

".venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port %PORT%
goto :end

:error
echo BLAD: nie udalo sie przygotowac srodowiska.
pause

:end
endlocal

