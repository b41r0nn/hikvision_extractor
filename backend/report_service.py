"""
report_service.py
Motor de generación de informes Excel con formato dinámico de marcas.
Lee directamente de PostgreSQL via SQLAlchemy.
"""
import io
import os
from datetime import date, timedelta, time, datetime
from collections import defaultdict
from typing import List, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from .models import RegistroAsistencia, Empleado, Turno, TurnoHorario, Festivo
from .timezone import hoy_bogota

# ── Colores ────────────────────────────────────────────────────────────────────
HDR_BLUE   = "1F3864"   # Encabezados azul oscuro
HDR_MID    = "2E5B9A"   # Sub-encabezados
GREEN_CELL = "E8F5E9"   # Celdas con hora (verde claro)
WHITE      = "FFFFFF"
GRAY_ALT   = "F2F4F8"   # Filas alternadas

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _border(color="AAAAAA"):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)


def _cell(ws, row, col, value="", bg=WHITE, bold=False, color="000000",
          size=9, align="center", wrap=False):
    c = ws.cell(row=row, column=col, value=value)
    c.font      = Font(name="Calibri", bold=bold, color=color, size=size)
    c.fill      = PatternFill("solid", fgColor=bg)
    c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    c.border    = _border()
    return c


def _hdr(ws, row, col, value, width=None, size=10, bg=HDR_BLUE):
    c = _cell(ws, row, col, value, bg=bg, bold=True, color="FFFFFF", size=size)
    if width:
        ws.column_dimensions[get_column_letter(col)].width = width
    return c


import holidays

# ── Lógica de festivos y días laborales ───────────────────────────────────────
def get_festivos(start: date, end: date) -> set:
    co_holidays = holidays.country_holidays('CO', years=range(start.year, end.year + 1))
    return {d for d in co_holidays if start <= d <= end}


def init_festivos(db: Session, years: Optional[List[int]] = None) -> int:
    """
    Puebla la tabla Festivo con los festivos colombianos calculados por la
    librería `holidays`. Si no se indican años, usa el anterior, actual y siguiente.
    Retorna la cantidad de festivos insertados.
    """
    from .models import Festivo

    if years is None:
        current = hoy_bogota().year
        years = [current - 1, current, current + 1]

    co_holidays = holidays.country_holidays('CO', years=years)
    added = 0
    for d_obj, desc in co_holidays.items():
        existe = db.query(Festivo).filter(Festivo.fecha == d_obj).first()
        if not existe:
            db.add(Festivo(fecha=d_obj, descripcion=desc, fuente="holidays"))
            added += 1
    db.commit()
    return added


def es_dia_laboral(d: date, festivos: set) -> bool:
    """Lunes a Viernes, sin festivos colombianos."""
    return d.weekday() < 5 and d not in festivos


def get_dias_rango(start: date, end: date, festivos: set) -> List[date]:
    dias = []
    cur = start
    while cur <= end:
        if es_dia_laboral(cur, festivos):
            dias.append(cur)
        cur += timedelta(days=1)
    return dias


# ── Fusión de marcas casi simultáneas ──────────────────────────────────────────
def _fusionar_marcas_por_empleado_dia(
    registros: List[RegistroAsistencia],
    ventana_minutos: int = 2,
) -> List[RegistroAsistencia]:
    """
    Fusiona marcas del mismo empleado/día que caen dentro de
    `ventana_minutos` desde la primera marca del grupo.
    Retorna una lista equivalente con solo la primera marca de cada grupo.
    """
    if ventana_minutos <= 0:
        return registros

    grouped = defaultdict(list)
    for r in registros:
        grouped[(r.nombre_empleado, r.fecha)].append(r)

    fusionados: List[RegistroAsistencia] = []
    for regs in grouped.values():
        regs.sort(key=lambda r: r.hora)
        if not regs:
            continue

        grupo = [regs[0]]
        for r in regs[1:]:
            primero = grupo[0]
            delta = (
                datetime.combine(hoy_bogota(), r.hora)
                - datetime.combine(hoy_bogota(), primero.hora)
            )
            if delta <= timedelta(minutes=ventana_minutos):
                grupo.append(r)
            else:
                fusionados.append(grupo[0])
                grupo = [r]
        fusionados.append(grupo[0])

    return fusionados


