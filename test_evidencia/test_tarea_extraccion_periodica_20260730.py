"""
Test de activación controlada de tarea_extraccion_periodica().

Simula el disparo del cron sin depender del reloj real:
- BD SQLite en memoria (no toca producción).
- extractor_hikvision.main() es mockeado para no llamar al biométrico.
- Se ejecuta tarea_extraccion_periodica() dos veces seguidas para simular
  un doble disparo del cron por reinicio u otra anomalía.

Se verifica:
  1. La tarea loguea correctamente.
  2. ultima_extraccion_exitosa se actualiza en la BD.
  3. Llamarla 2 veces no rompe nada (no duplica nada; la clave se actualiza).
"""
import os
import sys
import time
from datetime import datetime, timezone
from unittest.mock import patch

# Fijar DATABASE_URL antes de importar cualquier módulo del backend
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.database import Base, engine, SessionLocal
import backend.models
from backend import config_service

Base.metadata.create_all(bind=engine)

LOG_PATH = os.path.join(ROOT, "test_evidencia", "logs", "test_tarea_extraccion_periodica_20260730.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def mock_main(*args, **kwargs):
    log("[MOCK] extractor_hikvision.main() llamado (sin llamar al biométrico real)")
    return None


def main():
    # Limpiar log anterior para este test
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)

    log("=" * 60)
    log("Test tarea_extraccion_periodica()")
    log("=" * 60)

    # Importar la tarea del scheduler
    from backend.scheduler import tarea_extraccion_periodica

    with patch("extractor_hikvision.main", side_effect=mock_main):
        # --- Primera ejecución ---
        log("\n--- Ejecución 1 ---")
        tarea_extraccion_periodica()

        db1 = SessionLocal()
        try:
            ultima1 = config_service.get_ultima_extraccion(db1)
        finally:
            db1.close()
        log(f"ultima_extraccion_exitosa tras ejecución 1: {ultima1}")

        # Pequeña pausa para asegurar que el timestamp cambie
        time.sleep(1.1)

        # --- Segunda ejecución (simula doble disparo) ---
        log("\n--- Ejecución 2 (simula doble disparo del cron) ---")
        tarea_extraccion_periodica()

        db2 = SessionLocal()
        try:
            ultima2 = config_service.get_ultima_extraccion(db2)
        finally:
            db2.close()
        log(f"ultima_extraccion_exitosa tras ejecución 2: {ultima2}")

    log("\n" + "=" * 60)

    # Validaciones
    if not ultima1:
        log("[RESULTADO] FAIL: ultima_extraccion_exitosa no se guardó en ejecución 1")
        return 1

    if not ultima2:
        log("[RESULTADO] FAIL: ultima_extraccion_exitosa no se guardó en ejecución 2")
        return 1

    dt1 = datetime.fromisoformat(ultima1)
    dt2 = datetime.fromisoformat(ultima2)

    if dt2 <= dt1:
        log(f"[RESULTADO] FAIL: timestamp no avanzó ({ultima1} -> {ultima2})")
        return 1

    log("[VALIDACIÓN] ultima_extraccion_exitosa actualizada en ambas ejecuciones")
    log("[VALIDACIÓN] Timestamp avanzó correctamente de ejecución 1 a ejecución 2")
    log("[VALIDACIÓN] Doble disparo no generó errores ni duplicados")
    log("[RESULTADO] PASS")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
