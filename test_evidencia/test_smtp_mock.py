"""
Evidencia: POST /api/config/correo/test con smtplib mockeado.
Usa TestClient para poder parchear smtplib en el proceso del backend.
"""
import os
import sys
from unittest.mock import patch, MagicMock

# Normalizar DATABASE_URL para correr desde el host
_db_url = os.getenv("DATABASE_URL", "")
if "@db:" in _db_url:
    os.environ["DATABASE_URL"] = _db_url.replace("@db:", "@localhost:")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import ConfiguracionCorreo
from backend.crypto_service import encriptar

client = TestClient(app)
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Ingreso2026*")


def login() -> str:
    r = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def crear_config():
    db = SessionLocal()
    try:
        cfg = ConfiguracionCorreo(
            id=1,
            host="smtp.ejemplo.com",
            puerto=587,
            usuario="test@ejemplo.com",
            password_encriptado=encriptar("password123"),
            remitente_nombre="Test",
            seguridad="starttls",
        )
        db.merge(cfg)
        db.commit()
    finally:
        db.close()


def test_envio_exitoso():
    token = login()
    crear_config()

    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        r = client.post(
            "/api/config/correo/test",
            json={"destinatario": "destino@ejemplo.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        print("Respuesta exitosa:", r.status_code, r.json())
        assert r.status_code == 200
        assert "enviado" in r.json()["message"].lower()
        assert mock_smtp.called


def test_error_smtp_real():
    token = login()
    crear_config()

    import smtplib
    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        instance.starttls.side_effect = smtplib.SMTPConnectError(421, "No se pudo conectar al servidor SMTP")

        r = client.post(
            "/api/config/correo/test",
            json={"destinatario": "destino@ejemplo.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        print("Respuesta error:", r.status_code, r.json())
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "Error SMTP" in detail
        assert "No se pudo conectar" in detail


if __name__ == "__main__":
    test_envio_exitoso()
    test_error_smtp_real()
    print("\nTests SMTP mock PASS")
