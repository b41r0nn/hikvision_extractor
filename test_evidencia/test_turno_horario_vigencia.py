"""
test_turno_horario_vigencia.py
Evidencia de la Fase A del versionado de horarios por día de semana.

Pruebas (sin dispositivo real, solo BD SQLite):
1. Crear turno y horarios con 2 vigencias distintas de lunes.
2. obtener_horario_vigente() para una fecha ANTES de la nueva vigencia -> hora vieja.
3. obtener_horario_vigente() para una fecha DESPUÉS de la nueva vigencia -> hora nueva.
4. obtener_horario_vigente() para un día sin horario configurado -> lanza HorarioNoConfiguradoError.

Salida: test_evidencia/logs/test_turno_horario_vigencia_console.txt
"""
import os
import sys
import io
from datetime import date, time, timedelta
from contextlib import redirect_stdout

# Asegurar que el proyecto raíz esté en sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Turno, TurnoHorario
from backend.report_service import obtener_horario_vigente, HorarioNoConfiguradoError

DB_PATH = os.path.join(os.path.dirname(__file__), "test_turno_horario_vigencia.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Eliminar DB previa para arrancar limpio
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")


def main():
    from datetime import datetime
    global log

    def log(msg):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

    db = SessionLocal()
    try:
        log("Inicio de pruebas de versionado de horarios")

        # Crear turno de prueba
        turno = Turno(
            nombre="Turno Prueba Vigencia",
            hora_entrada=time(7, 30),
            hora_salida=time(17, 0),
            tolerancia_minutos=10,
        )
        db.add(turno)
        db.commit()
        db.refresh(turno)
        log(f"Turno creado: id={turno.id}")

        # Insertar horarios base para martes a viernes
        for dia in range(1, 5):
            db.add(TurnoHorario(
                turno_id=turno.id,
                dia_semana=dia,
                hora_entrada=time(7, 30),
                tolerancia_minutos=10,
                vigente_desde=date(2020, 1, 1),
            ))

        # Lunes: vigencia vieja a las 07:30
        db.add(TurnoHorario(
            turno_id=turno.id,
            dia_semana=0,  # lunes
            hora_entrada=time(7, 30),
            tolerancia_minutos=10,
            vigente_desde=date(2020, 1, 1),
        ))

        # Lunes: nueva vigencia desde el 4 de agosto de 2026 a las 08:00
        db.add(TurnoHorario(
            turno_id=turno.id,
            dia_semana=0,  # lunes
            hora_entrada=time(8, 0),
            tolerancia_minutos=10,
            vigente_desde=date(2026, 8, 4),
        ))

        db.commit()
        log("Horarios insertados: lunes con 2 vigencias, martes-viernes con vigencia base")

        # Test 1: lunes ANTES de la nueva vigencia
        fecha_antes = date(2026, 7, 27)  # lunes anterior al 4 de agosto
        hora, tol = obtener_horario_vigente(db, turno.id, 0, fecha_antes)
        log(f"TEST 1: lunes {fecha_antes} (antes de vigencia) -> hora={hora}, tolerancia={tol}")
        assert hora == time(7, 30), f"Esperado 07:30, obtenido {hora}"
        assert tol == 10

        # Test 2: lunes DESPUÉS de la nueva vigencia
        fecha_despues = date(2026, 8, 10)  # lunes posterior al 4 de agosto
        hora, tol = obtener_horario_vigente(db, turno.id, 0, fecha_despues)
        log(f"TEST 2: lunes {fecha_despues} (despues de vigencia) -> hora={hora}, tolerancia={tol}")
        assert hora == time(8, 0), f"Esperado 08:00, obtenido {hora}"
        assert tol == 10

        # Test 3: martes con vigencia base
        fecha_martes = date(2026, 8, 4)
        hora, tol = obtener_horario_vigente(db, turno.id, 1, fecha_martes)
        log(f"TEST 3: martes {fecha_martes} -> hora={hora}, tolerancia={tol}")
        assert hora == time(7, 30)
        assert tol == 10

        # Test 4: día sin horario configurado -> excepción
        # Creamos otro turno sin horarios
        turno_vacio = Turno(nombre="Turno Sin Horario", hora_entrada=time(7, 30), tolerancia_minutos=10)
        db.add(turno_vacio)
        db.commit()
        db.refresh(turno_vacio)
        try:
            obtener_horario_vigente(db, turno_vacio.id, 0, date(2026, 8, 4))
            log("TEST 4: ERROR -> no lanzó excepción")
            raise AssertionError("Se esperaba HorarioNoConfiguradoError")
        except HorarioNoConfiguradoError as e:
            log(f"TEST 4: OK -> HorarioNoConfiguradoError lanzada: {e}")

        log("Todas las pruebas PASARON")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            rc = main()
    except Exception as e:
        print(out.getvalue())
        print(f"[ERROR] {e}")
        rc = 1
    else:
        print(out.getvalue())

    log_path = os.path.join(os.path.dirname(__file__), "logs", "test_turno_horario_vigencia_console.txt")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(out.getvalue())
        if rc != 0:
            f.write("\n[RESULTADO] FAIL\n")
        else:
            f.write("\n[RESULTADO] PASS\n")

    sys.exit(rc)
