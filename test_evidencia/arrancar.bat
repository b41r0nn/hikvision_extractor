@echo off
REM Inicia el backend en background con la BD de prueba y captura logs
setlocal
cd /d "%~dp0\.."
set "DATABASE_URL=sqlite:///%~dp0evidencia.db"
set "PYTHONUNBUFFERED=1"
start /b "" ".\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 18000 --log-level info > "%~dp0logs\test_positivo.log" 2>&1
echo Proceso lanzado. PID en log.
