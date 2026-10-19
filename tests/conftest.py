"""
tests/conftest.py
Fixtures compartidos para toda la suite de tests.

Usa SQLite en memoria para no requerir PostgreSQL en CI/local.
Las variables de entorno se fijan ANTES de importar cualquier módulo
del backend para evitar que database.py falle al conectar.
"""
import os

# ── Variables de entorno deben estar antes de cualquier import del backend ──
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_chars_exactly!")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DEVICE_IP", "127.0.0.1")
os.environ.setdefault("DEVICE_USER", "admin")
os.environ.setdefault("DEVICE_PASS", "test_password")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "Admin123!")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")

import pytest
from datetime import date, time
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base


# ── Motor SQLite en memoria ──────────────────────────────────────────────────
@pytest.fixture(scope="session")
def engine():
    _engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Activar FKs en SQLite
    @sa_event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_con, _):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(_engine)
    return _engine


@pytest.fixture
def db(engine):
    """Sesión de BD con rollback automático al finalizar cada test."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ── Datos de muestra ─────────────────────────────────────────────────────────
@pytest.fixture
def turno_muestra(db):
    from backend.models import Turno, TurnoHorario
    turno = Turno(
        nombre="Turno General",
        hora_entrada=time(8, 0),
        tolerancia_minutos=10,
    )
    db.add(turno)
    db.flush()
    for dia in range(5):
        db.add(TurnoHorario(
            turno_id=turno.id,
            dia_semana=dia,
            hora_entrada=time(8, 0),
            tolerancia_minutos=10,
            vigente_desde=date(2026, 1, 1),
        ))
    db.flush()
    return turno


@pytest.fixture
def empleado_muestra(db, turno_muestra):
    from backend.models import Empleado
    emp = Empleado(
        employee_id="EMP001",
        nombre="Juan Perez",
        departamento="Sistemas",
        turno_id=turno_muestra.id,
        activo=True,
        hora_entrada=time(8, 0),
        tolerancia_minutos=10,
    )
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def registro_muestra(db, empleado_muestra):
    from backend.models import RegistroAsistencia
    reg = RegistroAsistencia(
        empleado_id=empleado_muestra.employee_id,
        nombre_empleado=empleado_muestra.nombre,
        fecha=date(2026, 10, 13),   # Lunes
        hora=time(8, 15),
        tipo_evento="Fingerprint Recognition Passed",
        evento_raw="2026-10-13T08:15:00",
    )
    db.add(reg)
    db.flush()
    return reg
