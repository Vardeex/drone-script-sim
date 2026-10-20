@echo off
REM ===========================================================================
REM  Drone Script Simulator - start serwera + przegladarka
REM
REM  Ten plik zawiera sciezki MOJEJ lokalnej instalacji na dysku D:
REM  (Python 3.11 w D:\DroneSim\tools\Python311, cache i temp na D:).
REM  Na innym komputerze wystarczy setup.bat + start.bat (patrz README),
REM  a sposob uruchamiania opisuje sekcja "Uruchomienie".
REM ===========================================================================
setlocal

set "PROJECT_DIR=D:\DroneSim"
set "PORT=8765"

REM cache / tmp tylko w biezacej sesji - nic nie zostaje na C:
set "PIP_CACHE_DIR=D:\DroneSim\cache\pip"
set "TEMP=D:\DroneSim\tmp"
set "TMP=D:\DroneSim\tmp"

cd /d "%PROJECT_DIR%"

if exist ".venv\Scripts\python.exe" goto :venv_ok
echo Brak srodowiska .venv - uruchamiam setup.bat ...
call "%PROJECT_DIR%\setup.bat"
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

