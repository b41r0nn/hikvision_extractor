"""
config_service.py
Gestión persistente de configuración del sistema (destinatarios de correo,
periodicidad de reportes, etc.) en la base de datos.
"""
import os
from typing import List
from sqlalchemy.orm import Session

from .models import Configuracion

DEFAULTS = {
    "destinatarios_correo": os.getenv("REPORT_RECIPIENTS", ""),
    "reporte_semanal_dia":   os.getenv("REPORTE_SEMANAL_DIA", "1"),    # 0=dom, 1=lun
    "reporte_semanal_hora":  os.getenv("REPORTE_SEMANAL_HORA", "7"),
    "reporte_semanal_minuto":os.getenv("REPORTE_SEMANAL_MINUTO", "5"),
    "reporte_mensual_dia":   os.getenv("REPORTE_MENSUAL_DIA", "1"),
    "reporte_mensual_hora":  os.getenv("REPORTE_MENSUAL_HORA", "7"),
    "reporte_mensual_minuto":os.getenv("REPORTE_MENSUAL_MINUTO", "5"),
}


def _get(db: Session, clave: str) -> Configuracion | None:
    return db.query(Configuracion).filter(Configuracion.clave == clave).first()


def get_valor(db: Session, clave: str, default: str = "") -> str:
    c = _get(db, clave)
    return c.valor if c else default


def set_valor(db: Session, clave: str, valor: str) -> None:
    c = _get(db, clave)
    if c:
        c.valor = valor
    else:
        db.add(Configuracion(clave=clave, valor=valor))
    db.commit()


def init_defaults(db: Session) -> None:
    """Crea las claves de configuración con valores por defecto si no existen."""
    for clave, valor in DEFAULTS.items():
        if _get(db, clave) is None:
            db.add(Configuracion(clave=clave, valor=valor))
    db.commit()


def get_recipients(db: Session) -> List[str]:
    raw = get_valor(db, "destinatarios_correo", DEFAULTS["destinatarios_correo"])
    return [e.strip() for e in raw.split(",") if e.strip()]


def add_recipient(db: Session, email: str) -> List[str]:
    recipients = get_recipients(db)
    email = email.strip()
    if email and email not in recipients:
        recipients.append(email)
    set_valor(db, "destinatarios_correo", ",".join(recipients))
    return recipients


def remove_recipient(db: Session, email: str) -> List[str]:
    recipients = [e for e in get_recipients(db) if e != email.strip()]
    set_valor(db, "destinatarios_correo", ",".join(recipients))
    return recipients


def get_periodicidad(db: Session) -> dict:
    return {
        "semanal": {
            "dia":    int(get_valor(db, "reporte_semanal_dia",    DEFAULTS["reporte_semanal_dia"])),
            "hora":   int(get_valor(db, "reporte_semanal_hora",   DEFAULTS["reporte_semanal_hora"])),
            "minuto": int(get_valor(db, "reporte_semanal_minuto", DEFAULTS["reporte_semanal_minuto"])),
        },
        "mensual": {
            "dia":    int(get_valor(db, "reporte_mensual_dia",    DEFAULTS["reporte_mensual_dia"])),
            "hora":   int(get_valor(db, "reporte_mensual_hora",   DEFAULTS["reporte_mensual_hora"])),
            "minuto": int(get_valor(db, "reporte_mensual_minuto", DEFAULTS["reporte_mensual_minuto"])),
        },
    }


def set_periodicidad(db: Session, semanal: dict, mensual: dict) -> None:
    set_valor(db, "reporte_semanal_dia",    str(int(semanal["dia"])))
    set_valor(db, "reporte_semanal_hora",   str(int(semanal["hora"])))
    set_valor(db, "reporte_semanal_minuto", str(int(semanal["minuto"])))
    set_valor(db, "reporte_mensual_dia",    str(int(mensual["dia"])))
    set_valor(db, "reporte_mensual_hora",   str(int(mensual["hora"])))
    set_valor(db, "reporte_mensual_minuto", str(int(mensual["minuto"])))
