"""
preparar_bd_prueba_migracion.py
Prepara una BD SQLite de prueba que simula el backup de producción:
- Schema actual (turnos, empleados, turno_horario) via Alembic upgrade head.
- 71 empleados con turno_id IS NULL.

Uso:
  python test_evidencia/preparar_bd_prueba_migracion.py
Genera:
  test_evidencia/migracion_prueba.db
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Empleado

DB_PATH = os.path.join(os.path.dirname(__file__), "migracion_prueba.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

os.environ["DATABASE_URL"] = DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Correr migraciones
alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
command.upgrade(alembic_cfg, "head")
print("[PREPARAR] Migraciones aplicadas")

# Insertar 71 empleados con turno_id NULL
db = SessionLocal()
try:
    for i in range(1, 72):
        db.add(Empleado(
            employee_id=str(1000 + i),
            nombre=f"Empleado Prueba {i}",
            departamento="Administrativo",
            turno_id=None,
            activo=True,
        ))
    db.commit()
    print("[PREPARAR] 71 empleados insertados con turno_id=NULL")
finally:
    db.close()

print(f"[PREPARAR] BD lista: {DB_PATH}")