# ── Lógica de tardanza ─────────────────────────────────────────────────────────
class HorarioNoConfiguradoError(Exception):
    """El turno no tiene un horario vigente configurado para el día solicitado."""


def obtener_horario_vigente(
    db: Session,
    turno_id: int,
    dia_semana: int,
    fecha: date,
) -> tuple:
    """
    Retorna (hora_entrada, tolerancia_minutos) vigentes para un turno, día de
    semana y fecha dados. Si no hay fila configurada, lanza
    HorarioNoConfiguradoError.

    dia_semana: 0=lunes, 1=martes, ..., 4=viernes.
    """
    horario = (
        db.query(TurnoHorario)
        .filter(
            TurnoHorario.turno_id == turno_id,
            TurnoHorario.dia_semana == dia_semana,
            TurnoHorario.vigente_desde <= fecha,
        )
        .order_by(TurnoHorario.vigente_desde.desc())
        .first()
    )
    if horario is None:
        raise HorarioNoConfiguradoError(
            f"Turno {turno_id} no tiene horario configurado para "
            f"dia_semana={dia_semana} vigente desde {fecha}"
        )
    return horario.hora_entrada, horario.tolerancia_minutos


def calcular_tardanza(primera_marca: time, hora_turno: time, tolerancia: int) -> Optional[int]:
    """Retorna minutos de tardanza (>0) o None si llegó a tiempo."""
    entrada = datetime.combine(hoy_bogota(), hora_turno)
    limite  = entrada + timedelta(minutes=tolerancia)
    llegada = datetime.combine(hoy_bogota(), primera_marca)
    delta   = (llegada - limite).total_seconds() / 60
    return int(delta) if delta > 0 else None


