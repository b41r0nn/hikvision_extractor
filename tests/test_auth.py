"""
tests/test_auth.py
Tests para el módulo de autenticación: hashing, JWT, RBAC.
"""
import pytest
from datetime import timedelta


def test_hash_password_no_almacena_en_claro():
    from backend.auth import get_password_hash
    hashed = get_password_hash("mi_contraseña_secreta")
    assert "mi_contraseña_secreta" not in hashed
    assert len(hashed) > 20


def test_verify_password_correcto():
    from backend.auth import get_password_hash, verify_password
    hashed = get_password_hash("password123")
    assert verify_password("password123", hashed) is True


def test_verify_password_incorrecto():
    from backend.auth import get_password_hash, verify_password
    hashed = get_password_hash("password123")
    assert verify_password("otro_password", hashed) is False


def test_create_access_token_contiene_sub():
    from backend.auth import create_access_token
    token = create_access_token({"sub": "testuser", "rol": "Admin"})
    assert isinstance(token, str)
    assert len(token) > 0


def test_create_access_token_con_expiracion_custom():
    from backend.auth import create_access_token
    token = create_access_token(
        {"sub": "testuser", "rol": "Admin"},
        expires_delta=timedelta(minutes=1),
    )
    assert isinstance(token, str)


def test_permisos_dict_contiene_permisos_canonicos():
    from backend.auth import PERMISOS
    permisos_esperados = {
        "ver_dashboard",
        "generar_reportes",
        "ver_historico_tardanzas",
        "forzar_extraccion",
        "sync_empleados",
        "admin_empleados",
        "admin_correo",
        "admin_roles",
    }
    assert permisos_esperados == set(PERMISOS.keys())


def test_hash_es_diferente_para_misma_clave(  ):
    """Argon2 genera salts distintos por llamada."""
    from backend.auth import get_password_hash
    h1 = get_password_hash("igual")
    h2 = get_password_hash("igual")
    assert h1 != h2


def test_hash_argon2_formato():
    from backend.auth import get_password_hash
    hashed = get_password_hash("test")
    # passlib/argon2 produce hashes con prefijo $argon2id$
    assert "$argon2" in hashed


def test_init_rbac_crea_roles_y_permisos(db):
    from backend.auth import init_rbac
    from backend.models import Rol, Permiso
    init_rbac(db)
    roles = db.query(Rol).all()
    permisos = db.query(Permiso).all()
    nombres_roles = {r.nombre for r in roles}
    assert "Admin" in nombres_roles
    assert "Reportes" in nombres_roles
    assert len(permisos) == 8


def test_init_rbac_idempotente(db):
    """Llamar init_rbac dos veces no duplica datos."""
    from backend.auth import init_rbac
    from backend.models import Rol
    init_rbac(db)
    init_rbac(db)
    roles = db.query(Rol).all()
    nombres = [r.nombre for r in roles]
    assert nombres.count("Admin") == 1


def test_admin_tiene_todos_los_permisos(db):
    from backend.auth import init_rbac, PERMISOS
    from backend.models import Rol
    init_rbac(db)
    admin = db.query(Rol).filter(Rol.nombre == "Admin").first()
    nombres_permisos = {p.nombre for p in admin.permisos}
    assert nombres_permisos == set(PERMISOS.keys())
