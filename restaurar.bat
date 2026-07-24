@echo off
REM restaurar.bat
REM Restaura el proyecto al checkpoint v0.0 (version inicial funcional pre-fixes).
REM ATENCION: descarta todos los cambios locales no commiteados.

cd /d "%~dp0"

echo.
echo ============================================
echo   Restaurando a v0.0
echo ============================================
echo.

git reset --hard v0.0
if errorlevel 1 (
    echo.
    echo ERROR: no se pudo restaurar. Verifica que el tag exista con:
    echo     git tag
    echo.
    pause
    exit /b 1
)

echo.
echo Restaurado correctamente a v0.0.
echo.
echo RECORDATORIO: tu archivo .env no esta en el repo.
echo Si necesitas restaurarlo, copialo desde tu backup.
echo.
pause
