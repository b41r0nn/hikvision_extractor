"""
config_correo_service.py
Gestión persistente de la configuración SMTP del sistema.
La contraseña se almacena encriptada con Fernet en la base de datos.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from .models import ConfiguracionCorreo, Usuario
from .crypto_service import encriptar, desencriptar
from .timezone import ahora_bogota


CONFIG_CORREO_ID = 1


def get_config(db: Session) -> Optional[ConfiguracionCorreo]:
    """Devuelve la fila de configuración de correo (única) o None."""
    return db.query(ConfiguracionCorreo).filter(ConfiguracionCorreo.id == CONFIG_CORREO_ID).first()


def get_config_segura(db: Session) -> Optional[dict]:
    """Devuelve la configuración sin nunca exponer el password en claro."""
    cfg = get_config(db)
    if not cfg:
        return None
    updated_by_username = None
    if cfg.updated_by_user:
        updated_by_username = cfg.updated_by_user.username
    return {
        "host": cfg.host,
        "puerto": cfg.puerto,
        "usuario": cfg.usuario,
        "remitente_nombre": cfg.remitente_nombre,
        "seguridad": cfg.seguridad,
        "password_configurado": bool(cfg.password_encriptado),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by": updated_by_username,
    }


def get_config_desencriptada(db: Session) -> Optional[dict]:
    """Devuelve la configuración completa incluyendo el password desencriptado.
    Usar solo en el backend (nunca enviar al cliente).
    """
    cfg = get_config(db)
    if not cfg:
        return None
    return {
        "host": cfg.host,
        "puerto": cfg.puerto,
        "usuario": cfg.usuario,
        "password": desencriptar(cfg.password_encriptado),
        "remitente_nombre": cfg.remitente_nombre,
        "seguridad": cfg.seguridad,
    }


def upsert_config(
    db: Session,
    host: str,
    puerto: int,
    usuario: str,
    password: Optional[str],
    remitente_nombre: Optional[str],
    seguridad: str,
    updated_by_id: Optional[int],
) -> ConfiguracionCorreo:
    """Crea o actualiza la configuración de correo. Si password es None,
    se conserva el password existente.
    """
    cfg = get_config(db)
    if not cfg:
        if password is None:
            raise ValueError("No existe configuración de correo previa; se requiere password para crearla.")
        cfg = ConfiguracionCorreo(
            id=CONFIG_CORREO_ID,
            host=host,
            puerto=puerto,
            usuario=usuario,
            password_encriptado=encriptar(password),
            remitente_nombre=remitente_nombre,
            seguridad=seguridad,
            updated_by=updated_by_id,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(cfg)
    else:
        cfg.host = host
        cfg.puerto = puerto
        cfg.usuario = usuario
        cfg.remitente_nombre = remitente_nombre
        cfg.seguridad = seguridad
        cfg.updated_by = updated_by_id
        cfg.updated_at = datetime.now(timezone.utc)
        if password is not None:
            cfg.password_encriptado = encriptar(password)
    db.commit()
    db.refresh(cfg)
    return cfg


def validar_seguridad(seguridad: str) -> str:
    """Normaliza y valida la opción de seguridad."""
    valor = (seguridad or "").strip().lower()
    if valor not in ("none", "starttls", "ssl"):
        raise ValueError("seguridad debe ser 'none', 'starttls' o 'ssl'")
    return valor
