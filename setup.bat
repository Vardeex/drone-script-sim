@echo off
REM ===========================================================================
REM  Drone Script Simulator - konfiguracja srodowiska (przenosny)
REM  Wymagany: Python 3.11+ dostepny jako "python" w PATH (lub ustaw PYTHON_EXE).
REM  Skrypt tworzy .venv w katalogu projektu i instaluje requirements.txt.
REM ===========================================================================
setlocal

cd /d "%~dp0"

if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo [1/3] Sprawdzam Pythona...
"%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 goto :no_python

if not exist ".venv\Scripts\python.exe" goto :make_venv
echo [2/3] Srodowisko .venv juz istnieje - pomijam tworzenie.
goto :install

:make_venv
echo [2/3] Tworze srodowisko wirtualne .venv ...
"%PYTHON_EXE%" -m venv ".venv"
if errorlevel 1 goto :venv_error

:install
echo [3/3] Instaluje zaleznosci z requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_error

echo.
echo Gotowe. Uruchom start.bat
endlocal
exit /b 0

:no_python
echo BLAD: Nie znaleziono Pythona 3.11+ ^("%PYTHON_EXE%"^).
echo Zainstaluj Python 3.11+ i dodaj go do PATH albo ustaw PYTHON_EXE, np.:
echo     set PYTHON_EXE=C:\sciezka\do\python.exe
echo     setup.bat
endlocal
exit /b 1

:venv_error
echo BLAD: nie udalo sie utworzyc venv.
endlocal
exit /b 1

:pip_error
echo BLAD: instalacja zaleznosci nie powiodla sie.
endlocal
exit /b 1
