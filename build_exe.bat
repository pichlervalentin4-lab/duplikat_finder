@echo off
REM Baut Duplikat-Finder.exe unter Windows (braucht einmalig Python 3.10+ von python.org)
pushd "%~dp0" || exit /b 1
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (%PY% -m venv .venv || goto fehler)
call .venv\Scripts\activate.bat || goto fehler
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto fehler
pyinstaller --noconfirm --onefile --windowed --name Duplikat-Finder --collect-data customtkinter app.py || goto fehler
echo.
echo Fertig: dist\Duplikat-Finder.exe
popd
pause
exit /b 0
:fehler
echo.
echo FEHLER: Der Build hat nicht geklappt, siehe Meldungen oben.
popd
pause
exit /b 1
