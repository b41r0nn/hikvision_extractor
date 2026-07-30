"""
test_evidencia/setup_bd.py
Crea la BD de prueba (SQLite), corre Alembic, inicializa festivos/RBAC/config
y setea ultima_extraccion_exitosa a N dias atras.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "evidencia.db"))
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.pop("DEVICE_IP", None)  # usar default del .env

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command
from alembic.config import Config
from backend.database import SessionLocal
from backend.report_service import init_festivos
from backend.auth import init_rbac
from backend import config_service

alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
command.upgrade(alembic_cfg, "head")

db = SessionLocal()
try:
    init_festivos(db)
    init_rbac(db)
    config_service.init_defaults(db)
    # Setear ultima extraccion a N dias atras
    dias_atras = int(os.environ.get("DIAS_ATRAS", "3"))
    cuando = datetime.now(timezone.utc) - timedelta(days=dias_atras)
    config_service.set_ultima_extraccion(db, when=cuando)
    print(f"[SETUP] ultima_extraccion_exitosa = {cuando.isoformat()} (hace {dias_atras} dias)")
    # Contar registros previos
    from backend.models import RegistroAsistencia
    total_prev = db.query(RegistroAsistencia).count()
    print(f"[SETUP] registros previos en BD: {total_prev}")
finally:
    db.close()

print(f"[SETUP] BD lista en {DB_PATH}")
