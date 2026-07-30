"""
migracion_turno_general.py
Fase B: migración de datos para el versionado de horarios por día de semana.

Crea un "Turno General", inserta horarios base (2020-01-01) y horarios vigentes
(2026-07-28), asigna el turno a todos los empleados con turno_id IS NULL y
verifica todo dentro de UNA transacción antes de COMMIT.

Uso:
  DATABASE_URL=postgresql://admin:adminpassword@db:5432/hikvision python migracion_turno_general.py

Para pruebas locales:
  DATABASE_URL=sqlite:///./migracion_test.db python migracion_turno_general.py
"""
import os
import sys
import logging
from datetime import date, time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Turno, TurnoHorario, Empleado
from backend.report_service import obtener_horario_vigente, HorarioNoConfiguradoError

# Configurar logging detallado
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "migracion_turno_general_console.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./migracion_test.db"
)

VIGENTE_BASE = date(2020, 1, 1)
VIGENTE_NUEVA = date(2026, 7, 28)
TURNO_NOMBRE = "Turno General"


def main() -> int:
    log.info("=" * 60)
    log.info("INICIO migracion_turno_general.py")
    log.info("DATABASE_URL=%s", DATABASE_URL)
    log.info("VIGENTE_NUEVA=%s", VIGENTE_NUEVA)
    log.info("=" * 60)

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Iniciar transacción explícita
        log.info("BEGIN transaccion")

        # 1. Crear Turno General
        turno = Turno(
            nombre=TURNO_NOMBRE,
            hora_entrada=time(7, 30),
            hora_salida=None,
            tolerancia_minutos=10,
        )
        db.add(turno)
        db.flush()
        db.refresh(turno)
        log.info("PASO 1: Creado turno '%s' con id=%s", TURNO_NOMBRE, turno.id)

        # 2. Insertar filas base (5 días, vigente_desde=2020-01-01)
        for dia in range(5):
            db.add(TurnoHorario(
                turno_id=turno.id,
                dia_semana=dia,
                hora_entrada=time(7, 30),
                tolerancia_minutos=10,
                vigente_desde=VIGENTE_BASE,
            ))
        log.info("PASO 2: Insertadas 5 filas base en turno_horario (vigente_desde=%s)", VIGENTE_BASE)

        # 3. Insertar filas nuevas (vigente_desde=2026-07-28)
        # Lunes (0): 08:00, tol=1
        db.add(TurnoHorario(
            turno_id=turno.id,
            dia_semana=0,
            hora_entrada=time(8, 0),
            tolerancia_minutos=1,
            vigente_desde=VIGENTE_NUEVA,
        ))
        # Martes a viernes: 07:30, tol=1
        for dia in range(1, 5):
            db.add(TurnoHorario(
                turno_id=turno.id,
                dia_semana=dia,
                hora_entrada=time(7, 30),
                tolerancia_minutos=1,
                vigente_desde=VIGENTE_NUEVA,
            ))
        log.info("PASO 3: Insertadas 5 filas nuevas en turno_horario (vigente_desde=%s)", VIGENTE_NUEVA)

        # 4. Asignar turno a empleados sin turno_id
        empleados_previo = db.query(Empleado).filter(Empleado.turno_id.is_(None)).count()
        log.info("PASO 4: Empleados con turno_id IS NULL antes del UPDATE: %s", empleados_previo)

        db.query(Empleado).filter(Empleado.turno_id.is_(None)).update(
            {Empleado.turno_id: turno.id},
            synchronize_session=False,
        )
        db.flush()
        log.info("PASO 4: UPDATE ejecutado")

        # 5. Verificaciones dentro de la transacción
        log.info("PASO 5: Inician verificaciones")

        check1 = db.query(Empleado).filter(Empleado.turno_id.is_(None)).count()
        log.info("  CHECK 1: empleados con turno_id IS NULL = %s (esperado 0)", check1)
        if check1 != 0:
            raise ValueError(f"CHECK 1 fallo: {check1} empleados siguen sin turno_id")

        check2 = db.query(TurnoHorario).filter(TurnoHorario.turno_id == turno.id).count()
        log.info("  CHECK 2: filas turno_horario para turno_id=%s = %s (esperado 10)", turno.id, check2)
        if check2 != 10:
            raise ValueError(f"CHECK 2 fallo: se esperaban 10 filas, hay {check2}")

        # Verificación funcional con obtener_horario_vigente
        he_lun_nuevo, tol_lun_nuevo = obtener_horario_vigente(db, turno.id, 0, VIGENTE_NUEVA)
        log.info("  CHECK 3: lunes %s -> hora=%s tolerancia=%s (esperado 08:00, 1)",
                 VIGENTE_NUEVA, he_lun_nuevo, tol_lun_nuevo)
        if he_lun_nuevo != time(8, 0) or tol_lun_nuevo != 1:
            raise ValueError(f"CHECK 3 fallo: lunes nuevo={he_lun_nuevo}/{tol_lun_nuevo}")

        he_mar_nuevo, tol_mar_nuevo = obtener_horario_vigente(db, turno.id, 1, VIGENTE_NUEVA)
        log.info("  CHECK 4: martes %s -> hora=%s tolerancia=%s (esperado 07:30, 1)",
                 VIGENTE_NUEVA, he_mar_nuevo, tol_mar_nuevo)
        if he_mar_nuevo != time(7, 30) or tol_mar_nuevo != 1:
            raise ValueError(f"CHECK 4 fallo: martes nuevo={he_mar_nuevo}/{tol_mar_nuevo}")

        fecha_historica = date(2020, 6, 1)  # lunes histórico antes de cualquier cambio
        he_lun_hist, tol_lun_hist = obtener_horario_vigente(db, turno.id, 0, fecha_historica)
        log.info("  CHECK 5: lunes %s -> hora=%s tolerancia=%s (esperado 07:30, 10)",
                 fecha_historica, he_lun_hist, tol_lun_hist)
        if he_lun_hist != time(7, 30) or tol_lun_hist != 10:
            raise ValueError(f"CHECK 5 fallo: lunes historico={he_lun_hist}/{tol_lun_hist}")

        # Si llegamos aquí, todo OK → COMMIT
        db.commit()
        log.info("COMMIT exitoso")
        log.info("=" * 60)
        log.info("MIGRACION COMPLETADA")
        log.info("  turno_id=%s '%s'", turno.id, TURNO_NOMBRE)
        log.info("  empleados actualizados=%s", empleados_previo)
        log.info("=" * 60)
        return 0

    except Exception as e:
        db.rollback()
        log.error("ROLLBACK ejecutado por error: %s", e)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        rc = 1
        log.error("Excepcion no controlada: %s", e)

    log.info("[RESULTADO] %s", "PASS" if rc == 0 else "FAIL")
    sys.exit(rc)
