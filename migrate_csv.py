"""
migrate_csv.py
Migra registros de un archivo CSV de Hikvision iVMS-4200 a la base de datos PostgreSQL.
"""
import csv
import sys
import os
from datetime import datetime
from backend.database import SessionLocal
from backend.models import RegistroAsistencia


def migrate(csv_path):
    if not os.path.exists(csv_path):
        print(f"Archivo {csv_path} no encontrado.")
        return

    db = SessionLocal()
    added = 0
    try:
        with open(csv_path, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nombre = row.get("Card Holder", "").strip()
                if not nombre:
                    continue

                event_time_str = row.get("Event Time", "")
                if not event_time_str:
                    continue

                try:
                    dt = datetime.strptime(event_time_str, "%Y-%m-%d %H:%M:%S")
                    fecha = dt.date()
                    hora  = dt.time()
                    # evento_raw: guardamos el string ISO original del timestamp
                    evento_raw = dt.isoformat()
                except ValueError:
                    continue

                # Evitar duplicados
                existe = db.query(RegistroAsistencia).filter(
                    RegistroAsistencia.nombre_empleado == nombre,
                    RegistroAsistencia.fecha == fecha,
                    RegistroAsistencia.hora  == hora
                ).first()

                if not existe:
                    reg = RegistroAsistencia(
                        empleado_id    =row.get("Employee ID", ""),
                        nombre_empleado=nombre,
                        fecha          =fecha,
                        hora           =hora,
                        tipo_evento    =row.get("Event Type", ""),
                        evento_raw     =evento_raw,   # ← corregido: antes faltaba
                    )
                    db.add(reg)
                    added += 1

        db.commit()
        print(f"Migración completada. {added} registros insertados.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    # Fase 1: los CSVs de ejemplo se movieron a legacy/.
    path = sys.argv[1] if len(sys.argv) > 1 else "legacy/eventos.csv"
    migrate(path)
