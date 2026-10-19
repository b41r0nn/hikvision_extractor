"""
tests/test_report_service.py
Tests para el motor de reportes y cálculo de tardanzas.

Cubre especialmente:
- Bug fix: fusión de marcas usa r.fecha (no hoy_bogota())
- Cálculo correcto de tardanza
- Días laborales / festivos
"""
import pytest
from datetime import date, time, datetime
from unittest.mock import MagicMock


# ── Tests de calcular_tardanza ───────────────────────────────────────────────

def test_tardanza_positiva():
    from backend.report_service import calcular_tardanza
    primera = time(8, 20)   # llegó 8:20
    turno   = time(8, 0)    # turno a las 8:00
    tol     = 10            # 10 min tolerancia → límite 8:10
    mins = calcular_tardanza(primera, turno, tol)
    assert mins == 10  # 8:20 - 8:10 = 10 minutos


def test_sin_tardanza_dentro_tolerancia():
    from backend.report_service import calcular_tardanza
    primera = time(8, 8)
    turno   = time(8, 0)
    tol     = 10
    assert calcular_tardanza(primera, turno, tol) is None


def test_sin_tardanza_exactamente_en_limite():
    from backend.report_service import calcular_tardanza
    primera = time(8, 10)   # exactamente en el límite
    turno   = time(8, 0)
    tol     = 10
    assert calcular_tardanza(primera, turno, tol) is None


def test_tardanza_antes_de_hora_turno():
    from backend.report_service import calcular_tardanza
    primera = time(7, 55)   # llegó antes
    turno   = time(8, 0)
    tol     = 10
    assert calcular_tardanza(primera, turno, tol) is None


# ── Tests de es_dia_laboral ──────────────────────────────────────────────────

def test_sabado_no_es_laboral():
    from backend.report_service import es_dia_laboral
    sabado = date(2026, 10, 17)  # sábado
    assert not es_dia_laboral(sabado, set())


def test_domingo_no_es_laboral():
    from backend.report_service import es_dia_laboral
    domingo = date(2026, 10, 18)
    assert not es_dia_laboral(domingo, set())


def test_lunes_es_laboral():
    from backend.report_service import es_dia_laboral
    lunes = date(2026, 10, 19)
    assert es_dia_laboral(lunes, set())


def test_festivo_no_es_laboral():
    from backend.report_service import es_dia_laboral
    festivo = date(2026, 7, 20)  # Día de la Independencia Colombia
    festivos = {festivo}
    assert not es_dia_laboral(festivo, festivos)


# ── Test bug fix: fusión de marcas usa fecha correcta ────────────────────────

def test_fusion_marcas_usa_fecha_del_registro():
    """
    Regresión: antes del fix, datetime.combine(hoy_bogota(), hora) usaba la
    fecha de HOY para calcular delta, pudiendo fusionar marcas de días distintos.
    Después del fix, se usa r.fecha y primero.fecha.
    """
    from backend.report_service import _fusionar_marcas_por_empleado_dia

    # Dos marcas del mismo empleado en DÍAS DIFERENTES con horas separadas < 2 min
    r1 = MagicMock()
    r1.nombre_empleado = "Juan"
    r1.fecha = date(2026, 10, 13)   # Lunes
    r1.hora  = time(8, 0)

    r2 = MagicMock()
    r2.nombre_empleado = "Juan"
    r2.fecha = date(2026, 10, 14)   # Martes
    r2.hora  = time(8, 1)  # 1 minuto después → dentro de ventana de 2min

    resultado = _fusionar_marcas_por_empleado_dia([r1, r2], ventana_minutos=2)

    # Con el fix, son días distintos → delta es 23h59min → NO se fusionan
    assert len(resultado) == 2, (
        "Marcas de días distintos NO deben fusionarse aunque las horas sean cercanas"
    )


