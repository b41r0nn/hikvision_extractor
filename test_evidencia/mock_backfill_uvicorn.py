"""
test_evidencia/mock_backfill_uvicorn.py
Wrapper que mockea extractor_hikvision.main para que el backfill del
lifespan procese 5 dias lentamente (sin dispositivo real), y luego
levanta uvicorn en el puerto 18003 apuntando a backfill_resume.db.
"""
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.abspath(os.path.join(ROOT, "test_evidencia", "backfill_resume.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["PYTHONUNBUFFERED"] = "1"

# Mock del extractor: procesa dia por dia, inserta 1 registro, actualiza
# ultima_extraccion_exitosa a ese dia, y duerme 10s para permitir matar
# el proceso a mitad de camino.
import extractor_hikvision
from backend.database import SessionLocal
from backend.models import RegistroAsistencia
from backend import config_service


def fake_main(start_str=None, end_str=None, progress_callback=None):
    start = date.fromisoformat(start_str) if start_str else date.today()
    end = date.fromisoformat(end_str) if end_str else date.today()
    current = start
    db = SessionLocal()
    try:
        while current <= end:
            msg = f"[MOCK EXTRACTOR] Procesando {current}..."
            print(msg)
            if progress_callback:
                progress_callback(msg)

            # Insertar 1 registro de prueba para ese dia
            reg = RegistroAsistencia(
                empleado_id="999",
                nombre_empleado="Empleado Mock",
                fecha=current,
                hora=datetime.now().time(),
                tipo_evento="Mock Authentication",
                evento_raw=f"mock-{current.isoformat()}",
            )
            db.add(reg)

            # Commit del dia (simula el comportamiento real dia por dia)
            db.commit()

            # Actualizar ultima_extraccion_exitosa a este dia
            when = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)
            config_service.set_ultima_extraccion(db, when=when)
            ultima = config_service.get_ultima_extraccion(db)
            msg_ok = f"[MOCK EXTRACTOR] {current} commiteado. ultima_extraccion_exitosa={ultima}"
            print(msg_ok)
            if progress_callback:
                progress_callback(msg_ok)

            # Dormir para permitir matar el proceso a mitad
            time.sleep(10)
            current += timedelta(days=1)
    finally:
        db.close()

    msg_fin = f"[MOCK EXTRACTOR] Extraccion completada {start} -> {end}"
    print(msg_fin)
    if progress_callback:
        progress_callback(msg_fin)


extractor_hikvision.main = fake_main

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=18003, log_level="info")
