@echo off
REM Arranca el backend en background apuntando a la BD de prueba para la
REM verificacion de la alerta extraccion_incompleta_dias.
setlocal
cd /d "%~dp0\.."
set "DATABASE_URL=sqlite:///%~dp0evidencia.db"
set "PYTHONUNBUFFERED=1"
start /b "" ".\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 18002 --log-level info > "%~dp0logs\test_alerta_18002.log" 2>&1
echo Proceso lanzado. Revisa logs\test_alerta_18002.log
