"""
tests/test_api_endpoints.py
Tests de integración para los endpoints REST de FastAPI.

Mockea la ejecución de migraciones Alembic (que son PostgreSQL-específicas)
y el scheduler. Las tablas se crean directamente con Base.metadata.create_all
sobre SQLite en memoria.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base
from backend.database import get_db

# Motor SQLite con StaticPool para que todos los threads usen la misma BD
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def override_get_db():
    db = _TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    """
    TestClient que:
    - Sobreescribe SessionLocal para apuntar al mismo motor de test
    - Mockea alembic.command.upgrade (no necesario: tablas ya creadas)
    - Mockea start_scheduler para no arrancar APScheduler en tests
    - Mockea el backfill para no intentar conectar al biométrico
    """
    # Garantizar que SessionLocal en database.py apunte al motor de test
    import backend.database as _db_module
    original_engine = _db_module.engine
    original_SessionLocal = _db_module.SessionLocal

    _db_module.engine       = _engine
    _db_module.SessionLocal = _TestingSession

    with patch("alembic.command.upgrade"), \
         patch("backend.main.start_scheduler"), \
         patch("backend.main.acquire_extraction_lock", return_value=False):

        from backend.main import app
        app.dependency_overrides[get_db] = override_get_db

        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

        app.dependency_overrides.clear()

    # Restaurar engine original
    _db_module.engine       = original_engine
    _db_module.SessionLocal = original_SessionLocal


@pytest.fixture(scope="module")
def auth_token(client):
    """Crea roles, admin y devuelve token JWT válido."""
    db = _TestingSession()
    try:
        from backend.auth import init_rbac, get_password_hash
        from backend.models import Usuario, Rol
        from backend import config_service
        init_rbac(db)
        config_service.init_defaults(db)
        db.commit()

        if not db.query(Usuario).filter(Usuario.username == "testadmin").first():
            rol_admin = db.query(Rol).filter(Rol.nombre == "Admin").first()
            db.add(Usuario(
                username="testadmin",
                password_hash=get_password_hash("Test1234!"),
                rol_id=rol_admin.id,
                activo=True,
                requiere_cambio_password=False,
            ))
            db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/login", json={
        "username": "testadmin",
        "password": "Test1234!",
    })
    assert resp.status_code == 200, f"Login falló: {resp.text}"
    return resp.json()["access_token"]


# ── Endpoints públicos ───────────────────────────────────────────────────────

def test_root_retorna_mensaje(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "REDIHOS" in resp.json()["message"]


def test_health_retorna_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Autenticación ─────────────────────────────────────────────────────────────

def test_login_credenciales_invalidas(client):
    resp = client.post("/api/auth/login", json={
        "username": "noexiste",
        "password": "wrongpass",
    })
    assert resp.status_code == 401


def test_login_exitoso_retorna_token(client, auth_token):
    assert len(auth_token) > 20


def test_me_sin_token_retorna_401(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_con_token_retorna_usuario(client, auth_token):
    resp = client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testadmin"
    assert data["rol"] == "Admin"


# ── Validación de fechas en /api/extraer (#6) ─────────────────────────────────

def test_extraer_fecha_inicio_mayor_a_fin_retorna_400(client, auth_token):
    resp = client.post(
        "/api/extraer",
        json={"fecha_inicio": "2026-10-15", "fecha_fin": "2026-10-13"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400
    assert "mayor" in resp.json()["detail"]


def test_extraer_rango_mayor_365_dias_retorna_400(client, auth_token):
    resp = client.post(
        "/api/extraer",
        json={"fecha_inicio": "2024-01-01", "fecha_fin": "2026-12-31"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400
    assert "365" in resp.json()["detail"]


def test_extraer_formato_invalido_retorna_400(client, auth_token):
    resp = client.post(
        "/api/extraer",
        json={"fecha_inicio": "13/10/2026", "fecha_fin": "2026-10-13"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400


def test_extraer_rango_valido_inicia_extraccion(client, auth_token):
    with patch("backend.main.background_tasks") if False else \
         patch("backend.main.ejecutar_extraccion"):
        resp = client.post(
            "/api/extraer",
            json={"fecha_inicio": "2026-10-13", "fecha_fin": "2026-10-13"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    assert resp.status_code == 200
    assert "Extracción iniciada" in resp.json()["message"]


# ── Protección de endpoints ───────────────────────────────────────────────────

def test_empleados_sin_token_retorna_401(client):
    resp = client.get("/api/empleados")
    assert resp.status_code == 401


def test_roles_sin_token_retorna_401(client):
    resp = client.get("/api/roles")
    assert resp.status_code == 401


def test_reportes_sin_token_retorna_401(client):
    resp = client.post("/api/reportes/generar", json={
        "fecha_inicio": "2026-10-01",
        "fecha_fin": "2026-10-31",
    })
    assert resp.status_code == 401


# ── CRUD de roles ─────────────────────────────────────────────────────────────

def test_crear_y_listar_rol(client, auth_token):
    resp = client.post(
        "/api/roles",
        json={"nombre": "TestRol"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["nombre"] == "TestRol"

    resp_list = client.get(
        "/api/roles",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp_list.status_code == 200
    nombres = [r["nombre"] for r in resp_list.json()]
    assert "TestRol" in nombres


def test_crear_rol_duplicado_retorna_400(client, auth_token):
    client.post("/api/roles", json={"nombre": "RolDup"},
                headers={"Authorization": f"Bearer {auth_token}"})
    resp = client.post("/api/roles", json={"nombre": "RolDup"},
                       headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 400


# ── CRUD de usuarios ──────────────────────────────────────────────────────────

def test_listar_usuarios(client, auth_token):
    resp = client.get("/api/usuarios",
                      headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_crear_usuario(client, auth_token):
    db = _TestingSession()
    try:
        from backend.models import Rol
        rol = db.query(Rol).filter(Rol.nombre == "Reportes").first()
        rol_id = rol.id
    finally:
        db.close()

    resp = client.post(
        "/api/usuarios",
        json={"username": "nuevouser", "password": "Pass123!", "rol_id": rol_id},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == "nuevouser"
