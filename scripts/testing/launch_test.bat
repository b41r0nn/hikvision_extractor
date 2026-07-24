@echo off
setlocal
set "ROOT=%~dp0\.."
set "WD=C:\Users\Sistemas\OneDrive - REPRESENTACIONES Y DISTRIBUCIONES HOSPITALARIAS S.A.S REDIHOS\Escritorio\Vscode\hikvision_extractor"
set "PY=%WD%\.venv\Scripts\python.exe"
set "LOG=%~1"
set "PORT=%~2"
set "DEVICE_IP=%~3"
set "DB_URL=sqlite:///%WD%\test_evidencia\evidencia.db"

set "DATABASE_URL=%DB_URL%"
set "PYTHONUNBUFFERED=1"

cd /d "%WD%"
"%PY%" -u "%WD%\scripts\testing\run_with_timestamps.py" "%LOG%" "%PY%" -u -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT% --log-level info
