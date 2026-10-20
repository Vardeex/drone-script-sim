@echo off
REM ===========================================================================
REM  Drone Script Simulator - start serwera + przegladarka
REM  UWAGA: ten plik zawiera sciezki mojej lokalnej instalacji na dysku D:
REM  (Python 3.11 zainstalowany poza systemowym PATH oraz katalog cache/tmp).
REM  Na innym komputerze uruchom najpierw setup.bat - patrz README.
REM ===========================================================================
setlocal

set "PROJECT_DIR=D:\DroneSim"
set "PYTHON=D:\DroneSim\tools\Python311\python.exe"

REM cache / tmp tylko w biezacej sesji - nic nie zostaje na C:
set "PIP_CACHE_DIR=D:\DroneSim\cache\pip"
set "TEMP=D:\DroneSim\tmp"
set "TMP=D:\DroneSim\tmp"

cd /d "%PROJECT_DIR%"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo Brak srodowiska .venv - uruchamiam setup.bat ...
    call "%PROJECT_DIR%\setup.bat"
    if errorlevel 1 exit /b 1
    set "PYTHON=.venv\Scripts\python.exe"
)

echo Uruchamiam Drone Script Simulator na http://127.0.0.1:8765 ...
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8765/"

"%PYTHON%" -m uvicorn app.server:app --host 127.0.0.1 --port 8765

endlocal
