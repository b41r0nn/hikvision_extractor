"""
timezone.py
Utilidades de zona horaria para todo el backend. El negocio opera en
America/Bogota; por eso los valores de 'hoy' usados en reportes, KPIs,
extracción programada y correos deben provenir de aquí.
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo

BOGOTA_TZ = ZoneInfo("America/Bogota")
UTC_TZ    = ZoneInfo("UTC")


def hoy_bogota() -> date:
    """Fecha local de Bogotá del momento actual."""
    return datetime.now(BOGOTA_TZ).date()


def ahora_bogota() -> datetime:
    """Datetime consciente de zona horaria en Bogotá."""
    return datetime.now(BOGOTA_TZ)


def ahora_utc() -> datetime:
    """Datetime consciente UTC (útil para tokens/auditoría)."""
    return datetime.now(UTC_TZ)