# ── Motor principal del informe ────────────────────────────────────────────────
def generar_reporte(
    db: Session,
    fecha_inicio: date,
    fecha_fin: date,
    employee_ids: Optional[List[str]] = None,   # lista de employee_id strings
    departamentos: Optional[List[str]] = None,
    modo: str = "entrada_salida",               # "entrada_salida" | "completo"
) -> bytes:
    """
    Genera el Excel con formato dinámico de marcas y retorna los bytes del archivo.
    modo="entrada_salida": una columna Entrada y otra Salida por día.
    modo="completo": todas las marcas del día como Marca 1, Marca 2, etc.
    """
    # 1. Festivos del período
    festivos = get_festivos(fecha_inicio, fecha_fin)
    dias_laborales = get_dias_rango(fecha_inicio, fecha_fin, festivos)

    if not dias_laborales:
        raise ValueError("No hay días laborales en el rango indicado.")

    # 2. Todos los empleados activos deben aparecer en el reporte
    query_empleados = db.query(Empleado).filter(Empleado.activo == True)
    if employee_ids:
        query_empleados = query_empleados.filter(Empleado.employee_id.in_(employee_ids))
    if departamentos:
        query_empleados = query_empleados.filter(Empleado.departamento.in_(departamentos))

    empleados_reporte = query_empleados.order_by(Empleado.nombre).all()
    if not empleados_reporte:
        raise ValueError("No hay empleados activos para los filtros seleccionados.")

    nombres_reporte = {e.nombre for e in empleados_reporte}

    # 3. Consultar registros del período
    query = db.query(RegistroAsistencia).filter(
        RegistroAsistencia.fecha >= fecha_inicio,
        RegistroAsistencia.fecha <= fecha_fin,
        RegistroAsistencia.nombre_empleado.in_(nombres_reporte)
    )

    registros = query.order_by(
        RegistroAsistencia.nombre_empleado,
        RegistroAsistencia.fecha,
        RegistroAsistencia.hora
    ).all()

    # 4. Fusionar marcas casi simultáneas (configurable vía .env)
    ventana_fusion = int(os.getenv("MARCA_FUSION_MINUTOS", "2"))
    registros = _fusionar_marcas_por_empleado_dia(registros, ventana_fusion)

    # 5. Pivot: {nombre: {fecha: [time, ...]}} — SOBRE datos ya fusionados
    pivot: dict = defaultdict(lambda: defaultdict(list))
    for r in registros:
        pivot[r.nombre_empleado][r.fecha].append(r.hora)

    empleados_sorted = sorted(e.nombre for e in empleados_reporte)

    total_marcaciones = sum(len(ms) for emp in pivot.values() for ms in emp.values())
    dias_sin_reg = sum(
        1 for nombre in empleados_sorted
        for d in dias_laborales
        if not pivot[nombre].get(d)
    )

    # 6. Construir Excel ─────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asistencia"

    if modo == "completo":
        _build_ws_completo(ws, dias_laborales, empleados_sorted, pivot,
                           fecha_inicio, fecha_fin, total_marcaciones, dias_sin_reg)
    else:
        _build_ws_entrada_salida(ws, dias_laborales, empleados_sorted, pivot,
                                 fecha_inicio, fecha_fin, total_marcaciones, dias_sin_reg)

    # ── Guardar en buffer de bytes ───────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _write_reporte_metadata(ws, total_cols, fecha_inicio, fecha_fin,
                            empleados_sorted, dias_laborales,
                            total_marcaciones, dias_sin_reg):
    """Escribe las filas de título y metadatos comunes a ambos modos."""
    # ── Fila 1: Título ───────────────────────────────────────────────────────
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    c = ws.cell(row=1, column=1, value="INFORME DE ASISTENCIA — REDIHOS S.A.S.")
    c.font      = Font(name="Calibri", bold=True, color="FFFFFF", size=14)
    c.fill      = PatternFill("solid", fgColor=HDR_BLUE)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # ── Fila 2: Metadatos ────────────────────────────────────────────────────
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    c = ws.cell(
        row=2, column=1,
        value=(f"Período: {fecha_inicio.strftime('%d/%m/%Y')} – {fecha_fin.strftime('%d/%m/%Y')}"
               f"   |   Empleados: {len(empleados_sorted)}"
               f"   |   Días laborales: {len(dias_laborales)}"
               f"   |   Total marcaciones: {total_marcaciones}"
               f"   |   Días sin registro: {dias_sin_reg}")
    )
    c.font      = Font(name="Calibri", italic=True, color="FFFFFF", size=9)
    c.fill      = PatternFill("solid", fgColor=HDR_MID)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20