def test_fusion_marcas_mismo_dia_dentro_ventana():
    """Marcas del mismo empleado/día dentro de la ventana SÍ deben fusionarse."""
    from backend.report_service import _fusionar_marcas_por_empleado_dia

    r1 = MagicMock()
    r1.nombre_empleado = "Ana"
    r1.fecha = date(2026, 10, 13)
    r1.hora  = time(8, 0)

    r2 = MagicMock()
    r2.nombre_empleado = "Ana"
    r2.fecha = date(2026, 10, 13)
    r2.hora  = time(8, 1)  # 1 min → dentro de ventana 2min

    resultado = _fusionar_marcas_por_empleado_dia([r1, r2], ventana_minutos=2)
    assert len(resultado) == 1
    assert resultado[0].hora == time(8, 0)  # conserva la primera


def test_fusion_marcas_mismo_dia_fuera_ventana():
    """Marcas del mismo empleado/día fuera de la ventana NO se fusionan."""
    from backend.report_service import _fusionar_marcas_por_empleado_dia

    r1 = MagicMock()
    r1.nombre_empleado = "Ana"
    r1.fecha = date(2026, 10, 13)
    r1.hora  = time(8, 0)

    r2 = MagicMock()
    r2.nombre_empleado = "Ana"
    r2.fecha = date(2026, 10, 13)
    r2.hora  = time(17, 0)  # salida a las 5pm → fuera de ventana

    resultado = _fusionar_marcas_por_empleado_dia([r1, r2], ventana_minutos=2)
    assert len(resultado) == 2


def test_fusion_ventana_cero_no_fusiona():
    """ventana_minutos=0 retorna la lista original sin fusionar."""
    from backend.report_service import _fusionar_marcas_por_empleado_dia

    r1 = MagicMock()
    r1.nombre_empleado = "Pedro"
    r1.fecha = date(2026, 10, 13)
    r1.hora  = time(8, 0)

    r2 = MagicMock()
    r2.nombre_empleado = "Pedro"
    r2.fecha = date(2026, 10, 13)
    r2.hora  = time(8, 0)

    resultado = _fusionar_marcas_por_empleado_dia([r1, r2], ventana_minutos=0)
    assert len(resultado) == 2


# ── Tests de calcular_tardanzas_dia ─────────────────────────────────────────

def test_tardanzas_dia_no_laboral_retorna_vacio(db):
    from backend.report_service import calcular_tardanzas_dia
    sabado = date(2026, 10, 17)
    resultado = calcular_tardanzas_dia(db, sabado)
    assert resultado == []


def test_tardanzas_dia_con_tardanza(db, empleado_muestra, registro_muestra):
    """Empleado que llegó a las 8:15 con turno a las 8:00 y tolerancia 10min
    → tardanza de 5 minutos (8:15 - 8:10)."""
    from backend.report_service import calcular_tardanzas_dia
    lunes = date(2026, 10, 13)  # fecha del registro_muestra
    tardanzas = calcular_tardanzas_dia(db, lunes)
    assert len(tardanzas) == 1
    assert tardanzas[0]["nombre"] == "Juan Perez"
    assert tardanzas[0]["tardanza_mins"] == 5


def test_tardanzas_dia_sin_tardanza(db, empleado_muestra):
    """Empleado que llegó a tiempo → sin tardanza."""
    from backend.models import RegistroAsistencia
    from backend.report_service import calcular_tardanzas_dia
    reg = RegistroAsistencia(
        empleado_id=empleado_muestra.employee_id,
        nombre_empleado=empleado_muestra.nombre,
        fecha=date(2026, 10, 14),   # Martes
        hora=time(7, 55),           # llegó antes del turno
        tipo_evento="Fingerprint Recognition Passed",
        evento_raw="2026-10-14T07:55:00",
    )
    db.add(reg)
    db.flush()
    tardanzas = calcular_tardanzas_dia(db, date(2026, 10, 14))
    assert len(tardanzas) == 0
