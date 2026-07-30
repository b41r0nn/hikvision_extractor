"""
Evidencia funcionalidad: configuración SMTP editable desde Admin.
Corre contra el backend local corriendo en http://localhost:8000.
"""
import os
import sys
import requests

# Agregar backend al path para probar crypto directamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

API = "http://localhost:8000/api"
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Ingreso2026*")




def login() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def test_encriptacion_no_expone_password():
    """Prueba 1: encriptar/desencriptar y verificar que en BD no está en claro."""
    from backend.crypto_service import encriptar, desencriptar
    from backend.database import SessionLocal
    from backend.models import ConfiguracionCorreo

    password = "MiPasswordSecreto123"
    token = encriptar(password)
    assert token != password
    assert desencriptar(token) == password

    # Guardar a mano en BD y leer raw
    db = SessionLocal()
    try:
        cfg = ConfiguracionCorreo(
            id=1,
            host="smtp.ejemplo.com",
            puerto=587,
            usuario="usuario@ejemplo.com",
            password_encriptado=token,
            remitente_nombre="Test",
            seguridad="starttls",
        )
        db.merge(cfg)
        db.commit()

        raw = db.query(ConfiguracionCorreo.password_encriptado).filter(ConfiguracionCorreo.id == 1).scalar()
        assert raw != password, "El password NO debe guardarse en texto plano en la BD"
        assert "MiPasswordSecreto" not in raw
        print("PASS: password encriptado en BD; desencriptado coincide")
    finally:
        db.close()


def test_get_no_devuelve_password(token: str):
    """Prueba 2: GET /api/config/correo no incluye password."""
    r = requests.get(
        f"{API}/config/correo",
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    data = r.json()
    assert "password" not in data, f"La respuesta expuso password: {data.keys()}"
    assert "password_configurado" in data
    print(f"PASS: GET /api/config/correo no devuelve password. Response: {data}")


def test_put_password_vacio_no_pisa(token: str):
    """Prueba 3: PUT con password vacío conserva el password existente."""
    # Cambiamos solo el host, sin enviar password
    r = requests.put(
        f"{API}/config/correo",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "host": "smtp.modificado.com",
            "puerto": 465,
            "usuario": "usuario@ejemplo.com",
            "password": "",
            "remitente_nombre": "Test Modificado",
            "seguridad": "ssl",
        },
    )
    r.raise_for_status()

    # Verificar en BD que el password sigue siendo el mismo encriptado
    from backend.database import SessionLocal
    from backend.models import ConfiguracionCorreo
    from backend.crypto_service import desencriptar

    db = SessionLocal()
    try:
        cfg = db.query(ConfiguracionCorreo).filter(ConfiguracionCorreo.id == 1).first()
        assert cfg.host == "smtp.modificado.com"
        assert desencriptar(cfg.password_encriptado) == "MiPasswordSecreto123"
        print("PASS: PUT con password vacío no pisó el password existente")
    finally:
        db.close()


def test_migracion_upgrade_downgrade():
    """Prueba 4: upgrade/downgrade/upgrade de la migración."""
    import subprocess
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://admin:adminpassword@localhost:5432/hikvision"

    python_exe = sys.executable
    for cmd, label in [
        ([python_exe, "-m", "alembic", "upgrade", "head"], "upgrade"),
        ([python_exe, "-m", "alembic", "downgrade", "-1"], "downgrade"),
        ([python_exe, "-m", "alembic", "upgrade", "head"], "upgrade final"),
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        print(f"--- {label} ---")
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
            raise AssertionError(f"{label} falló")
    print("PASS: migración upgrade/downgrade/upgrade")


if __name__ == "__main__":
    print("Iniciando tests de evidencia config correo...")
    test_encriptacion_no_expone_password()
    tk = login()
    test_get_no_devuelve_password(tk)
    test_put_password_vacio_no_pisa(tk)
    test_migracion_upgrade_downgrade()
    print("\nTodos los tests de evidencia PASS")