def _build_ws_entrada_salida(ws, dias_laborales, empleados_sorted, pivot,
                             fecha_inicio, fecha_fin, total_marcaciones, dias_sin_reg):
    """Reporte resumido: Entrada (primera marca) / Salida (última marca)."""
    MARCAS_POR_DIA = 2
    ENTRADA_IDX = 0
    SALIDA_IDX  = 1

    ws.column_dimensions["A"].width = 32
    ncols_datos = len(dias_laborales) * MARCAS_POR_DIA
    total_cols = 1 + ncols_datos

    _write_reporte_metadata(ws, total_cols, fecha_inicio, fecha_fin,
                            empleados_sorted, dias_laborales,
                            total_marcaciones, dias_sin_reg)

    # ── Fila 3: Fechas (grupos por día) ─────────────────────────────────────
    ws.cell(row=3, column=1, value="").fill = PatternFill("solid", fgColor=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        col_start = 2 + i * MARCAS_POR_DIA
        col_end   = col_start + MARCAS_POR_DIA - 1
        label = f"{DIAS_ES[d.weekday()]}  {d.strftime('%d/%m')}"
        ws.merge_cells(start_row=3, start_column=col_start, end_row=3, end_column=col_end)
        c = ws.cell(row=3, column=col_start, value=label)
        c.font      = Font(name="Calibri", bold=True, color="FFFFFF", size=9)
        c.fill      = PatternFill("solid", fgColor=HDR_BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = _border()
    ws.row_dimensions[3].height = 22

    # ── Fila 4: Sub-encabezados Entrada / Salida ────────────────────────────
    _hdr(ws, 4, 1, "EMPLEADO", width=32, bg=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        col_entrada = 2 + i * MARCAS_POR_DIA + ENTRADA_IDX
        col_salida  = 2 + i * MARCAS_POR_DIA + SALIDA_IDX
        _hdr(ws, 4, col_entrada, "Entrada", width=10, bg=HDR_MID)
        _hdr(ws, 4, col_salida,  "Salida",  width=10, bg=HDR_MID)
    ws.row_dimensions[4].height = 22
    ws.freeze_panes = "B5"

    # ── Filas de datos ───────────────────────────────────────────────────────
    totales_col = defaultdict(int)

    for r_idx, nombre in enumerate(empleados_sorted):
        row = 5 + r_idx
        bg_row = WHITE if r_idx % 2 == 0 else GRAY_ALT
        _cell(ws, row, 1, nombre, bg=bg_row, align="left", size=9)

        for i, d in enumerate(dias_laborales):
            marcas = sorted(pivot[nombre].get(d, []))
            col_entrada = 2 + i * MARCAS_POR_DIA + ENTRADA_IDX
            col_salida  = 2 + i * MARCAS_POR_DIA + SALIDA_IDX

            if not marcas:
                ws.merge_cells(
                    start_row=row, start_column=col_entrada,
                    end_row=row, end_column=col_salida
                )
                _cell(ws, row, col_entrada, "SIN REGISTRO",
                      bg="FFF3E0", color="E65100", bold=True, size=8)
            else:
                entrada = marcas[0]
                salida  = marcas[-1] if len(marcas) > 1 else None

                _cell(ws, row, col_entrada,
                      entrada.strftime("%H:%M") if hasattr(entrada, 'strftime') else str(entrada)[:5],
                      bg=GREEN_CELL, size=9)
                totales_col[col_entrada] += 1

                if salida:
                    _cell(ws, row, col_salida,
                          salida.strftime("%H:%M") if hasattr(salida, 'strftime') else str(salida)[:5],
                          bg=GREEN_CELL, size=9)
                    totales_col[col_salida] += 1
                else:
                    _cell(ws, row, col_salida, "—", bg=bg_row, color="AAAAAA", size=9)

        ws.row_dimensions[row].height = 17

    # ── Fila de totales ──────────────────────────────────────────────────────
    total_row = 5 + len(empleados_sorted)
    _hdr(ws, total_row, 1, "TOTAL MARCACIONES", bg=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        col_entrada = 2 + i * MARCAS_POR_DIA + ENTRADA_IDX
        col_salida  = 2 + i * MARCAS_POR_DIA + SALIDA_IDX
        _hdr(ws, total_row, col_entrada, str(totales_col.get(col_entrada, 0)), bg=HDR_MID)
        _hdr(ws, total_row, col_salida,  str(totales_col.get(col_salida, 0)),  bg=HDR_MID)
    ws.row_dimensions[total_row].height = 20


def _build_ws_completo(ws, dias_laborales, empleados_sorted, pivot,
                       fecha_inicio, fecha_fin, total_marcaciones, dias_sin_reg):
    """Reporte completo: todas las marcas del día como Marca 1, Marca 2, ..."""
    # N máximo de marcas en cualquier día (sobre datos fusionados)
    max_marcas = 1
    for emp_data in pivot.values():
        for marcas in emp_data.values():
            if len(marcas) > max_marcas:
                max_marcas = len(marcas)

    ws.column_dimensions["A"].width = 32
    ncols_datos = len(dias_laborales) * max_marcas
    total_cols = 1 + ncols_datos

    _write_reporte_metadata(ws, total_cols, fecha_inicio, fecha_fin,
                            empleados_sorted, dias_laborales,
                            total_marcaciones, dias_sin_reg)

    # ── Fila 3: Fechas (grupos por día) ─────────────────────────────────────
    ws.cell(row=3, column=1, value="").fill = PatternFill("solid", fgColor=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        col_start = 2 + i * max_marcas
        col_end   = col_start + max_marcas - 1
        label = f"{DIAS_ES[d.weekday()]}  {d.strftime('%d/%m')}"
        if max_marcas > 1:
            ws.merge_cells(start_row=3, start_column=col_start, end_row=3, end_column=col_end)
        c = ws.cell(row=3, column=col_start, value=label)
        c.font      = Font(name="Calibri", bold=True, color="FFFFFF", size=9)
        c.fill      = PatternFill("solid", fgColor=HDR_BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = _border()
    ws.row_dimensions[3].height = 22

    # ── Fila 4: Sub-encabezados (Marca 1, Marca 2, ...) ─────────────────────
    _hdr(ws, 4, 1, "EMPLEADO", width=32, bg=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        for m in range(max_marcas):
            col = 2 + i * max_marcas + m
            label = f"Marca {m+1}" if max_marcas > 1 else "Hora"
            _hdr(ws, 4, col, label, width=9, bg=HDR_MID)
    ws.row_dimensions[4].height = 22
    ws.freeze_panes = "B5"

    # ── Filas de datos ───────────────────────────────────────────────────────
    totales_col = defaultdict(int)

    for r_idx, nombre in enumerate(empleados_sorted):
        row = 5 + r_idx
        bg_row = WHITE if r_idx % 2 == 0 else GRAY_ALT
        _cell(ws, row, 1, nombre, bg=bg_row, align="left", size=9)

        for i, d in enumerate(dias_laborales):
            marcas = sorted(pivot[nombre].get(d, []))

            if not marcas:
                col_start = 2 + i * max_marcas
                if max_marcas > 1:
                    ws.merge_cells(
                        start_row=row, start_column=col_start,
                        end_row=row, end_column=col_start + max_marcas - 1
                    )
                _cell(ws, row, col_start, "SIN REGISTRO",
                      bg="FFF3E0", color="E65100", bold=True, size=8)
            else:
                for m in range(max_marcas):
                    col = 2 + i * max_marcas + m
                    if m < len(marcas):
                        valor = marcas[m].strftime("%H:%M") if hasattr(marcas[m], 'strftime') else str(marcas[m])[:5]
                        _cell(ws, row, col, valor, bg=GREEN_CELL, size=9)
                        totales_col[col] += 1
                    else:
                        _cell(ws, row, col, "—", bg=bg_row, color="AAAAAA", size=9)

        ws.row_dimensions[row].height = 17

    # ── Fila de totales ──────────────────────────────────────────────────────
    total_row = 5 + len(empleados_sorted)
    _hdr(ws, total_row, 1, "TOTAL MARCACIONES", bg=HDR_BLUE)
    for i, d in enumerate(dias_laborales):
        for m in range(max_marcas):
            col = 2 + i * max_marcas + m
            _hdr(ws, total_row, col, str(totales_col.get(col, 0)), bg=HDR_MID)
    ws.row_dimensions[total_row].height = 20


# ── Tardanzas del día ─────────────────────────────────────────────────────────
def calcular_tardanzas_dia(db: Session, dia: date) -> List[dict]:
    """
    Retorna lista de dicts con empleados registrados que llegaron tarde ese día.
    Ignora marcas de personas no asociadas a un Empleado.

    Desde la Fase A del versionado de horarios, la fuente de verdad es la
    tabla turno_horario. No hay fallback a DEFAULT_TURNO_ENTRADA ni a horario
    individual en la tabla empleados. Si un empleado no tiene turno_id o su
    turno no tiene horario para el día, se lanza HorarioNoConfiguradoError.
    """
    festivos = get_festivos(dia, dia)
    if not es_dia_laboral(dia, festivos):
        return []

    # Primer marca del día por empleado
    registros = db.query(RegistroAsistencia).filter(
        RegistroAsistencia.fecha == dia
    ).order_by(RegistroAsistencia.nombre_empleado, RegistroAsistencia.hora).all()

    primeras: dict = {}
    for r in registros:
        if r.nombre_empleado not in primeras:
            primeras[r.nombre_empleado] = r.hora

    # Buscar turno de cada empleado
    empleados = {e.nombre: e for e in db.query(Empleado).all()}
    tardanzas = []

    for nombre, primera_hora in primeras.items():
        emp = empleados.get(nombre)
        # Ignorar si no está registrado como Empleado
        if not emp:
            continue

        if emp.turno_id is None:
            raise HorarioNoConfiguradoError(
                f"Empleado '{emp.nombre}' (id={emp.id}) no tiene turno_id asignado. "
                f"Correr migración de datos de Fase B antes de calcular tardanzas."
            )

        hora_turno, tolerancia = obtener_horario_vigente(
            db, emp.turno_id, dia.weekday(), dia
        )

        mins = calcular_tardanza(primera_hora, hora_turno, tolerancia)
        if mins is not None:
            tardanzas.append({
                "nombre":        nombre,
                "departamento":  emp.departamento,
                "primera_marca": primera_hora.strftime("%H:%M") if primera_hora else "--",
                "hora_turno":    hora_turno.strftime("%H:%M"),
                "tardanza_mins": mins,
            })

    return sorted(tardanzas, key=lambda x: x["tardanza_mins"], reverse=True)


def calcular_tardanzas_acumulado(
    db: Session,
    fecha_hasta: date,
    max_minutos: int = 30,
) -> List[dict]:
    """
    Retorna acumulado de minutos de tardanza por empleado para el mes y el año
    de `fecha_hasta`. Solo suma tardanzas <= max_minutos. Los días sin horario
    configurado se omiten silenciosamente en lugar de abortar el cálculo.

    Columnas devueltas:
      - nombre
      - departamento
      - minutos_mes
      - dias_mes
      - minutos_año
      - dias_año
    """
    inicio_mes = fecha_hasta.replace(day=1)
    inicio_año = fecha_hasta.replace(month=1, day=1)

    festivos_mes = get_festivos(inicio_mes, fecha_hasta)
    festivos_año = get_festivos(inicio_año, fecha_hasta)

    dias_mes = get_dias_rango(inicio_mes, fecha_hasta, festivos_mes)
    dias_año = get_dias_rango(inicio_año, fecha_hasta, festivos_año)

    acum = {}

    def _procesar_dia(dia: date):
        try:
            tardanzas = calcular_tardanzas_dia(db, dia)
        except HorarioNoConfiguradoError:
            # Día sin horario configurado: no suma ni aborta.
            return
        for t in tardanzas:
            if t["tardanza_mins"] > max_minutos:
                continue
            nombre = t["nombre"]
            if nombre not in acum:
                acum[nombre] = {
                    "nombre":       nombre,
                    "departamento": t["departamento"] or "—",
                    "minutos_mes":  0,
                    "dias_mes":     0,
                    "minutos_año":  0,
                    "dias_año":     0,
                }
            acum[nombre]["minutos_año"] += t["tardanza_mins"]
            acum[nombre]["dias_año"]     += 1
            if dia in dias_mes:
                acum[nombre]["minutos_mes"] += t["tardanza_mins"]
                acum[nombre]["dias_mes"]     += 1

    # Procesar todos los días del año (el acumulado de mes se deriva del mismo loop)
    for dia in dias_año:
        _procesar_dia(dia)

    return sorted(acum.values(), key=lambda x: x["minutos_año"], reverse=True)

